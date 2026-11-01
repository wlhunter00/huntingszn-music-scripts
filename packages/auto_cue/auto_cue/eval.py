"""Offline evaluation harness for auto-cue predictions.

Run blind predictions on gold-labeled tracks and compare to hand cues.
Can be run with rule-based fallback or with LLM (when OPENAI_API_KEY is set).
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_cue.tags import (
    read_track_tags,
    write_track_markers2,
    Markers2Data,
    cues_to_beats,
)
from auto_cue.features import extract_features
from auto_cue.llm import (
    predict_cues_llm,
    predict_cues_rules,
    prediction_to_cue_set,
    LLMAPIError,
    CueAbstainError,
)
from auto_cue.validate import validate_cue_set


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
    predicted_cues: dict[int, int] = field(default_factory=dict)
    errors: dict[int, float] = field(default_factory=dict)
    abstained: bool = False
    abstain_reason: str = ""
    validation_errors: list[str] = field(default_factory=list)
    is_api_error: bool = False  # True for API/auth/HTTP errors (not real abstentions)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    reasoning_effort: str = ""


@dataclass
class EvalSummary:
    """Summary metrics across all evaluated tracks."""
    total: int = 0
    processed: int = 0
    abstained: int = 0
    api_errors: int = 0
    
    per_cue_errors: dict[int, list[float]] = field(default_factory=dict)
    per_cue_correct: dict[int, int] = field(default_factory=dict)
    per_cue_total: dict[int, int] = field(default_factory=dict)
    
    gold_cue_totals: dict[int, int] = field(default_factory=dict)
    
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
    gold: GoldCues,
    *,
    use_llm: bool = False,
    model: str = "gpt-6-luna",
    reasoning_effort: str = "medium",
) -> EvalResult:
    """Run blind prediction on a single track and compare to gold."""
    result = EvalResult(
        track_name=audio_path.name,
        gold_cues=gold.cues,
        predicted_cues={},
    )
    
    with tempfile.TemporaryDirectory() as td:
        copy_path = Path(td) / audio_path.name
        shutil.copy2(audio_path, copy_path)
        
        original_tags = read_track_tags(copy_path)
        if not original_tags.beatgrid:
            result.abstained = True
            result.abstain_reason = "no beatgrid"
            return result
        
        write_track_markers2(copy_path, Markers2Data())
        
        try:
            features = extract_features(
                copy_path,
                original_tags.beatgrid.bpm,
                original_tags.beatgrid.first_beat_s,
            )
        except Exception as e:
            result.abstained = True
            result.abstain_reason = f"feature extraction error: {e}"
            return result
        
        try:
            if use_llm and os.environ.get("OPENAI_API_KEY"):
                prediction = predict_cues_llm(features, model=model, reasoning_effort=reasoning_effort)
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
        
        validation = validate_cue_set(cues)
        if not validation.valid:
            result.abstained = True
            result.abstain_reason = f"validation failed: {'; '.join(validation.errors)}"
            result.validation_errors = validation.errors
            return result
        
        result.predicted_cues = cues.to_dict()
        
        for slot, pred_beat in result.predicted_cues.items():
            if slot in gold.cues:
                error = abs(pred_beat - gold.cues[slot])
                result.errors[slot] = error
    
    return result


def compute_summary(results: list[EvalResult], tolerance: float = 1.0) -> EvalSummary:
    """Compute summary metrics from evaluation results."""
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
    lines.append("| Track | Cue 1 | Cue 2 | Cue 3 | Cue 4 | Cue 5 | Cue 6 | Cue 7 | Cue 8 | Status |")
    lines.append("|-------|-------|-------|-------|-------|-------|-------|-------|-------|--------|")
    
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
    
    Reports accuracy both over processed songs and over ALL songs.
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
        lines.append(f"API Cost: ${summary.total_cost_usd:.4f} total, ${cost_per_track:.4f}/track")
        lines.append(f"Tokens: {summary.total_input_tokens:,} in, {summary.total_output_tokens:,} out")
        lines.append("")
    
    lines.append(f"Per-cue accuracy OVER PROCESSED (within {tolerance} beat):")
    for slot in range(8):  # slot 0-7 = Cue 1-8
        acc = summary.cue_accuracy_processed(slot, tolerance)
        mean_err = summary.mean_cue_error(slot)
        total = summary.per_cue_total.get(slot, 0)
        correct = summary.per_cue_correct.get(slot, 0)
        if total > 0:
            lines.append(f"  Cue {slot+1}: {correct}/{total} = {acc:.1%} (mean error: {mean_err:.1f} beats)")
        else:
            lines.append(f"  Cue {slot+1}: no data")
    
    lines.append("")
    lines.append(f"Per-cue accuracy OVER ALL SONGS (abstains count as misses):")
    for slot in range(8):  # slot 0-7 = Cue 1-8
        acc = summary.cue_accuracy_all(slot, tolerance)
        gold_total = summary.gold_cue_totals.get(slot, 0)
        correct = summary.per_cue_correct.get(slot, 0)
        if gold_total > 0:
            lines.append(f"  Cue {slot+1}: {correct}/{gold_total} = {acc:.1%}")
        else:
            lines.append(f"  Cue {slot+1}: no gold labels")
    
    lines.append("")
    lines.append(f"All 8 correct: {summary.all_8_correct}/{summary.processed} (processed)")
    
    # Cue 4 and Cue 6 are the key metrics (slot 3 and 5 internally)
    cue4_acc_processed = summary.cue_accuracy_processed(3, tolerance)
    cue6_acc_processed = summary.cue_accuracy_processed(5, tolerance)
    cue4_acc_all = summary.cue_accuracy_all(3, tolerance)
    cue6_acc_all = summary.cue_accuracy_all(5, tolerance)
    
    lines.append(f"Cue 4 accuracy: {cue4_acc_processed:.1%} processed, {cue4_acc_all:.1%} all (spec: >= 85%)")
    lines.append(f"Cue 6 accuracy: {cue6_acc_processed:.1%} processed, {cue6_acc_all:.1%} all (spec: >= 85%)")
    lines.append(f"Abstain rate: {summary.abstain_rate:.1%} (spec: <= 35%)")
    
    return "\n".join(lines)


def run_eval(
    audio_dir: Path,
    *,
    gold_csv: Path | None = None,
    use_llm: bool = False,
    model: str = "gpt-6-luna",
    reasoning_effort: str = "medium",
    output_md: Path | None = None,
) -> tuple[list[EvalResult], EvalSummary]:
    """Run evaluation on all tracks in a directory.
    
    Args:
        audio_dir: Directory containing audio files
        gold_csv: Optional CSV with gold labels (if not provided, reads from files)
        use_llm: Use LLM for prediction (requires OPENAI_API_KEY)
        model: Model to use for LLM prediction
        output_md: Optional path to write markdown report
    
    Returns:
        (results, summary)
    """
    if gold_csv and gold_csv.exists():
        gold_data = load_gold_cues_csv(gold_csv)
    else:
        gold_data = load_gold_from_files(audio_dir)
    
    results = []
    
    for audio_file in sorted(audio_dir.glob("*.mp3")):
        gold = None
        for key, g in gold_data.items():
            if audio_file.name in key or key.endswith(audio_file.name) or audio_file.stem in key:
                gold = g
                break
        
        if gold is None:
            gold = gold_data.get(audio_file.name)
        
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
        
        result = evaluate_track(audio_file, gold, use_llm=use_llm, model=model, reasoning_effort=reasoning_effort)
        results.append(result)
        
        print(f"\n=== {audio_file.name} ===")
        if result.abstained:
            status = "API ERROR" if result.is_api_error else "ABSTAINED"
            print(f"{status}: {result.abstain_reason}")
        else:
            gold_1indexed = {k+1: v for k, v in sorted(gold.cues.items())}
            pred_1indexed = {k+1: v for k, v in sorted(result.predicted_cues.items())}
            print(f"Gold:      {gold_1indexed}")
            print(f"Predicted: {pred_1indexed}")
            print(f"Errors (beats):")
            for slot in sorted(result.errors.keys()):  # slot is 0-indexed internally
                err = result.errors[slot]
                status = "✓" if err <= 1.0 else "✗"
                gold_beat = gold.cues.get(slot, 0)
                pred_beat = result.predicted_cues.get(slot, 0)
                print(f"  Cue {slot+1}: gold={gold_beat:.0f}, pred={pred_beat}, error={err:.1f} {status}")
    
    summary = compute_summary(results)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(format_summary(summary))
    
    if output_md:
        with open(output_md, "w") as f:
            f.write("# Blind Evaluation Results\n\n")
            f.write(f"Mode: {'LLM' if use_llm and os.environ.get('OPENAI_API_KEY') else 'Rule-based'}\n")
            f.write(f"Model: {model}\n\n")
            f.write("## Per-Track Results\n\n")
            f.write(format_results_table(results))
            f.write("\n\n## Summary\n\n```\n")
            f.write(format_summary(summary))
            f.write("\n```\n")
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
        help="CSV file with gold labels (optional, reads from files if not provided)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM for prediction (requires OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default="gpt-6-luna",
        help="Model to use for LLM prediction (default: gpt-6-luna)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="medium",
        choices=["low", "medium", "high"],
        help="Reasoning effort for reasoning models (default: medium)",
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
        output_md=args.output,
    )
    
    if summary.api_errors > 0:
        print(f"\nERROR: {summary.api_errors} API error(s) occurred", file=__import__('sys').stderr)
        return 3  # Distinct exit code for API errors
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
