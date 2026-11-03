#!/usr/bin/env python3
"""Diagnose cue 4 and cue 6 misses for the best ablation arm.

Analyzes WHY drops are missed: grid problems, candidate recall, fake-outs, wrong drops, etc.
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.eval import evaluate_track, EvalResult
from auto_cue.features import extract_features, TrackFeatures, PhraseFeatures
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples, GoldTrack
from auto_cue.llm import FewShotExample
from auto_cue.tags import read_track_tags

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"


@dataclass
class DropMissAnalysis:
    """Analysis of a single cue 4 or cue 6 miss."""
    track: str
    cue_slot: int  # 3 for cue4, 5 for cue6
    bpm_band: str
    gold_beat: float
    pred_beat: int
    offset_beats: float
    
    # Cause classification
    cause: str  # grid, candidate_recall, candidate_judgment, fakeout_16, fakeout_32, wrong_drop, separate_grid, skipped, gold_questionable
    cause_detail: str
    
    # Grid analysis
    gold_on_16_lattice: bool = False
    gold_on_32_lattice: bool = False
    grid_phase_issue: bool = False
    
    # Candidate analysis
    gold_in_candidates: bool = False
    candidate_set: list[int] = field(default_factory=list)
    gold_drop_score: float = 0.0
    pred_drop_score: float = 0.0
    
    # Feature comparison (gold vs pred)
    gold_features: dict = field(default_factory=dict)
    pred_features: dict = field(default_factory=dict)


@dataclass 
class TrackDiagnostic:
    """Full diagnostic for a track."""
    track: str
    bpm: float
    bpm_band: str
    total_beats: int
    
    # Grid info
    first_beat_s: float
    serato_first_beat_s: float | None
    grid_offset_ms: float | None
    
    # Results
    gold_cues: dict[int, float] = field(default_factory=dict)
    pred_cues: dict[int, int] = field(default_factory=dict)
    errors: dict[int, float] = field(default_factory=dict)
    
    # Candidate info
    drop_candidates: list[int] = field(default_factory=list)
    candidate_scores: dict[int, float] = field(default_factory=dict)
    
    # Status
    abstained: bool = False
    abstain_reason: str = ""
    
    # Cue 4/6 misses
    cue4_miss: DropMissAnalysis | None = None
    cue6_miss: DropMissAnalysis | None = None


def get_phrase_at_beat(features: TrackFeatures, beat: int) -> PhraseFeatures | None:
    """Get the 32-beat phrase containing this beat."""
    for p in features.phrases_32:
        if p.beat_start <= beat < p.beat_start + 32:
            return p
    return None


def get_phrase_features_dict(p: PhraseFeatures | None) -> dict:
    """Extract key features as dict."""
    if p is None:
        return {}
    return {
        "rms_db": round(p.rms_db, 1),
        "low_db": round(p.low_db, 1),
        "delta_low": round(p.delta_low, 2),
        "kick_density": round(p.kick_density, 2),
        "delta_kick": round(p.delta_kick, 2),
        "vocal_activity": round(p.vocal_activity, 2),
        "build_score": round(p.build_score, 2),
        "snare_roll": round(p.snare_roll, 2),
        "contrast_score": round(p.contrast_score, 2),
        "novelty_score": round(p.novelty_score, 2),
        "pre_drop_gap": round(p.pre_drop_gap, 2),
        "post_sustain": round(p.post_sustain, 2),
        "track_pct": round(p.track_pct, 2),
        "drop_score": round(p.drop_score, 2),
        "is_drop_candidate": p.is_drop_candidate,
    }


def classify_miss(
    cue_slot: int,
    gold_beat: float,
    pred_beat: int,
    features: TrackFeatures,
    gold_cues: dict[int, float],
    pred_cues: dict[int, int],
) -> DropMissAnalysis:
    """Classify a cue 4 or cue 6 miss."""
    offset = pred_beat - gold_beat
    abs_offset = abs(offset)
    bpm_band = features.bpm_band
    
    analysis = DropMissAnalysis(
        track=features.path.name,
        cue_slot=cue_slot,
        bpm_band=bpm_band,
        gold_beat=gold_beat,
        pred_beat=pred_beat,
        offset_beats=offset,
        cause="unknown",
        cause_detail="",
    )
    
    # Grid analysis
    gold_beat_int = round(gold_beat)
    analysis.gold_on_16_lattice = (gold_beat_int % 16 == 0)
    analysis.gold_on_32_lattice = (gold_beat_int % 32 == 0)
    
    # Check if gold is fractional (grid misalignment)
    gold_fraction = abs(gold_beat - round(gold_beat))
    if gold_fraction > 0.1:
        analysis.grid_phase_issue = True
    
    # Candidate analysis
    analysis.candidate_set = features.drop_candidates[:10]
    
    # Check if gold is in candidates (within 1 beat)
    gold_in_cands = any(abs(c - gold_beat) <= 1 for c in features.drop_candidates)
    analysis.gold_in_candidates = gold_in_cands
    
    # Get drop scores
    gold_phrase = get_phrase_at_beat(features, int(gold_beat))
    pred_phrase = get_phrase_at_beat(features, pred_beat)
    
    if gold_phrase:
        analysis.gold_drop_score = gold_phrase.drop_score
        analysis.gold_features = get_phrase_features_dict(gold_phrase)
    if pred_phrase:
        analysis.pred_drop_score = pred_phrase.drop_score
        analysis.pred_features = get_phrase_features_dict(pred_phrase)
    
    # Classify cause
    
    # 1. Grid problem
    if gold_fraction > 0.1:
        analysis.cause = "grid"
        analysis.cause_detail = f"Gold beat {gold_beat:.3f} not on integer grid (fraction={gold_fraction:.3f})"
        return analysis
    
    if not analysis.gold_on_32_lattice:
        analysis.cause = "grid"
        analysis.cause_detail = f"Gold beat {gold_beat_int} not on 32-beat lattice"
        return analysis
    
    # 2. Candidate problem
    if not gold_in_cands:
        analysis.cause = "candidate_recall"
        analysis.cause_detail = f"Gold beat {gold_beat_int} not in candidate set {analysis.candidate_set[:5]}"
        return analysis
    
    # 3. Fake-out / run-up (±16 or ±32)
    if 15 <= abs_offset <= 17:
        if offset > 0:
            analysis.cause = "fakeout_16"
            analysis.cause_detail = f"Picked {pred_beat} which is 16 beats AFTER gold {gold_beat_int} (post-drop run-up?)"
        else:
            analysis.cause = "fakeout_16"
            analysis.cause_detail = f"Picked {pred_beat} which is 16 beats BEFORE gold {gold_beat_int} (pre-drop run-up?)"
        return analysis
    
    if 31 <= abs_offset <= 33:
        if offset > 0:
            analysis.cause = "fakeout_32"
            analysis.cause_detail = f"Picked {pred_beat} which is 32 beats AFTER gold {gold_beat_int}"
        else:
            analysis.cause = "fakeout_32"
            analysis.cause_detail = f"Picked {pred_beat} which is 32 beats BEFORE gold {gold_beat_int}"
        return analysis
    
    # 4. Wrong drop entirely
    if cue_slot == 5:  # cue 6
        # Check if it picked an earlier drop (like cue 4's drop)
        cue4_gold = gold_cues.get(3, 0)
        if abs(pred_beat - cue4_gold) <= 1:
            analysis.cause = "wrong_drop"
            analysis.cause_detail = f"Picked first drop ({pred_beat}) instead of last drop ({gold_beat_int})"
            return analysis
        
        # Check if the picked drop is actually the last drop
        later_drops = [c for c in features.drop_candidates if c > pred_beat]
        if later_drops:
            analysis.cause = "wrong_drop"
            analysis.cause_detail = f"Picked {pred_beat} but later drops exist: {later_drops[:3]}"
            return analysis
    
    if cue_slot == 3:  # cue 4
        # Check if it picked a later drop
        cue6_gold = gold_cues.get(5, 0)
        if cue6_gold and abs(pred_beat - cue6_gold) <= 1:
            analysis.cause = "wrong_drop"
            analysis.cause_detail = f"Picked last drop ({pred_beat}) instead of first drop ({gold_beat_int})"
            return analysis
    
    # 5. Separate grid issue (cues 5-8 not synced with 1-4)
    if cue_slot == 5:  # cue 6
        cue4_gold = gold_cues.get(3, 0)
        cue6_gold = gold_beat
        cue4_pred = pred_cues.get(3, 0)
        cue6_pred = pred_beat
        
        # Check if gold cues are on different grids
        if cue4_gold and cue6_gold:
            gold_gap = cue6_gold - cue4_gold
            if gold_gap % 32 != 0 and gold_gap % 16 == 0:
                analysis.cause = "separate_grid"
                analysis.cause_detail = f"Gold cue4={cue4_gold}, cue6={cue6_gold}, gap={gold_gap} not 32-synced"
                return analysis
    
    # Default: judgment failure (gold was in candidates, model picked wrong one)
    analysis.cause = "candidate_judgment"
    analysis.cause_detail = f"Gold ({gold_beat_int}, score={analysis.gold_drop_score:.1f}) was in candidates but model picked ({pred_beat}, score={analysis.pred_drop_score:.1f})"
    
    return analysis


def diagnose_track(
    audio_path: Path,
    gold: GoldTrack,
    fewshot: list[FewShotExample] | None,
    features_cache: dict[str, TrackFeatures],
) -> TrackDiagnostic:
    """Run full diagnostic on a single track."""
    
    diag = TrackDiagnostic(
        track=audio_path.name,
        bpm=gold.bpm,
        bpm_band=gold.bpm_band or "",
        total_beats=gold.total_beats,
        first_beat_s=gold.first_beat_s,
        serato_first_beat_s=None,
        grid_offset_ms=None,
        gold_cues={s: b for s, b in gold.cues.items()},
    )
    
    # Check Serato grid
    try:
        tags = read_track_tags(audio_path)
        if tags.beatgrid:
            diag.serato_first_beat_s = tags.beatgrid.first_beat_s
            diag.grid_offset_ms = (gold.first_beat_s - tags.beatgrid.first_beat_s) * 1000
    except:
        pass
    
    # Extract features
    try:
        features = extract_features(audio_path, gold.bpm, gold.first_beat_s, use_demucs=True)
        features_cache[audio_path.name] = features
    except Exception as e:
        diag.abstained = True
        diag.abstain_reason = f"feature extraction: {e}"
        return diag
    
    diag.drop_candidates = features.drop_candidates[:10]
    diag.candidate_scores = {
        p.beat_start: p.drop_score 
        for p in features.phrases_32 
        if p.is_drop_candidate
    }
    
    # Run eval
    result = evaluate_track(
        audio_path,
        gold,
        use_llm=True,
        model=MODEL,
        reasoning_effort=REASONING,
        fewshot_examples=fewshot,
        bpm_band=gold.bpm_band or "",
        use_demucs=True,
    )
    
    if result.abstained:
        diag.abstained = True
        diag.abstain_reason = result.abstain_reason
        
        # Still classify why it abstained for cue4/cue6
        if 3 in gold.cues:
            diag.cue4_miss = DropMissAnalysis(
                track=audio_path.name,
                cue_slot=3,
                bpm_band=gold.bpm_band or "",
                gold_beat=gold.cues[3],
                pred_beat=-1,
                offset_beats=0,
                cause="skipped",
                cause_detail=result.abstain_reason,
                candidate_set=features.drop_candidates[:10],
                gold_in_candidates=any(abs(c - gold.cues[3]) <= 1 for c in features.drop_candidates),
            )
            gold_phrase = get_phrase_at_beat(features, int(gold.cues[3]))
            if gold_phrase:
                diag.cue4_miss.gold_features = get_phrase_features_dict(gold_phrase)
        
        if 5 in gold.cues:
            diag.cue6_miss = DropMissAnalysis(
                track=audio_path.name,
                cue_slot=5,
                bpm_band=gold.bpm_band or "",
                gold_beat=gold.cues[5],
                pred_beat=-1,
                offset_beats=0,
                cause="skipped",
                cause_detail=result.abstain_reason,
                candidate_set=features.drop_candidates[:10],
                gold_in_candidates=any(abs(c - gold.cues[5]) <= 1 for c in features.drop_candidates),
            )
            gold_phrase = get_phrase_at_beat(features, int(gold.cues[5]))
            if gold_phrase:
                diag.cue6_miss.gold_features = get_phrase_features_dict(gold_phrase)
        
        return diag
    
    diag.pred_cues = result.predicted_cues
    diag.errors = result.errors
    
    # Analyze cue 4 miss (slot 3)
    if 3 in result.errors and result.errors[3] > 1.0:
        diag.cue4_miss = classify_miss(
            cue_slot=3,
            gold_beat=gold.cues[3],
            pred_beat=result.predicted_cues.get(3, 0),
            features=features,
            gold_cues=gold.cues,
            pred_cues=result.predicted_cues,
        )
    
    # Analyze cue 6 miss (slot 5)
    if 5 in result.errors and result.errors[5] > 1.0:
        diag.cue6_miss = classify_miss(
            cue_slot=5,
            gold_beat=gold.cues[5],
            pred_beat=result.predicted_cues.get(5, 0),
            features=features,
            gold_cues=gold.cues,
            pred_cues=result.predicted_cues,
        )
    
    # Check for gold being questionable
    for miss in [diag.cue4_miss, diag.cue6_miss]:
        if miss and miss.cause == "candidate_judgment":
            # If predicted score is much higher than gold, flag as questionable
            if miss.pred_drop_score > miss.gold_drop_score + 1.0:
                miss.cause = "gold_questionable"
                miss.cause_detail = f"Predicted ({miss.pred_beat}, score={miss.pred_drop_score:.1f}) has higher drop score than gold ({int(miss.gold_beat)}, score={miss.gold_drop_score:.1f})"
    
    return diag


def main():
    """Run diagnostics on all tracks."""
    
    gold_tracks = load_gold_csv(GOLD_CSV)
    
    # Load gold pool for fewshot
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    gold_pool = load_gold_pool(pool_csv, audio_sel)
    print(f"Loaded gold pool: {len(gold_pool.tracks)} tracks")
    
    features_cache: dict[str, TrackFeatures] = {}
    diagnostics: list[TrackDiagnostic] = []
    
    for audio_file in sorted(AUDIO_DIR.glob("*.mp3")):
        if audio_file.name not in gold_tracks:
            continue
        
        gold = gold_tracks[audio_file.name]
        
        # Get fewshot examples
        fewshot = get_pool_fewshot_examples(
            gold_pool,
            target_bpm=gold.bpm,
            target_beats=gold.total_beats,
            audio_dir=POOL_DIR,
            max_examples=5,
            features_cache=features_cache,
        )
        
        print(f"\n=== Diagnosing {audio_file.name} ===")
        print(f"BPM: {gold.bpm:.1f} ({gold.bpm_band})")
        
        diag = diagnose_track(audio_file, gold, fewshot, features_cache)
        diagnostics.append(diag)
        
        # Print quick summary
        if diag.abstained:
            print(f"ABSTAINED: {diag.abstain_reason}")
        else:
            c4_err = diag.errors.get(3, 0)
            c6_err = diag.errors.get(5, 0)
            c4_status = "✓" if c4_err <= 1 else f"✗ {c4_err:.0f}"
            c6_status = "✓" if c6_err <= 1 else f"✗ {c6_err:.0f}"
            print(f"Cue4: {c4_status}, Cue6: {c6_status}")
        
        if diag.cue4_miss:
            print(f"  Cue4 MISS: {diag.cue4_miss.cause} - {diag.cue4_miss.cause_detail}")
        if diag.cue6_miss:
            print(f"  Cue6 MISS: {diag.cue6_miss.cause} - {diag.cue6_miss.cause_detail}")
    
    # Save diagnostics as JSON
    output_json = Path("/workspace/drop_diagnostics.json")
    serializable = []
    for d in diagnostics:
        dd = {
            "track": d.track,
            "bpm": d.bpm,
            "bpm_band": d.bpm_band,
            "total_beats": d.total_beats,
            "first_beat_s": d.first_beat_s,
            "serato_first_beat_s": d.serato_first_beat_s,
            "grid_offset_ms": d.grid_offset_ms,
            "gold_cues": {str(k): v for k, v in d.gold_cues.items()},
            "pred_cues": {str(k): v for k, v in d.pred_cues.items()},
            "errors": {str(k): v for k, v in d.errors.items()},
            "drop_candidates": d.drop_candidates,
            "candidate_scores": {str(k): v for k, v in d.candidate_scores.items()},
            "abstained": d.abstained,
            "abstain_reason": d.abstain_reason,
        }
        if d.cue4_miss:
            dd["cue4_miss"] = asdict(d.cue4_miss)
        if d.cue6_miss:
            dd["cue6_miss"] = asdict(d.cue6_miss)
        serializable.append(dd)
    
    with open(output_json, "w") as f:
        json.dump(serializable, f, indent=2)
    print(f"\nDiagnostics saved to: {output_json}")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    total = len(diagnostics)
    abstained = sum(1 for d in diagnostics if d.abstained)
    
    cue4_correct = sum(1 for d in diagnostics if not d.abstained and d.errors.get(3, 999) <= 1)
    cue6_correct = sum(1 for d in diagnostics if not d.abstained and d.errors.get(5, 999) <= 1)
    
    print(f"Total tracks: {total}")
    print(f"Abstained: {abstained}")
    print(f"Cue4 correct: {cue4_correct}/{total} = {cue4_correct/total:.1%}")
    print(f"Cue6 correct: {cue6_correct}/{total} = {cue6_correct/total:.1%}")
    
    # Cause breakdown
    cue4_causes: dict[str, int] = {}
    cue6_causes: dict[str, int] = {}
    
    for d in diagnostics:
        if d.cue4_miss:
            cause = d.cue4_miss.cause
            cue4_causes[cause] = cue4_causes.get(cause, 0) + 1
        if d.cue6_miss:
            cause = d.cue6_miss.cause
            cue6_causes[cause] = cue6_causes.get(cause, 0) + 1
    
    print("\nCue4 miss causes:")
    for cause, count in sorted(cue4_causes.items(), key=lambda x: -x[1]):
        print(f"  {cause}: {count}")
    
    print("\nCue6 miss causes:")
    for cause, count in sorted(cue6_causes.items(), key=lambda x: -x[1]):
        print(f"  {cause}: {count}")
    
    # Candidate recall
    cue4_gold_in_cands = sum(1 for d in diagnostics if d.cue4_miss and d.cue4_miss.gold_in_candidates)
    cue4_misses = sum(1 for d in diagnostics if d.cue4_miss)
    cue6_gold_in_cands = sum(1 for d in diagnostics if d.cue6_miss and d.cue6_miss.gold_in_candidates)
    cue6_misses = sum(1 for d in diagnostics if d.cue6_miss)
    
    print(f"\nCandidate recall for misses:")
    print(f"  Cue4: gold in candidates {cue4_gold_in_cands}/{cue4_misses}")
    print(f"  Cue6: gold in candidates {cue6_gold_in_cands}/{cue6_misses}")
    
    return diagnostics


if __name__ == "__main__":
    diagnostics = main()
