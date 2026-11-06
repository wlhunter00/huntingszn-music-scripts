"""Offline evaluation harness for auto-cue predictions.

Run blind predictions on gold-labeled tracks and compare to hand cues.
Can be run with rule-based fallback or with LLM (when OPENAI_API_KEY is set).
Supports few-shot learning with leave-one-out cross-validation.
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_cue.features import TrackFeatures, extract_features
from auto_cue.gold import (
    GoldPool,
    GoldTrack,
    get_fewshot_examples,
    get_pool_fewshot_examples,
    load_gold_csv,
    load_gold_pool,
)
from auto_cue.llm import (
    CueAbstainError,
    FewShotExample,
    LLMAPIError,
    predict_cues_llm,
    predict_cues_rules,
    prediction_to_cue_set,
)
from auto_cue.tags import (
    cues_to_beats,
    read_track_tags,
)
from auto_cue.validate import validate_and_repair

if TYPE_CHECKING:
    pass


def analyze_errors(results: list[EvalResult]) -> dict[str, Any]:
    """Analyze error patterns: ±16 and ±32 beat errors."""
    analysis: dict[str, Any] = {
        "total_errors": 0,
        "errors_16": 0,  # Exactly 16 beats off
        "errors_32": 0,  # Exactly 32 beats off
        "errors_other": 0,
        "cue4_errors_16": 0,
        "cue4_errors_32": 0,
        "cue6_errors_16": 0,
        "cue6_errors_32": 0,
    }

    for result in results:
        if result.abstained:
            continue

        for slot, error in result.errors.items():
            if error <= 1.0:
                continue

            analysis["total_errors"] += 1

            if 15 <= error <= 17:
                analysis["errors_16"] += 1
                if slot == 3:
                    analysis["cue4_errors_16"] += 1
                elif slot == 5:
                    analysis["cue6_errors_16"] += 1
            elif 31 <= error <= 33:
                analysis["errors_32"] += 1
                if slot == 3:
                    analysis["cue4_errors_32"] += 1
                elif slot == 5:
                    analysis["cue6_errors_32"] += 1
            else:
                analysis["errors_other"] += 1

    return analysis


def compute_candidate_recall(
    results: list[EvalResult],
    features_cache: dict[str, TrackFeatures],
) -> dict[str, dict[str, Any]]:
    """Compute candidate recall: was the gold drop in the candidate set?

    Args:
        results: List of evaluation results
        features_cache: Cache of TrackFeatures by filename

    Returns:
        Dict with cue4 and cue6 recall stats
    """
    stats = {
        "cue4": {"gold_in_candidates": 0, "gold_not_in_candidates": 0, "total_with_gold": 0},
        "cue6": {"gold_in_candidates": 0, "gold_not_in_candidates": 0, "total_with_gold": 0},
    }

    for result in results:
        features = features_cache.get(result.track_name)
        if features is None:
            continue

        candidates = set(features.drop_candidates)

        # Check cue4 (slot 3)
        if 3 in result.gold_cues:
            gold_beat = round(result.gold_cues[3])
            stats["cue4"]["total_with_gold"] += 1
            # Check if gold is within 1 beat of any candidate
            if any(abs(c - gold_beat) <= 1 for c in candidates):
                stats["cue4"]["gold_in_candidates"] += 1
            else:
                stats["cue4"]["gold_not_in_candidates"] += 1

        # Check cue6 (slot 5)
        if 5 in result.gold_cues:
            gold_beat = round(result.gold_cues[5])
            stats["cue6"]["total_with_gold"] += 1
            if any(abs(c - gold_beat) <= 1 for c in candidates):
                stats["cue6"]["gold_in_candidates"] += 1
            else:
                stats["cue6"]["gold_not_in_candidates"] += 1

    # Compute recall percentages
    for cue in ["cue4", "cue6"]:
        total = stats[cue]["total_with_gold"]
        if total > 0:
            stats[cue]["recall"] = stats[cue]["gold_in_candidates"] / total
        else:
            stats[cue]["recall"] = 0.0

    return stats


def results_by_bpm_band(results: list[EvalResult]) -> dict[str, dict[str, Any]]:
    """Group results by BPM band."""
    bands: dict[str, list[EvalResult]] = {}

    for result in results:
        band = result.genre_bucket or "unknown"
        if band not in bands:
            bands[band] = []
        bands[band].append(result)

    stats: dict[str, dict[str, Any]] = {}
    for band, band_results in bands.items():
        total = len(band_results)
        processed = sum(1 for r in band_results if not r.abstained)
        cue4_hits = sum(
            1 for r in band_results
            if not r.abstained and r.errors.get(3, 999) <= 1
        )
        cue6_hits = sum(
            1 for r in band_results
            if not r.abstained and r.errors.get(5, 999) <= 1
        )

        stats[band] = {
            "total": total,
            "processed": processed,
            "abstained": total - processed,
            "cue4_hits": cue4_hits,
            "cue6_hits": cue6_hits,
            "cue4_all": cue4_hits / total * 100 if total else 0,
            "cue6_all": cue6_hits / total * 100 if total else 0,
        }

    return stats


@dataclass
class GoldCues:
    """Gold cue positions for a track."""
    path: str
    bpm: float
    cues: dict[int, float]  # slot (0-7) -> beat position


@dataclass
class EvalResult:
    """Evaluation result for a single track."""
    track_name: str
    gold_cues: dict[int, float] = field(default_factory=dict)
    predicted_cues: dict[int, int] = field(default_factory=dict)  # Only emitted cues
    errors: dict[int, float] = field(default_factory=dict)
    emitted_slots: list[int] = field(default_factory=list)  # Slots where we emitted a cue
    nulled_slots: list[int] = field(default_factory=list)  # Slots nulled due to low confidence
    abstained: bool = False
    abstain_reason: str = ""
    validation_errors: list[str] = field(default_factory=list)
    is_api_error: bool = False  # True for API/auth/HTTP errors (not real abstentions)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    reasoning_effort: str = ""
    genre_bucket: str = ""
    quirks: list[str] = field(default_factory=list)


@dataclass
class EvalSummary:
    """Summary metrics across all evaluated tracks.

    Per-cue metrics:
    - Precision: correct / emitted (accuracy among cues we emit)
    - Coverage: emitted / gold_total (% of cues we emit)
    - Accuracy: correct / gold_total (traditional accuracy)

    A wrong emitted cue is far worse than unknown.
    """
    total: int = 0
    processed: int = 0
    abstained: int = 0
    api_errors: int = 0

    per_cue_errors: dict[int, list[float]] = field(default_factory=dict)
    per_cue_correct: dict[int, int] = field(default_factory=dict)  # Correct emitted cues
    per_cue_emitted: dict[int, int] = field(default_factory=dict)  # Total emitted cues
    per_cue_total: dict[int, int] = field(default_factory=dict)   # Legacy (same as emitted)

    gold_cue_totals: dict[int, int] = field(default_factory=dict)  # Tracks with gold for this slot

    all_8_correct: int = 0

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model: str = ""
    reasoning_effort: str = ""

    @property
    def abstain_rate(self) -> float:
        return self.abstained / self.total if self.total > 0 else 0.0

    @property
    def api_error_rate(self) -> float:
        return self.api_errors / self.total if self.total > 0 else 0.0

    def cue_precision(self, slot: int, tolerance: float = 1.0) -> float:
        """Precision: correct / emitted (accuracy among cues we emit)."""
        emitted = self.per_cue_emitted.get(slot, 0)
        if emitted == 0:
            return 0.0
        return self.per_cue_correct.get(slot, 0) / emitted

    def cue_coverage(self, slot: int) -> float:
        """Coverage: emitted / gold_total (% of cues we emit)."""
        gold_total = self.gold_cue_totals.get(slot, 0)
        if gold_total == 0:
            return 0.0
        return self.per_cue_emitted.get(slot, 0) / gold_total

    def cue_accuracy_processed(self, slot: int, tolerance: float = 1.0) -> float:
        """Accuracy over processed (non-abstained) songs only."""
        total = self.per_cue_total.get(slot, 0)
        if total == 0:
            return 0.0
        return self.per_cue_correct.get(slot, 0) / total

    def cue_accuracy_all(self, slot: int, tolerance: float = 1.0) -> float:
        """Accuracy over ALL songs (abstains count as misses)."""
        total = self.gold_cue_totals.get(slot, 0)
        if total == 0:
            return 0.0
        return self.per_cue_correct.get(slot, 0) / total

    def mean_cue_error(self, slot: int) -> float:
        errors = self.per_cue_errors.get(slot, [])
        if not errors:
            return float('inf')
        return sum(errors) / len(errors)


def load_gold_cues_csv(csv_path: Path) -> dict[str, GoldCues]:
    """Load gold cues from cues.csv, excluding MIK Energy cues."""
    gold = {}

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            path = row.get("path", "")
            if not path:
                continue

            if "Energy" in row.get("name", ""):
                continue

            if row.get("kind") != "CUE":
                continue

            if path not in gold:
                try:
                    bpm = float(row.get("bpm") or 0)
                except ValueError:
                    bpm = 0.0
                gold[path] = GoldCues(path=path, bpm=bpm, cues={})

            try:
                index = int(row["index"])
                beat = float(row["beat"])
                gold[path].cues[index] = beat
            except (ValueError, KeyError):
                pass

    return {p: g for p, g in gold.items() if len(g.cues) >= 4}


def load_gold_from_files(audio_dir: Path) -> dict[str, GoldCues]:
    """Load gold cues directly from audio files in a directory."""
    gold = {}

    for audio_file in audio_dir.glob("*.mp3"):
        tags = read_track_tags(audio_file)
        if not tags.markers2 or not tags.beatgrid:
            continue

        cue_beats = cues_to_beats(tags.markers2, tags.beatgrid)
        if len(cue_beats) < 4:
            continue

        gold[audio_file.name] = GoldCues(
            path=str(audio_file),
            bpm=tags.bpm or 0.0,
            cues=cue_beats,
        )

    return gold


def evaluate_track(
    audio_path: Path,
    gold: GoldCues | GoldTrack,
    *,
    use_llm: bool = False,
    model: str = "gpt-6.1-terra",
    reasoning_effort: str = "medium",
    fewshot_examples: list[FewShotExample] | None = None,
    bpm_band: str = "",
    use_demucs: bool = False,
) -> EvalResult:
    """Run blind prediction on a single track and compare to gold.

    Args:
        audio_path: Path to audio file
        gold: Gold cue labels (GoldCues or GoldTrack)
        use_llm: Use LLM for prediction
        model: Model name
        reasoning_effort: Reasoning effort for reasoning models
        fewshot_examples: Few-shot examples (leave-one-out)
        bpm_band: BPM band hint
        use_demucs: Whether to use demucs for vocal separation
    """
    if isinstance(gold, GoldTrack):
        gold_cues = {s: b for s, b in gold.cues.items()}
        bpm = gold.bpm
        first_beat_s = gold.first_beat_s
        band = gold.bpm_band or bpm_band
        quirks = gold.quirks
    else:
        gold_cues = gold.cues
        bpm = gold.bpm
        first_beat_s = None
        band = bpm_band
        quirks = []

    result = EvalResult(
        track_name=audio_path.name,
        gold_cues=gold_cues,
        predicted_cues={},
        genre_bucket=band,
        quirks=quirks,
    )

    try:
        if first_beat_s is not None:
            features = extract_features(
                audio_path, bpm, first_beat_s, use_demucs=use_demucs
            )
        else:
            tags = read_track_tags(audio_path)
            if not tags.beatgrid:
                result.abstained = True
                result.abstain_reason = "no beatgrid"
                return result
            features = extract_features(
                audio_path,
                tags.beatgrid.bpm,
                tags.beatgrid.first_beat_s,
                use_demucs=use_demucs,
            )
    except Exception as e:
        result.abstained = True
        result.abstain_reason = f"feature extraction error: {e}"
        return result

    try:
        if use_llm and os.environ.get("OPENAI_API_KEY"):
            prediction = predict_cues_llm(
                features,
                model=model,
                reasoning_effort=reasoning_effort,
                genre_bucket=band,
                examples=fewshot_examples,
            )
            result.cost_usd = prediction.cost_usd
            result.input_tokens = prediction.input_tokens
            result.output_tokens = prediction.output_tokens
            result.model = prediction.model
            result.reasoning_effort = reasoning_effort
        else:
            prediction = predict_cues_rules(features)
    except LLMAPIError as e:
        result.abstained = True
        result.is_api_error = True
        result.abstain_reason = f"API error: {e}"
        return result
    except CueAbstainError as e:
        result.abstained = True
        result.abstain_reason = str(e)
        return result
    except Exception as e:
        result.abstained = True
        result.abstain_reason = f"error: {e}"
        return result

    cues = prediction_to_cue_set(prediction, features.total_beats)

    # Use validate_and_repair to fix ordering conflicts instead of rejecting
    cues, validation = validate_and_repair(cues)

    if not validation.valid:
        # Only hard errors (negative beats, lattice violations) cause rejection
        result.abstained = True
        result.abstain_reason = f"validation: {'; '.join(validation.errors)}"
        result.validation_errors = validation.errors
        return result

    # Track which slots were emitted and which were nulled
    result.nulled_slots = validation.nulled_slots
    result.predicted_cues = cues.to_dict()
    result.emitted_slots = [slot + 1 for slot in result.predicted_cues]  # Convert to 1-indexed

    # Calculate errors only for emitted slots
    for slot, pred_beat in result.predicted_cues.items():
        if slot in gold_cues:
            error = abs(pred_beat - gold_cues[slot])
            result.errors[slot] = error

    return result


def compute_summary(results: list[EvalResult], tolerance: float = 1.0) -> EvalSummary:
    """Compute summary metrics from evaluation results.

    Per-cue metrics:
    - Precision: correct / emitted (accuracy among cues we emit)
    - Coverage: emitted / gold_total (% of cues we emit)
    - Accuracy: correct / gold_total (traditional accuracy)
    """
    summary = EvalSummary()
    summary.total = len(results)

    for result in results:
        summary.total_cost_usd += result.cost_usd
        summary.total_input_tokens += result.input_tokens
        summary.total_output_tokens += result.output_tokens
        if result.model:
            summary.model = result.model
        if result.reasoning_effort:
            summary.reasoning_effort = result.reasoning_effort

        # Count gold cues for all tracks (including abstained)
        for slot in range(8):
            if slot in result.gold_cues:
                summary.gold_cue_totals[slot] = summary.gold_cue_totals.get(slot, 0) + 1

        if result.abstained:
            summary.abstained += 1
            if result.is_api_error:
                summary.api_errors += 1
            continue

        summary.processed += 1
        all_correct = True

        # Track emitted cues for precision/coverage
        for slot in result.predicted_cues.keys():
            summary.per_cue_emitted[slot] = summary.per_cue_emitted.get(slot, 0) + 1

        for slot in range(8):
            if slot in result.errors:
                error = result.errors[slot]

                if slot not in summary.per_cue_errors:
                    summary.per_cue_errors[slot] = []
                summary.per_cue_errors[slot].append(error)

                summary.per_cue_total[slot] = summary.per_cue_total.get(slot, 0) + 1

                if error <= tolerance:
                    summary.per_cue_correct[slot] = summary.per_cue_correct.get(slot, 0) + 1
                else:
                    all_correct = False
            elif slot in result.gold_cues:
                all_correct = False

        if all_correct and len(result.predicted_cues) == 8:
            summary.all_8_correct += 1

    return summary


def format_results_table(results: list[EvalResult], include_abstain_details: bool = True) -> str:
    """Format results as a markdown table.

    Uses 1-indexed cue labels (Cue 1-8) matching Serato's A-H slots.
    Internally, slot indices are 0-7.
    """
    lines = []
    header = "| Track | Cue 1 | Cue 2 | Cue 3 | Cue 4 | Cue 5 | Cue 6 | Cue 7 | Cue 8 | Status |"
    lines.append(header)
    sep = "|-------|-------|-------|-------|-------|-------|-------|-------|-------|--------|"
    lines.append(sep)

    abstain_details = []
    api_error_details = []

    for result in results:
        row = [result.track_name[:30]]

        if result.abstained:
            row.extend(["—"] * 8)
            if result.is_api_error:
                row.append("ERROR")
                if include_abstain_details:
                    api_error_details.append((result.track_name, result.abstain_reason))
            else:
                row.append("ABSTAIN")
                if include_abstain_details:
                    abstain_details.append((result.track_name, result.abstain_reason))
        else:
            for slot in range(8):  # slot 0-7 corresponds to Cue 1-8
                if slot in result.errors:
                    error = result.errors[slot]
                    if error <= 1.0:
                        row.append(f"✓ {error:.1f}")
                    else:
                        row.append(f"✗ {error:.1f}")
                elif slot in result.gold_cues:
                    row.append("MISS")
                else:
                    row.append("—")

            all_good = all(e <= 1.0 for e in result.errors.values())
            row.append("✓" if all_good else "partial")

        lines.append("| " + " | ".join(row) + " |")

    if api_error_details:
        lines.append("")
        lines.append("### API Errors (NOT abstentions - should fail fast)")
        lines.append("")
        for track, reason in api_error_details:
            lines.append(f"- **{track}**: {reason}")

    if abstain_details:
        lines.append("")
        lines.append("### Abstain Decisions")
        lines.append("")
        for track, reason in abstain_details:
            lines.append(f"- **{track}**: {reason}")

    return "\n".join(lines)


def format_summary(summary: EvalSummary, tolerance: float = 1.0) -> str:
    """Format summary as text.

    Reports per-cue metrics:
    - Precision: correct / emitted (accuracy among cues we emit)
    - Coverage: emitted / gold_total (% of cues we emit)
    - Accuracy: correct / gold_total (traditional accuracy)

    Uses 1-indexed cue labels (Cue 1-8).
    """
    lines = []
    if summary.model:
        model_info = summary.model
        if summary.reasoning_effort:
            model_info += f" (reasoning_effort={summary.reasoning_effort})"
        lines.append(f"Model: {model_info}")
    lines.append(f"Total tracks: {summary.total}")
    lines.append(f"Processed: {summary.processed}")
    lines.append(f"Abstained: {summary.abstained} ({summary.abstain_rate:.1%})")
    if summary.api_errors > 0:
        lines.append(f"  - API errors: {summary.api_errors} (NOT real abstentions)")
        lines.append(f"  - True abstentions: {summary.abstained - summary.api_errors}")
    lines.append("")

    if summary.total_cost_usd > 0:
        cost_per_track = summary.total_cost_usd / summary.total if summary.total > 0 else 0
        total_cost = summary.total_cost_usd
        lines.append(f"API Cost: ${total_cost:.4f} total, ${cost_per_track:.4f}/track")
        in_tok = summary.total_input_tokens
        out_tok = summary.total_output_tokens
        lines.append(f"Tokens: {in_tok:,} in, {out_tok:,} out")
        lines.append("")

    # Per-cue precision/coverage/accuracy
    lines.append("Per-cue PRECISION/COVERAGE/ACCURACY:")
    lines.append("  (Precision=correct/emitted, Coverage=emitted/gold, Accuracy=correct/gold)")
    lines.append("")
    for slot in range(8):  # slot 0-7 = Cue 1-8
        prec = summary.cue_precision(slot, tolerance)
        cov = summary.cue_coverage(slot)
        acc = summary.cue_accuracy_all(slot, tolerance)
        emitted = summary.per_cue_emitted.get(slot, 0)
        correct = summary.per_cue_correct.get(slot, 0)
        gold_total = summary.gold_cue_totals.get(slot, 0)
        if gold_total > 0:
            lines.append(
                f"  Cue {slot+1}: P={prec:.0%} ({correct}/{emitted}) | "
                f"C={cov:.0%} ({emitted}/{gold_total}) | "
                f"A={acc:.0%} ({correct}/{gold_total})"
            )
        else:
            lines.append(f"  Cue {slot+1}: no gold labels")

    lines.append("")
    lines.append(f"All 8 correct: {summary.all_8_correct}/{summary.processed} (processed)")

    # Cue 4 and Cue 6 are the key metrics (slot 3 and 5 internally)
    cue4_acc_processed = summary.cue_accuracy_processed(3, tolerance)
    cue6_acc_processed = summary.cue_accuracy_processed(5, tolerance)
    cue4_acc_all = summary.cue_accuracy_all(3, tolerance)
    cue6_acc_all = summary.cue_accuracy_all(5, tolerance)

    lines.append(
        f"Cue 4: {cue4_acc_processed:.1%} processed, {cue4_acc_all:.1%} all (spec: >=85%)"
    )
    lines.append(
        f"Cue 6: {cue6_acc_processed:.1%} processed, {cue6_acc_all:.1%} all (spec: >=85%)"
    )
    lines.append(f"Abstain rate: {summary.abstain_rate:.1%} (spec: <= 35%)")

    return "\n".join(lines)


def run_eval(
    audio_dir: Path,
    *,
    gold_csv: Path | None = None,
    use_llm: bool = False,
    model: str = "gpt-6.1-terra",
    reasoning_effort: str = "medium",
    use_fewshot: bool = True,
    use_demucs: bool = False,
    output_md: Path | None = None,
    pool_dir: Path | None = None,
) -> tuple[list[EvalResult], EvalSummary]:
    """Run evaluation on all tracks in a directory.

    Args:
        audio_dir: Directory containing audio files to evaluate
        gold_csv: CSV with gold labels (required for new QA format)
        use_llm: Use LLM for prediction (requires OPENAI_API_KEY)
        model: Model to use for LLM prediction
        reasoning_effort: Reasoning effort for reasoning models
        use_fewshot: Use few-shot examples from pool
        use_demucs: Use demucs for vocal separation
        output_md: Optional path to write markdown report
        pool_dir: Directory with gold pool (gold_pool_clean.csv, audio_sel.csv, g2_NNN.mp3)

    Returns:
        (results, summary)
    """
    gold_tracks: dict[str, GoldTrack] = {}
    gold_cues_data: dict[str, GoldCues] = {}
    features_cache: dict[str, TrackFeatures] = {}

    if gold_csv and gold_csv.exists():
        gold_tracks = load_gold_csv(gold_csv)
    else:
        gold_cues_data = load_gold_from_files(audio_dir)

    gold_pool: GoldPool | None = None
    if use_fewshot and pool_dir and pool_dir.exists():
        pool_csv = pool_dir / "gold_pool_clean.csv"
        if not pool_csv.exists():
            pool_csv = pool_dir / "gold_pool.csv"
        audio_sel = pool_dir / "audio_sel.csv"
        if pool_csv.exists():
            gold_pool = load_gold_pool(pool_csv, audio_sel)
            print(f"Loaded gold pool: {len(gold_pool.tracks)} tracks, "
                  f"{len(gold_pool.get_tracks_with_audio())} with audio mapping")

    results = []

    for audio_file in sorted(audio_dir.glob("*.mp3")):
        gold: GoldCues | GoldTrack | None = None
        fewshot: list[FewShotExample] | None = None

        if audio_file.name in gold_tracks:
            gold = gold_tracks[audio_file.name]
            if use_fewshot and use_llm:
                if gold_pool:
                    title = Path(gold.source_path).stem if gold.source_path else gold.filename
                    exclude_paths = gold_pool.paths_to_exclude(
                        artist="",
                        title=title,
                        source_path=gold.source_path,
                        bpm=gold.bpm,
                        duration_s=gold.duration_s,
                    )
                    fewshot = get_pool_fewshot_examples(
                        gold_pool,
                        target_bpm=gold.bpm,
                        target_beats=gold.total_beats,
                        audio_dir=pool_dir,
                        max_examples=5,
                        features_cache=features_cache,
                        exclude_paths=exclude_paths,
                    )
                else:
                    fewshot = get_fewshot_examples(
                        gold_tracks,
                        exclude_filename=audio_file.name,
                        target_bpm=gold.bpm,
                        target_beats=gold.total_beats,
                        audio_dir=audio_dir,
                        max_examples=5,
                        features_cache=features_cache,
                    )
        else:
            for key, g in gold_cues_data.items():
                if audio_file.name in key or key.endswith(audio_file.name):
                    gold = g
                    break
            if gold is None:
                gold = gold_cues_data.get(audio_file.name)

            if gold is None:
                tags = read_track_tags(audio_file)
                if tags.markers2 and tags.beatgrid:
                    cue_beats = cues_to_beats(tags.markers2, tags.beatgrid)
                    if len(cue_beats) >= 4:
                        gold = GoldCues(
                            path=str(audio_file),
                            bpm=tags.bpm or 0.0,
                            cues=cue_beats,
                        )

        if gold is None:
            continue

        result = evaluate_track(
            audio_file, gold,
            use_llm=use_llm,
            model=model,
            reasoning_effort=reasoning_effort,
            fewshot_examples=fewshot,
            bpm_band=gold.bpm_band if isinstance(gold, GoldTrack) else "",
            use_demucs=use_demucs,
        )
        results.append(result)

        print(f"\n=== {audio_file.name} ===")
        if result.genre_bucket:
            print(f"Genre: {result.genre_bucket}")
        if result.quirks:
            print(f"Quirks: {', '.join(result.quirks)}")

        if result.abstained:
            status = "API ERROR" if result.is_api_error else "ABSTAINED"
            print(f"{status}: {result.abstain_reason}")
        else:
            gold_cues = gold.cues if isinstance(gold, GoldTrack) else gold.cues
            gold_1indexed = {k+1: v for k, v in sorted(gold_cues.items())}
            pred_1indexed = {k+1: v for k, v in sorted(result.predicted_cues.items())}
            print(f"Gold:      {gold_1indexed}")
            print(f"Predicted: {pred_1indexed}")
            print("Errors (beats):")
            for slot in sorted(result.errors.keys()):
                err = result.errors[slot]
                status = "✓" if err <= 1.0 else "✗"
                gold_beat = gold_cues.get(slot, 0)
                pred_beat = result.predicted_cues.get(slot, 0)
                print(
                    f"  Cue {slot+1}: gold={gold_beat:.1f}, pred={pred_beat}, "
                    f"err={err:.1f} {status}"
                )

    summary = compute_summary(results)
    error_analysis = analyze_errors(results)
    bpm_stats = results_by_bpm_band(results)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(format_summary(summary))

    print("\n" + "=" * 60)
    print("ERROR ANALYSIS")
    print("=" * 60)
    print(f"Total errors (>1 beat): {error_analysis['total_errors']}")
    print(f"  ±16 beat errors: {error_analysis['errors_16']}")
    print(f"  ±32 beat errors: {error_analysis['errors_32']}")
    print(f"  Other errors: {error_analysis['errors_other']}")
    print(f"Cue4 ±16: {error_analysis['cue4_errors_16']}, ±32: {error_analysis['cue4_errors_32']}")
    print(f"Cue6 ±16: {error_analysis['cue6_errors_16']}, ±32: {error_analysis['cue6_errors_32']}")

    print("\n" + "=" * 60)
    print("PER-BPM BAND")
    print("=" * 60)
    for band, stats in sorted(bpm_stats.items()):
        print(f"{band}: {stats['total']} tracks, {stats['processed']} processed")
        print(f"  Cue4: {stats['cue4_hits']}/{stats['total']} = {stats['cue4_all']:.0f}%")
        print(f"  Cue6: {stats['cue6_hits']}/{stats['total']} = {stats['cue6_all']:.0f}%")

    if output_md:
        with open(output_md, "w") as f:
            f.write("# Blind Evaluation Results\n\n")
            mode = "LLM" if use_llm and os.environ.get("OPENAI_API_KEY") else "Rule-based"
            f.write(f"Mode: {mode}\n")
            f.write(f"Model: {model}\n")
            f.write(f"Few-shot: {'Yes' if use_fewshot else 'No'}\n\n")
            f.write("## Per-Track Results\n\n")
            f.write(format_results_table(results))
            f.write("\n\n## Summary\n\n```\n")
            f.write(format_summary(summary))
            f.write("\n```\n")
            f.write("\n## Error Analysis\n\n")
            f.write(f"- Total errors (>1 beat): {error_analysis['total_errors']}\n")
            f.write(f"- ±16 beat errors: {error_analysis['errors_16']}\n")
            f.write(f"- ±32 beat errors: {error_analysis['errors_32']}\n")
            f.write(f"- Other errors: {error_analysis['errors_other']}\n")
            f.write("\n## Per-BPM Band\n\n")
            f.write("| BPM Band | Tracks | Cue4 | Cue6 |\n")
            f.write("|----------|--------|------|------|\n")
            for band, stats in sorted(bpm_stats.items()):
                f.write(
                    f"| {band} | {stats['total']} | "
                    f"{stats['cue4_all']:.0f}% | {stats['cue6_all']:.0f}% |\n"
                )
        print(f"\nResults written to: {output_md}")

    return results, summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for evaluation."""
    parser = argparse.ArgumentParser(
        prog="auto-cue-eval",
        description="Run blind evaluation of auto-cue predictions against gold labels",
    )
    parser.add_argument(
        "audio_dir",
        type=Path,
        help="Directory containing audio files to evaluate",
    )
    parser.add_argument(
        "--gold-csv",
        type=Path,
        help="CSV file with gold labels (required for new QA format)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM for prediction (requires OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default="gpt-6.1-terra",
        help="Model to use for LLM prediction (default: gpt-6.1-terra)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="medium",
        choices=["low", "medium", "high"],
        help="Reasoning effort for reasoning models (default: medium)",
    )
    parser.add_argument(
        "--no-fewshot",
        action="store_true",
        help="Disable few-shot examples (for ablation study)",
    )
    parser.add_argument(
        "--use-demucs",
        action="store_true",
        help="Use demucs vocal separation for vocal activity feature",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output markdown file for results",
    )

    args = parser.parse_args(argv)

    if not args.audio_dir.is_dir():
        print(f"Error: {args.audio_dir} is not a directory", file=__import__('sys').stderr)
        return 1

    if args.use_llm and not os.environ.get("OPENAI_API_KEY"):
        print("Warning: --use-llm set but OPENAI_API_KEY not found, using rule-based fallback")

    results, summary = run_eval(
        args.audio_dir,
        gold_csv=args.gold_csv,
        use_llm=args.use_llm,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        use_fewshot=not args.no_fewshot,
        use_demucs=args.use_demucs,
        output_md=args.output,
    )

    if summary.api_errors > 0:
        print(f"\nERROR: {summary.api_errors} API error(s) occurred", file=__import__('sys').stderr)
        return 3  # Distinct exit code for API errors

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
