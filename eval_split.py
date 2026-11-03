#!/usr/bin/env python3
"""Evaluate on gold-pool train/held-out split + 42-track eval.

Compares baseline vs current configuration.
"""

import json
import os
import random
import sys
from pathlib import Path
from dataclasses import dataclass

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import extract_features
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples
from auto_cue.llm import predict_cues_llm

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"

# Split: 70% train, 30% held-out
TRAIN_RATIO = 0.7
RANDOM_SEED = 42


@dataclass
class EvalResult:
    cue4_correct: int = 0
    cue4_total: int = 0
    cue4_16_errors: int = 0
    cue6_correct: int = 0
    cue6_total: int = 0
    cue6_16_errors: int = 0
    cost_usd: float = 0.0
    bpm_stats: dict = None
    
    def __post_init__(self):
        if self.bpm_stats is None:
            self.bpm_stats = {}
    
    @property
    def cue4_acc(self):
        return self.cue4_correct / self.cue4_total * 100 if self.cue4_total > 0 else 0
    
    @property
    def cue6_acc(self):
        return self.cue6_correct / self.cue6_total * 100 if self.cue6_total > 0 else 0


def evaluate_track(filename, gold, audio_path, pool, pool_dir, result: EvalResult):
    """Evaluate a single track and update result."""
    features = extract_features(
        audio_path, gold.bpm, gold.first_beat_s, use_demucs=False  # Skip demucs for speed
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
    result.cost_usd += prediction.cost_usd
    
    band = gold.bpm_band
    if band not in result.bpm_stats:
        result.bpm_stats[band] = {"cue4_correct": 0, "cue4_total": 0, "cue6_correct": 0, "cue6_total": 0}
    
    # Cue4
    gold_cue4 = gold.cues.get(3)
    pred_cue4 = prediction.cue4_beat
    if gold_cue4 is not None:
        result.cue4_total += 1
        result.bpm_stats[band]["cue4_total"] += 1
        error = abs(pred_cue4 - gold_cue4) if pred_cue4 else float('inf')
        if error <= 1.0:
            result.cue4_correct += 1
            result.bpm_stats[band]["cue4_correct"] += 1
        elif 14 <= error <= 18:
            result.cue4_16_errors += 1
    
    # Cue6
    gold_cue6 = gold.cues.get(5)
    pred_cue6 = prediction.cue6_beat
    if gold_cue6 is not None:
        result.cue6_total += 1
        result.bpm_stats[band]["cue6_total"] += 1
        error = abs(pred_cue6 - gold_cue6) if pred_cue6 else float('inf')
        if error <= 1.0:
            result.cue6_correct += 1
            result.bpm_stats[band]["cue6_correct"] += 1
        elif 14 <= error <= 18:
            result.cue6_16_errors += 1
    
    return prediction


def print_result(name: str, result: EvalResult):
    """Print evaluation result summary."""
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    print(f"Cue4: {result.cue4_correct}/{result.cue4_total} = {result.cue4_acc:.1f}%  (±16 err: {result.cue4_16_errors})")
    print(f"Cue6: {result.cue6_correct}/{result.cue6_total} = {result.cue6_acc:.1f}%  (±16 err: {result.cue6_16_errors})")
    print(f"Cost: ${result.cost_usd:.2f}")
    
    if result.bpm_stats:
        print(f"\nBy BPM band:")
        for band in ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)"]:
            if band in result.bpm_stats:
                stats = result.bpm_stats[band]
                c4 = stats["cue4_correct"] / stats["cue4_total"] * 100 if stats["cue4_total"] > 0 else 0
                c6 = stats["cue6_correct"] / stats["cue6_total"] * 100 if stats["cue6_total"] > 0 else 0
                print(f"  {band}: cue4={c4:.0f}% ({stats['cue4_correct']}/{stats['cue4_total']}), cue6={c6:.0f}% ({stats['cue6_correct']}/{stats['cue6_total']})")


def main():
    print("=" * 60)
    print("GOLD-POOL SPLIT EVALUATION")
    print("=" * 60)
    
    # Load 42-track eval set (to exclude from pool)
    eval_tracks = load_gold_csv(GOLD_CSV)
    eval_filenames = set(eval_tracks.keys())
    
    # Load gold pool
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    # Get pool tracks with audio (excluding eval set)
    pool_tracks = []
    for name, track in pool.tracks.items():
        if name not in eval_filenames and track.has_audio:
            small_file = pool.audio_map.get(name)
            if small_file:
                audio_path = POOL_DIR / small_file
                if audio_path.exists():
                    pool_tracks.append((name, track, audio_path))
    
    print(f"42-track eval set: {len(eval_filenames)} tracks")
    print(f"Gold pool with audio (excluding eval): {len(pool_tracks)} tracks")
    
    # Split pool into train/held-out
    random.seed(RANDOM_SEED)
    random.shuffle(pool_tracks)
    split_idx = int(len(pool_tracks) * TRAIN_RATIO)
    train_tracks = pool_tracks[:split_idx]
    holdout_tracks = pool_tracks[split_idx:]
    
    print(f"Train split: {len(train_tracks)} tracks")
    print(f"Held-out split: {len(holdout_tracks)} tracks")
    
    # Run evaluation on held-out gold pool
    print(f"\n{'='*60}")
    print("EVALUATING HELD-OUT GOLD POOL...")
    print("=" * 60)
    
    holdout_result = EvalResult()
    for i, (name, track, audio_path) in enumerate(holdout_tracks[:30]):  # Limit for speed
        print(f"\n[{i+1}/30] {Path(name).name[:40]}... BPM={track.bpm:.0f}")
        try:
            evaluate_track(name, track, audio_path, pool, POOL_DIR, holdout_result)
            print(f"  Running: cue4={holdout_result.cue4_acc:.0f}%, cue6={holdout_result.cue6_acc:.0f}%")
        except Exception as e:
            print(f"  ERROR: {e}")
    
    print_result("HELD-OUT GOLD POOL (30 tracks)", holdout_result)
    
    # Run evaluation on 42-track eval set
    print(f"\n{'='*60}")
    print("EVALUATING 42-TRACK EVAL SET...")
    print("=" * 60)
    
    eval_result = EvalResult()
    for i, (filename, gold) in enumerate(eval_tracks.items()):
        audio_path = AUDIO_DIR / filename
        if not audio_path.exists():
            continue
        print(f"\n[{i+1}/{len(eval_tracks)}] {filename} BPM={gold.bpm:.0f}")
        try:
            evaluate_track(filename, gold, audio_path, pool, POOL_DIR, eval_result)
            print(f"  Running: cue4={eval_result.cue4_acc:.0f}%, cue6={eval_result.cue6_acc:.0f}%")
        except Exception as e:
            print(f"  ERROR: {e}")
    
    print_result("42-TRACK EVAL SET", eval_result)
    
    # Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\n| Dataset | Cue4 | Cue6 | ±16 (c4/c6) |")
    print(f"|---------|------|------|-------------|")
    print(f"| Held-out | {holdout_result.cue4_acc:.1f}% | {holdout_result.cue6_acc:.1f}% | {holdout_result.cue4_16_errors}/{holdout_result.cue6_16_errors} |")
    print(f"| 42-eval  | {eval_result.cue4_acc:.1f}% | {eval_result.cue6_acc:.1f}% | {eval_result.cue4_16_errors}/{eval_result.cue6_16_errors} |")
    
    # Save results
    results = {
        "holdout": {
            "cue4_acc": holdout_result.cue4_acc,
            "cue6_acc": holdout_result.cue6_acc,
            "cue4_16_errors": holdout_result.cue4_16_errors,
            "cue6_16_errors": holdout_result.cue6_16_errors,
            "bpm_stats": holdout_result.bpm_stats,
        },
        "eval": {
            "cue4_acc": eval_result.cue4_acc,
            "cue6_acc": eval_result.cue6_acc,
            "cue4_16_errors": eval_result.cue4_16_errors,
            "cue6_16_errors": eval_result.cue6_16_errors,
            "bpm_stats": eval_result.bpm_stats,
        },
        "total_cost": holdout_result.cost_usd + eval_result.cost_usd,
    }
    
    with open("/workspace/split_eval_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to /workspace/split_eval_results.json")


if __name__ == "__main__":
    main()
