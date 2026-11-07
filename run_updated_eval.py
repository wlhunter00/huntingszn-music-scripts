#!/usr/bin/env python3
"""Run updated evaluation with per-cue precision/coverage/accuracy metrics."""

import json
import os
import sys
from pathlib import Path

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.eval import (
    run_eval,
    compute_summary,
    compute_candidate_recall,
    analyze_errors,
    results_by_bpm_band,
)
from auto_cue.features import TrackFeatures, extract_features
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"


def main():
    """Run updated evaluation."""
    
    print("="*60)
    print("UPDATED EVALUATION: Terra medium + fewshot + demucs")
    print("="*60)
    print(f"Model: {MODEL}")
    print(f"Reasoning: {REASONING}")
    print(f"Features: fewshot (v2 pool) + demucs")
    print("")
    
    # Load gold tracks
    gold_tracks = load_gold_csv(GOLD_CSV)
    print(f"Gold tracks: {len(gold_tracks)}")
    
    # Load gold pool for fewshot
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    gold_pool = load_gold_pool(pool_csv, audio_sel)
    print(f"Gold pool: {len(gold_pool.tracks)} tracks")
    
    # Run evaluation
    results, summary = run_eval(
        AUDIO_DIR,
        gold_csv=GOLD_CSV,
        use_llm=True,
        model=MODEL,
        reasoning_effort=REASONING,
        use_fewshot=True,
        use_demucs=True,
        pool_dir=POOL_DIR,
    )
    
    # Collect features for candidate recall analysis
    features_cache: dict[str, TrackFeatures] = {}
    for result in results:
        audio_path = AUDIO_DIR / result.track_name
        if audio_path.exists():
            gold = gold_tracks.get(result.track_name)
            if gold:
                try:
                    features = extract_features(
                        audio_path, gold.bpm, gold.first_beat_s, use_demucs=True
                    )
                    features_cache[result.track_name] = features
                except Exception as e:
                    print(f"Warning: Could not extract features for {result.track_name}: {e}")
    
    # Compute candidate recall
    recall_stats = compute_candidate_recall(results, features_cache)
    
    # Error analysis
    error_analysis = analyze_errors(results)
    
    # BPM band stats
    bpm_stats = results_by_bpm_band(results)
    
    # Print results
    print("\n" + "="*60)
    print("PER-CUE PRECISION / COVERAGE / ACCURACY")
    print("="*60)
    print("(Precision=correct/emitted, Coverage=emitted/gold, Accuracy=correct/gold)")
    print("")
    
    for slot in range(8):
        prec = summary.cue_precision(slot)
        cov = summary.cue_coverage(slot)
        acc = summary.cue_accuracy_all(slot)
        emitted = summary.per_cue_emitted.get(slot, 0)
        correct = summary.per_cue_correct.get(slot, 0)
        gold_total = summary.gold_cue_totals.get(slot, 0)
        
        if gold_total > 0:
            marker = "**" if slot in [3, 5] else ""  # Highlight cue4 and cue6
            print(
                f"  {marker}Cue {slot+1}{marker}: P={prec:.0%} ({correct}/{emitted}) | "
                f"C={cov:.0%} ({emitted}/{gold_total}) | "
                f"A={acc:.0%} ({correct}/{gold_total})"
            )
    
    print("\n" + "="*60)
    print("CANDIDATE RECALL (gold drop in candidate set)")
    print("="*60)
    for cue in ["cue4", "cue6"]:
        stats = recall_stats[cue]
        recall = stats["recall"]
        in_cands = stats["gold_in_candidates"]
        total = stats["total_with_gold"]
        print(f"  {cue.upper()}: {recall:.0%} ({in_cands}/{total})")
    
    print("\n" + "="*60)
    print("ERROR ANALYSIS (±16/±32)")
    print("="*60)
    print(f"Total errors (>1 beat): {error_analysis['total_errors']}")
    print(f"  ±16 beat errors: {error_analysis['errors_16']}")
    print(f"  ±32 beat errors: {error_analysis['errors_32']}")
    print(f"  Other errors: {error_analysis['errors_other']}")
    print(f"Cue4 ±16: {error_analysis['cue4_errors_16']}, ±32: {error_analysis['cue4_errors_32']}")
    print(f"Cue6 ±16: {error_analysis['cue6_errors_16']}, ±32: {error_analysis['cue6_errors_32']}")
    
    print("\n" + "="*60)
    print("RESULTS BY BPM BAND")
    print("="*60)
    print("| BPM Band | Tracks | Cue4 P | Cue4 A | Cue6 P | Cue6 A |")
    print("|----------|--------|--------|--------|--------|--------|")
    
    for band in ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)", "unknown"]:
        if band in bpm_stats:
            stats = bpm_stats[band]
            total = stats["total"]
            c4_hits = stats["cue4_hits"]
            c6_hits = stats["cue6_hits"]
            c4_pct = c4_hits / total * 100 if total > 0 else 0
            c6_pct = c6_hits / total * 100 if total > 0 else 0
            print(f"| {band:14s} | {total:6d} | {c4_pct:5.0f}% | {c4_pct:5.0f}% | {c6_pct:5.0f}% | {c6_pct:5.0f}% |")
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total tracks: {summary.total}")
    print(f"Processed: {summary.processed}")
    print(f"Abstained: {summary.abstained} ({summary.abstain_rate:.1%})")
    print(f"API Cost: ${summary.total_cost_usd:.4f} total")
    
    # Key metrics
    c4_prec = summary.cue_precision(3)
    c6_prec = summary.cue_precision(5)
    c4_acc = summary.cue_accuracy_all(3)
    c6_acc = summary.cue_accuracy_all(5)
    
    print("\n" + "="*60)
    print("KEY METRICS (TARGET: >=90% precision)")
    print("="*60)
    print(f"  Cue4: Precision={c4_prec:.1%}, Accuracy={c4_acc:.1%}")
    print(f"  Cue6: Precision={c6_prec:.1%}, Accuracy={c6_acc:.1%}")
    
    # Save results to JSON
    output = {
        "model": MODEL,
        "reasoning": REASONING,
        "total_tracks": summary.total,
        "processed": summary.processed,
        "abstained": summary.abstained,
        "per_cue_metrics": {},
        "candidate_recall": recall_stats,
        "error_analysis": error_analysis,
        "bpm_stats": bpm_stats,
    }
    
    for slot in range(8):
        output["per_cue_metrics"][f"cue{slot+1}"] = {
            "precision": summary.cue_precision(slot),
            "coverage": summary.cue_coverage(slot),
            "accuracy": summary.cue_accuracy_all(slot),
            "emitted": summary.per_cue_emitted.get(slot, 0),
            "correct": summary.per_cue_correct.get(slot, 0),
            "gold_total": summary.gold_cue_totals.get(slot, 0),
        }
    
    output_path = Path("/workspace/updated_eval_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {output_path}")
    
    return results, summary


if __name__ == "__main__":
    main()
