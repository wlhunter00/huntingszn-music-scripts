#!/usr/bin/env python3
"""Analyze ±16 beat errors: find discriminators between drop start, run-up, and drop continuation.

For every ±16 miss:
- Dump features at gold beat vs predicted beat
- Identify discriminators: kick+bass slam after build/gap = drop; rising energy = run-up
- Check if gold cue3→cue4 is 16 vs 32 and whether model defaults to 32
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, asdict

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import extract_features, TrackFeatures, PhraseFeatures
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples
from auto_cue.llm import predict_cues_llm

import numpy as np

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"


@dataclass
class BeatAnalysis:
    """Feature analysis at a specific beat position."""
    beat: int
    # Kick/bass signals
    kick_density: float = 0.0
    delta_kick: float = 0.0  # Change from previous phrase
    low_energy: float = 0.0
    delta_low: float = 0.0
    # Build/gap signals
    build_score: float = 0.0  # Rising centroid/highband in preceding phrase
    gap_score: float = 0.0  # Quiet moment before
    snare_roll: float = 0.0  # Snare density in preceding 16 beats
    # Sustain signal (does energy stay high after?)
    post_sustain: float = 0.0
    # Novelty/contrast
    novelty: float = 0.0
    contrast: float = 0.0
    # Multi-zoom before/after (2/4/8/16 beat windows)
    zoom_2_before: float = 0.0
    zoom_2_after: float = 0.0
    zoom_4_before: float = 0.0
    zoom_4_after: float = 0.0
    zoom_8_before: float = 0.0
    zoom_8_after: float = 0.0
    zoom_16_before: float = 0.0
    zoom_16_after: float = 0.0
    # Vocal activity
    vocal_activity: float = 0.0
    # Is this a drop candidate?
    is_drop_candidate: bool = False
    drop_score: float = 0.0
    
    # Classification
    classification: str = ""  # "drop_start", "run_up", "drop_continuation", "other"


def analyze_beat(features: TrackFeatures, beat: int) -> BeatAnalysis:
    """Analyze features at a specific beat position."""
    analysis = BeatAnalysis(beat=beat)
    
    # Find the phrase containing this beat
    phrase_16 = None
    for p in features.phrases_16:
        if p.beat_start <= beat < p.beat_end:
            phrase_16 = p
            break
    
    if phrase_16 is None:
        # Find closest phrase
        closest = min(features.phrases_16, key=lambda p: abs(p.beat_start - beat))
        phrase_16 = closest
    
    # Basic phrase features
    analysis.kick_density = phrase_16.kick_density
    analysis.delta_kick = phrase_16.delta_kick
    analysis.low_energy = phrase_16.low_db
    analysis.delta_low = phrase_16.delta_low
    analysis.build_score = phrase_16.build_score
    analysis.gap_score = phrase_16.pre_drop_gap
    analysis.snare_roll = phrase_16.snare_roll
    analysis.post_sustain = phrase_16.post_sustain
    analysis.novelty = phrase_16.novelty_score
    analysis.contrast = phrase_16.contrast_score
    analysis.vocal_activity = phrase_16.vocal_activity
    analysis.is_drop_candidate = phrase_16.is_drop_candidate
    analysis.drop_score = phrase_16.drop_score
    
    # Multi-zoom analysis using beat features
    beat_features = features.beat_features
    if beat < len(beat_features):
        # Compute before/after energy at different scales
        for window, (before_attr, after_attr) in [
            (2, ("zoom_2_before", "zoom_2_after")),
            (4, ("zoom_4_before", "zoom_4_after")),
            (8, ("zoom_8_before", "zoom_8_after")),
            (16, ("zoom_16_before", "zoom_16_after")),
        ]:
            start = max(0, beat - window)
            end = min(len(beat_features), beat + window)
            
            before_beats = beat_features[start:beat]
            after_beats = beat_features[beat:end]
            
            if before_beats:
                before_low = np.mean([b.low_db for b in before_beats])
                setattr(analysis, before_attr, before_low)
            if after_beats:
                after_low = np.mean([b.low_db for b in after_beats])
                setattr(analysis, after_attr, after_low)
    
    # Classify the beat position
    analysis.classification = classify_beat(analysis)
    
    return analysis


def classify_beat(analysis: BeatAnalysis) -> str:
    """Classify a beat as drop_start, run_up, drop_continuation, or other.
    
    - drop_start: kick+bass slam after a build/gap (delta_kick > 0, delta_low > 0, gap > 0)
    - run_up: rising energy without full low end (build_score > 0, delta_kick < thresh)
    - drop_continuation: high energy but no fresh slam (low energy high but delta small)
    """
    # Drop start: strong kick/bass entry after a gap
    if analysis.delta_kick > 0.05 and analysis.delta_low > 5.0 and analysis.gap_score > 1.0:
        return "drop_start"
    if analysis.delta_kick > 0.1 and analysis.delta_low > 8.0:
        return "drop_start"
    
    # Run-up: build-up phase, rising energy but no full kick entry
    if analysis.build_score > 0.5 and analysis.delta_kick < 0.05:
        return "run_up"
    if analysis.snare_roll > 0.1 and analysis.delta_kick < 0.05:
        return "run_up"
    
    # Drop continuation: already in the drop, high energy but no fresh slam
    if analysis.low_energy > -25 and abs(analysis.delta_low) < 3.0 and abs(analysis.delta_kick) < 0.05:
        return "drop_continuation"
    
    return "other"


def compute_drop_start_score(analysis: BeatAnalysis) -> float:
    """Compute explicit 'is this a drop start' score (0-1)."""
    score = 0.0
    
    # Positive signals for drop start
    if analysis.delta_kick > 0:
        score += min(analysis.delta_kick * 5, 0.3)  # Kick slam-in
    if analysis.delta_low > 0:
        score += min(analysis.delta_low / 20, 0.25)  # Bass entry
    if analysis.gap_score > 0:
        score += min(analysis.gap_score / 5, 0.2)  # Pre-drop gap
    if analysis.post_sustain > -3:
        score += 0.15  # Energy stays high after
    if analysis.novelty > 0.5:
        score += 0.1  # Section change
    
    # Negative signals
    if analysis.classification == "run_up":
        score -= 0.3
    if analysis.classification == "drop_continuation":
        score -= 0.2
    
    return max(0, min(1, score))


@dataclass
class Error16Analysis:
    """Analysis of a ±16 beat error."""
    track: str
    cue: str  # "cue4" or "cue6"
    gold_beat: int
    pred_beat: int
    error: int  # +16 or -16
    
    gold_analysis: BeatAnalysis = None
    pred_analysis: BeatAnalysis = None
    
    gold_drop_score: float = 0.0
    pred_drop_score: float = 0.0
    
    # cue3 analysis
    gold_cue3_gap: int = 0  # 16 or 32
    model_default_32: bool = False
    
    discriminator_correct: bool = False  # Would drop_start_score pick gold?


def analyze_16_errors(
    audio_dir: Path,
    gold_csv: Path,
    pool_dir: Path,
) -> list[Error16Analysis]:
    """Run predictions and analyze all ±16 beat errors."""
    
    gold_tracks = load_gold_csv(gold_csv)
    pool_csv = pool_dir / "gold_pool_clean.csv"
    audio_sel = pool_dir / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    errors = []
    
    for filename, gold in gold_tracks.items():
        audio_path = audio_dir / filename
        if not audio_path.exists():
            continue
        
        print(f"\nProcessing {filename}...")
        
        try:
            features = extract_features(
                audio_path, gold.bpm, gold.first_beat_s, use_demucs=True
            )
            
            examples = get_pool_fewshot_examples(
                pool, gold.bpm, features.total_beats, pool_dir, max_examples=5
            )
            
            prediction = predict_cues_llm(
                features,
                model=MODEL,
                reasoning_effort=REASONING,
                genre_bucket=features.bpm_band,
                examples=examples,
            )
            
            # Check cue4
            gold_cue4 = gold.cues.get(3)  # 0-indexed
            pred_cue4 = prediction.cue4_beat
            
            if gold_cue4 is not None and pred_cue4 is not None:
                error = pred_cue4 - int(gold_cue4)
                if abs(error) in [16, -16, 15, 17, -15, -17]:  # ±16 with tolerance
                    error_16 = 16 if error > 0 else -16
                    
                    gold_analysis = analyze_beat(features, int(gold_cue4))
                    pred_analysis = analyze_beat(features, pred_cue4)
                    
                    # Check cue3→cue4 gap
                    gold_cue3 = gold.cues.get(2)  # 0-indexed
                    gold_cue3_gap = int(gold_cue4 - gold_cue3) if gold_cue3 else 0
                    
                    # Check if model's cue3→cue4 would be 32
                    model_cue3 = prediction.cue4_beat - 32 if prediction.cue4_beat >= 32 else prediction.cue4_beat - 16
                    model_default_32 = (prediction.cue4_beat - model_cue3) == 32
                    
                    gold_drop_score = compute_drop_start_score(gold_analysis)
                    pred_drop_score = compute_drop_start_score(pred_analysis)
                    
                    err = Error16Analysis(
                        track=filename,
                        cue="cue4",
                        gold_beat=int(gold_cue4),
                        pred_beat=pred_cue4,
                        error=error_16,
                        gold_analysis=gold_analysis,
                        pred_analysis=pred_analysis,
                        gold_drop_score=gold_drop_score,
                        pred_drop_score=pred_drop_score,
                        gold_cue3_gap=gold_cue3_gap,
                        model_default_32=model_default_32,
                        discriminator_correct=gold_drop_score > pred_drop_score,
                    )
                    errors.append(err)
                    
                    print(f"  CUE4 ±16 ERROR: gold={int(gold_cue4)}, pred={pred_cue4}, err={error_16}")
                    print(f"    Gold: {gold_analysis.classification}, drop_score={gold_drop_score:.2f}")
                    print(f"    Pred: {pred_analysis.classification}, drop_score={pred_drop_score:.2f}")
                    print(f"    Discriminator would pick: {'gold' if gold_drop_score > pred_drop_score else 'pred'}")
            
            # Check cue6
            gold_cue6 = gold.cues.get(5)  # 0-indexed
            pred_cue6 = prediction.cue6_beat
            
            if gold_cue6 is not None and pred_cue6 is not None:
                error = pred_cue6 - int(gold_cue6)
                if abs(error) in [16, -16, 15, 17, -15, -17]:
                    error_16 = 16 if error > 0 else -16
                    
                    gold_analysis = analyze_beat(features, int(gold_cue6))
                    pred_analysis = analyze_beat(features, pred_cue6)
                    
                    gold_drop_score = compute_drop_start_score(gold_analysis)
                    pred_drop_score = compute_drop_start_score(pred_analysis)
                    
                    err = Error16Analysis(
                        track=filename,
                        cue="cue6",
                        gold_beat=int(gold_cue6),
                        pred_beat=pred_cue6,
                        error=error_16,
                        gold_analysis=gold_analysis,
                        pred_analysis=pred_analysis,
                        gold_drop_score=gold_drop_score,
                        pred_drop_score=pred_drop_score,
                        discriminator_correct=gold_drop_score > pred_drop_score,
                    )
                    errors.append(err)
                    
                    print(f"  CUE6 ±16 ERROR: gold={int(gold_cue6)}, pred={pred_cue6}, err={error_16}")
                    print(f"    Gold: {gold_analysis.classification}, drop_score={gold_drop_score:.2f}")
                    print(f"    Pred: {pred_analysis.classification}, drop_score={pred_drop_score:.2f}")
                    print(f"    Discriminator would pick: {'gold' if gold_drop_score > pred_drop_score else 'pred'}")
                    
        except Exception as e:
            print(f"  ERROR: {e}")
    
    return errors


def main():
    print("=" * 60)
    print("±16 ERROR ANALYSIS")
    print("=" * 60)
    
    errors = analyze_16_errors(AUDIO_DIR, GOLD_CSV, POOL_DIR)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    cue4_errors = [e for e in errors if e.cue == "cue4"]
    cue6_errors = [e for e in errors if e.cue == "cue6"]
    
    print(f"\nTotal ±16 errors: {len(errors)}")
    print(f"  Cue4: {len(cue4_errors)}")
    print(f"  Cue6: {len(cue6_errors)}")
    
    # Check discriminator effectiveness
    disc_correct = sum(1 for e in errors if e.discriminator_correct)
    print(f"\nDiscriminator would pick gold: {disc_correct}/{len(errors)} ({disc_correct/len(errors)*100:.1f}%)")
    
    disc_correct_4 = sum(1 for e in cue4_errors if e.discriminator_correct)
    disc_correct_6 = sum(1 for e in cue6_errors if e.discriminator_correct)
    print(f"  Cue4: {disc_correct_4}/{len(cue4_errors)} ({disc_correct_4/len(cue4_errors)*100:.1f}%)" if cue4_errors else "  Cue4: 0")
    print(f"  Cue6: {disc_correct_6}/{len(cue6_errors)} ({disc_correct_6/len(cue6_errors)*100:.1f}%)" if cue6_errors else "  Cue6: 0")
    
    # Check cue3→cue4 gap patterns
    gap_16 = sum(1 for e in cue4_errors if e.gold_cue3_gap == 16)
    gap_32 = sum(1 for e in cue4_errors if e.gold_cue3_gap == 32)
    model_32 = sum(1 for e in cue4_errors if e.model_default_32)
    print(f"\nCue3→Cue4 gap in gold (for ±16 errors):")
    print(f"  16 beats: {gap_16}")
    print(f"  32 beats: {gap_32}")
    print(f"  Model defaults to 32: {model_32}/{len(cue4_errors)}")
    
    # Analyze error direction
    errors_plus16 = sum(1 for e in errors if e.error == 16)
    errors_minus16 = sum(1 for e in errors if e.error == -16)
    print(f"\nError direction:")
    print(f"  +16 (pred after gold): {errors_plus16}")
    print(f"  -16 (pred before gold): {errors_minus16}")
    
    # Feature comparison
    print("\n" + "=" * 60)
    print("FEATURE COMPARISON (Gold vs Pred)")
    print("=" * 60)
    
    print("\n| Metric | Gold Avg | Pred Avg | Diff |")
    print("|--------|----------|----------|------|")
    
    metrics = [
        ("delta_kick", "Δ Kick"),
        ("delta_low", "Δ Low"),
        ("gap_score", "Gap"),
        ("build_score", "Build"),
        ("post_sustain", "Sustain"),
        ("novelty", "Novelty"),
        ("drop_score", "Drop Score"),
    ]
    
    for attr, name in metrics:
        gold_vals = [getattr(e.gold_analysis, attr) for e in errors if e.gold_analysis]
        pred_vals = [getattr(e.pred_analysis, attr) for e in errors if e.pred_analysis]
        
        gold_avg = np.mean(gold_vals) if gold_vals else 0
        pred_avg = np.mean(pred_vals) if pred_vals else 0
        diff = gold_avg - pred_avg
        
        print(f"| {name:10s} | {gold_avg:8.2f} | {pred_avg:8.2f} | {diff:+.2f} |")
    
    # Classification breakdown
    print("\n" + "=" * 60)
    print("CLASSIFICATION BREAKDOWN")
    print("=" * 60)
    
    gold_classes = {}
    pred_classes = {}
    
    for e in errors:
        gc = e.gold_analysis.classification if e.gold_analysis else "unknown"
        pc = e.pred_analysis.classification if e.pred_analysis else "unknown"
        gold_classes[gc] = gold_classes.get(gc, 0) + 1
        pred_classes[pc] = pred_classes.get(pc, 0) + 1
    
    print("\nGold beat classification:")
    for c, count in sorted(gold_classes.items()):
        print(f"  {c}: {count}")
    
    print("\nPredicted beat classification:")
    for c, count in sorted(pred_classes.items()):
        print(f"  {c}: {count}")
    
    # Save detailed results
    output = {
        "total_errors": len(errors),
        "cue4_errors": len(cue4_errors),
        "cue6_errors": len(cue6_errors),
        "discriminator_correct": disc_correct,
        "errors": [
            {
                "track": e.track,
                "cue": e.cue,
                "gold_beat": e.gold_beat,
                "pred_beat": e.pred_beat,
                "error": e.error,
                "gold_classification": e.gold_analysis.classification if e.gold_analysis else None,
                "pred_classification": e.pred_analysis.classification if e.pred_analysis else None,
                "gold_drop_score": e.gold_drop_score,
                "pred_drop_score": e.pred_drop_score,
                "discriminator_correct": e.discriminator_correct,
                "gold_cue3_gap": e.gold_cue3_gap,
            }
            for e in errors
        ]
    }
    
    output_path = Path("/workspace/16_error_analysis.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved detailed results to: {output_path}")


if __name__ == "__main__":
    main()
