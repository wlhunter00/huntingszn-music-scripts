#!/usr/bin/env python3
"""Run evaluation with calibrated confidence including self-consistency.

Uses 3 model samples per track to compute self-consistency confidence.
Combines with code-based confidence signals for final calibrated score.
"""

import json
import os
import sys
from pathlib import Path

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import extract_features, TrackFeatures
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples
from auto_cue.llm import predict_cues_llm, prediction_to_cue_set
from auto_cue.calibrated_confidence import (
    compute_cue_confidence_signals,
    compute_self_consistency_confidence,
)
from auto_cue.validate import validate_and_repair

import numpy as np

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"
N_SAMPLES = 3  # Number of model samples for self-consistency


def run_with_self_consistency(
    features: TrackFeatures,
    pool_dir: Path,
    n_samples: int = 3,
) -> dict:
    """Run prediction with self-consistency across multiple samples.
    
    Returns:
        Dict with predictions, confidences, and consensus
    """
    pool_csv = pool_dir / "gold_pool_clean.csv"
    audio_sel = pool_dir / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    examples = get_pool_fewshot_examples(
        pool,
        features.bpm,
        features.total_beats,
        pool_dir,
        max_examples=5,
    )
    
    predictions = []
    total_cost = 0.0
    
    for i in range(n_samples):
        pred = predict_cues_llm(
            features,
            model=MODEL,
            reasoning_effort=REASONING,
            genre_bucket=features.bpm_band,
            examples=examples,
        )
        total_cost += pred.cost_usd
        predictions.append((pred.cue4_beat, pred.cue6_beat))
    
    # Compute self-consistency
    sc_cue4, sc_cue6, consensus_cue4, consensus_cue6 = compute_self_consistency_confidence(
        predictions, tolerance_beats=16
    )
    
    # Compute code-based confidence for consensus
    code_cue4 = compute_cue_confidence_signals(features, consensus_cue4, cue_slot=4)
    code_cue6 = compute_cue_confidence_signals(features, consensus_cue6, cue_slot=6)
    
    # Combined confidence: self-consistency * code confidence
    # Both must be high for high overall confidence
    cue4_combined = sc_cue4 * code_cue4.calibrated_confidence
    cue6_combined = sc_cue6 * code_cue6.calibrated_confidence
    
    return {
        "consensus_cue4": consensus_cue4,
        "consensus_cue6": consensus_cue6,
        "self_consistency_cue4": sc_cue4,
        "self_consistency_cue6": sc_cue6,
        "code_confidence_cue4": code_cue4.calibrated_confidence,
        "code_confidence_cue6": code_cue6.calibrated_confidence,
        "combined_confidence_cue4": cue4_combined,
        "combined_confidence_cue6": cue6_combined,
        "individual_predictions": predictions,
        "cost_usd": total_cost,
    }


def main():
    print("=" * 60)
    print("CALIBRATED EVALUATION WITH SELF-CONSISTENCY")
    print("=" * 60)
    print(f"Model: {MODEL} x {N_SAMPLES} samples")
    print(f"Audio: {AUDIO_DIR}")
    print("")
    
    gold_tracks = load_gold_csv(GOLD_CSV)
    print(f"Gold tracks: {len(gold_tracks)}")
    
    results = []
    total_cost = 0.0
    
    for i, (filename, gold) in enumerate(gold_tracks.items()):
        audio_path = AUDIO_DIR / filename
        if not audio_path.exists():
            print(f"[{i+1}] {filename}: audio not found")
            continue
        
        print(f"\n[{i+1}/{len(gold_tracks)}] {filename}")
        print(f"  BPM: {gold.bpm:.1f} ({gold.bpm_band})")
        
        try:
            features = extract_features(
                audio_path, gold.bpm, gold.first_beat_s, use_demucs=True
            )
            
            result = run_with_self_consistency(features, POOL_DIR, N_SAMPLES)
            total_cost += result["cost_usd"]
            
            gold_cue4 = gold.cues.get(3)  # 0-indexed
            gold_cue6 = gold.cues.get(5)
            
            pred_cue4 = result["consensus_cue4"]
            pred_cue6 = result["consensus_cue6"]
            
            cue4_err = abs(pred_cue4 - gold_cue4) if pred_cue4 and gold_cue4 else None
            cue6_err = abs(pred_cue6 - gold_cue6) if pred_cue6 and gold_cue6 else None
            
            cue4_correct = cue4_err is not None and cue4_err <= 1.0
            cue6_correct = cue6_err is not None and cue6_err <= 1.0
            
            result.update({
                "filename": filename,
                "gold_cue4": gold_cue4,
                "gold_cue6": gold_cue6,
                "cue4_error": cue4_err,
                "cue6_error": cue6_err,
                "cue4_correct": cue4_correct,
                "cue6_correct": cue6_correct,
            })
            results.append(result)
            
            print(f"  Cue4: pred={pred_cue4}, gold={gold_cue4}, err={cue4_err}")
            print(f"    SC={result['self_consistency_cue4']:.2f}, Code={result['code_confidence_cue4']:.2f}, Combined={result['combined_confidence_cue4']:.2f}")
            print(f"  Cue6: pred={pred_cue6}, gold={gold_cue6}, err={cue6_err}")
            print(f"    SC={result['self_consistency_cue6']:.2f}, Code={result['code_confidence_cue6']:.2f}, Combined={result['combined_confidence_cue6']:.2f}")
            
        except Exception as e:
            print(f"  ERROR: {e}")
    
    print(f"\n\nTotal API cost: ${total_cost:.2f}")
    
    # Compute precision/coverage curves
    print("\n" + "=" * 60)
    print("PRECISION/COVERAGE CURVES (Combined Confidence)")
    print("=" * 60)
    
    def compute_curve(results: list[dict], cue_key: str) -> list[tuple[float, float, float]]:
        conf_key = f"combined_confidence_{cue_key}"
        correct_key = f"{cue_key}_correct"
        
        data = [(r[conf_key], r[correct_key]) for r in results if r.get(f"gold_{cue_key}") is not None]
        if not data:
            return []
        
        thresholds = np.arange(0.0, 1.01, 0.05)
        curve = []
        total = len(data)
        
        for thresh in thresholds:
            emitted = [(conf, correct) for conf, correct in data if conf >= thresh]
            n_emitted = len(emitted)
            
            if n_emitted == 0:
                precision = 1.0
                coverage = 0.0
            else:
                n_correct = sum(1 for _, correct in emitted if correct)
                precision = n_correct / n_emitted
                coverage = n_emitted / total
            
            curve.append((float(thresh), precision, coverage))
        
        return curve
    
    cue4_curve = compute_curve(results, "cue4")
    cue6_curve = compute_curve(results, "cue6")
    
    print("\nCUE4 PRECISION/COVERAGE:")
    print(f"{'Threshold':>10} | {'Precision':>10} | {'Coverage':>10}")
    print("-" * 40)
    for thresh, prec, cov in cue4_curve:
        marker = ""
        if prec >= 0.90 and (not cue4_curve or prec < 0.95):
            marker = " <- 90%"
        elif prec >= 0.80 and prec < 0.90:
            marker = " <- 80%"
        print(f"{thresh:>10.2f} | {prec:>10.1%} | {cov:>10.1%}{marker}")
    
    print("\nCUE6 PRECISION/COVERAGE:")
    print(f"{'Threshold':>10} | {'Precision':>10} | {'Coverage':>10}")
    print("-" * 40)
    for thresh, prec, cov in cue6_curve:
        marker = ""
        if prec >= 0.90 and prec < 0.95:
            marker = " <- 90%"
        elif prec >= 0.80 and prec < 0.90:
            marker = " <- 80%"
        print(f"{thresh:>10.2f} | {prec:>10.1%} | {cov:>10.1%}{marker}")
    
    # Find recommended thresholds
    def find_threshold(curve: list[tuple[float, float, float]], target: float) -> float:
        for thresh, prec, cov in curve:
            if prec >= target:
                return thresh
        return 1.0
    
    print("\n" + "=" * 60)
    print("RECOMMENDED THRESHOLDS")
    print("=" * 60)
    
    cue4_80 = find_threshold(cue4_curve, 0.80)
    cue4_90 = find_threshold(cue4_curve, 0.90)
    cue4_95 = find_threshold(cue4_curve, 0.95)
    cue6_80 = find_threshold(cue6_curve, 0.80)
    cue6_90 = find_threshold(cue6_curve, 0.90)
    cue6_95 = find_threshold(cue6_curve, 0.95)
    
    print(f"CUE4: 80%@{cue4_80:.2f}, 90%@{cue4_90:.2f}, 95%@{cue4_95:.2f}")
    print(f"CUE6: 80%@{cue6_80:.2f}, 90%@{cue6_90:.2f}, 95%@{cue6_95:.2f}")
    
    # Report per-cue metrics at 90% precision threshold (or best available)
    print("\n" + "=" * 60)
    print("PER-CUE METRICS AT 90% PRECISION OPERATING POINT")
    print("=" * 60)
    
    cue4_thresh = cue4_90 if cue4_90 < 1.0 else cue4_80
    cue6_thresh = cue6_90 if cue6_90 < 1.0 else cue6_80
    
    n_total_cue4 = sum(1 for r in results if r.get("gold_cue4") is not None)
    n_total_cue6 = sum(1 for r in results if r.get("gold_cue6") is not None)
    
    n_emitted_cue4 = sum(1 for r in results if r.get("gold_cue4") is not None and r["combined_confidence_cue4"] >= cue4_thresh)
    n_correct_cue4 = sum(1 for r in results if r.get("gold_cue4") is not None and r["combined_confidence_cue4"] >= cue4_thresh and r["cue4_correct"])
    
    n_emitted_cue6 = sum(1 for r in results if r.get("gold_cue6") is not None and r["combined_confidence_cue6"] >= cue6_thresh)
    n_correct_cue6 = sum(1 for r in results if r.get("gold_cue6") is not None and r["combined_confidence_cue6"] >= cue6_thresh and r["cue6_correct"])
    
    prec_cue4 = n_correct_cue4 / n_emitted_cue4 if n_emitted_cue4 > 0 else 0
    cov_cue4 = n_emitted_cue4 / n_total_cue4 if n_total_cue4 > 0 else 0
    acc_cue4 = n_correct_cue4 / n_total_cue4 if n_total_cue4 > 0 else 0
    
    prec_cue6 = n_correct_cue6 / n_emitted_cue6 if n_emitted_cue6 > 0 else 0
    cov_cue6 = n_emitted_cue6 / n_total_cue6 if n_total_cue6 > 0 else 0
    acc_cue6 = n_correct_cue6 / n_total_cue6 if n_total_cue6 > 0 else 0
    
    print(f"Cue4 @ thresh={cue4_thresh:.2f}:")
    print(f"  Precision: {prec_cue4:.1%} ({n_correct_cue4}/{n_emitted_cue4})")
    print(f"  Coverage:  {cov_cue4:.1%} ({n_emitted_cue4}/{n_total_cue4})")
    print(f"  Accuracy:  {acc_cue4:.1%} ({n_correct_cue4}/{n_total_cue4})")
    
    print(f"\nCue6 @ thresh={cue6_thresh:.2f}:")
    print(f"  Precision: {prec_cue6:.1%} ({n_correct_cue6}/{n_emitted_cue6})")
    print(f"  Coverage:  {cov_cue6:.1%} ({n_emitted_cue6}/{n_total_cue6})")
    print(f"  Accuracy:  {acc_cue6:.1%} ({n_correct_cue6}/{n_total_cue6})")
    
    # Save results
    output = {
        "model": MODEL,
        "n_samples": N_SAMPLES,
        "total_tracks": len(results),
        "total_cost": total_cost,
        "cue4_threshold_90": cue4_90,
        "cue6_threshold_90": cue6_90,
        "cue4_curve": [{"threshold": t, "precision": p, "coverage": c} for t, p, c in cue4_curve],
        "cue6_curve": [{"threshold": t, "precision": p, "coverage": c} for t, p, c in cue6_curve],
        "results": results,
    }
    
    output_path = Path("/workspace/calibrated_eval_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
