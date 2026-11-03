#!/usr/bin/env python3
"""Run simple accuracy evaluation for cue4/cue6.

Reports:
- Overall accuracy for cue4/cue6
- By BPM band breakdown
- ±16/±32 error analysis
"""

import json
import os
import sys
from pathlib import Path

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


def main():
    print("=" * 60)
    print("ACCURACY EVALUATION")
    print("=" * 60)
    print(f"Model: {MODEL}")
    print("")
    
    gold_tracks = load_gold_csv(GOLD_CSV)
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    print(f"Gold tracks: {len(gold_tracks)}")
    
    results = []
    total_cost = 0.0
    
    # Track accuracy
    cue4_correct = 0
    cue4_total = 0
    cue4_16_errors = 0
    cue4_32_errors = 0
    
    cue6_correct = 0
    cue6_total = 0
    cue6_16_errors = 0
    cue6_32_errors = 0
    
    # By BPM band
    bpm_stats = {}
    
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
            
            examples = get_pool_fewshot_examples(
                pool, gold.bpm, features.total_beats, POOL_DIR, max_examples=5
            )
            
            prediction = predict_cues_llm(
                features,
                model=MODEL,
                reasoning_effort=REASONING,
                genre_bucket=features.bpm_band,
                examples=examples,
            )
            total_cost += prediction.cost_usd
            
            # Cue4 analysis
            gold_cue4 = gold.cues.get(3)  # 0-indexed
            pred_cue4 = prediction.cue4_beat
            
            if gold_cue4 is not None:
                cue4_total += 1
                error = abs(pred_cue4 - gold_cue4) if pred_cue4 else float('inf')
                
                if error <= 1.0:
                    cue4_correct += 1
                    print(f"  Cue4: ✓ pred={pred_cue4}, gold={int(gold_cue4)}")
                else:
                    print(f"  Cue4: ✗ pred={pred_cue4}, gold={int(gold_cue4)}, err={error:.0f}")
                    if 14 <= error <= 18:
                        cue4_16_errors += 1
                    elif 30 <= error <= 34:
                        cue4_32_errors += 1
                
                # BPM band tracking
                band = gold.bpm_band
                if band not in bpm_stats:
                    bpm_stats[band] = {"cue4_correct": 0, "cue4_total": 0, "cue6_correct": 0, "cue6_total": 0}
                bpm_stats[band]["cue4_total"] += 1
                if error <= 1.0:
                    bpm_stats[band]["cue4_correct"] += 1
            
            # Cue6 analysis
            gold_cue6 = gold.cues.get(5)  # 0-indexed
            pred_cue6 = prediction.cue6_beat
            
            if gold_cue6 is not None:
                cue6_total += 1
                error = abs(pred_cue6 - gold_cue6) if pred_cue6 else float('inf')
                
                if error <= 1.0:
                    cue6_correct += 1
                    print(f"  Cue6: ✓ pred={pred_cue6}, gold={int(gold_cue6)}")
                else:
                    print(f"  Cue6: ✗ pred={pred_cue6}, gold={int(gold_cue6)}, err={error:.0f}")
                    if 14 <= error <= 18:
                        cue6_16_errors += 1
                    elif 30 <= error <= 34:
                        cue6_32_errors += 1
                
                band = gold.bpm_band
                bpm_stats[band]["cue6_total"] += 1
                if error <= 1.0:
                    bpm_stats[band]["cue6_correct"] += 1
            
            results.append({
                "filename": filename,
                "bpm": gold.bpm,
                "bpm_band": gold.bpm_band,
                "gold_cue4": gold_cue4,
                "pred_cue4": pred_cue4,
                "gold_cue6": gold_cue6,
                "pred_cue6": pred_cue6,
            })
            
        except Exception as e:
            print(f"  ERROR: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    cue4_acc = cue4_correct / cue4_total * 100 if cue4_total > 0 else 0
    cue6_acc = cue6_correct / cue6_total * 100 if cue6_total > 0 else 0
    
    print(f"\nCue4 Accuracy: {cue4_correct}/{cue4_total} = {cue4_acc:.1f}%")
    print(f"  ±16 errors: {cue4_16_errors}")
    print(f"  ±32 errors: {cue4_32_errors}")
    
    print(f"\nCue6 Accuracy: {cue6_correct}/{cue6_total} = {cue6_acc:.1f}%")
    print(f"  ±16 errors: {cue6_16_errors}")
    print(f"  ±32 errors: {cue6_32_errors}")
    
    print(f"\nTotal API Cost: ${total_cost:.2f}")
    
    # By BPM band
    print("\n" + "=" * 60)
    print("BY BPM BAND")
    print("=" * 60)
    print("\n| BPM Band | Cue4 | Cue6 |")
    print("|----------|------|------|")
    
    for band in ["bass (<80)", "dnb (80-100)", "midtempo (100-115)", "house (115+)"]:
        if band in bpm_stats:
            stats = bpm_stats[band]
            c4 = stats["cue4_correct"] / stats["cue4_total"] * 100 if stats["cue4_total"] > 0 else 0
            c6 = stats["cue6_correct"] / stats["cue6_total"] * 100 if stats["cue6_total"] > 0 else 0
            print(f"| {band:14s} | {c4:4.0f}% | {c6:4.0f}% |")
    
    # Save results
    output = {
        "cue4_accuracy": cue4_acc,
        "cue6_accuracy": cue6_acc,
        "cue4_16_errors": cue4_16_errors,
        "cue6_16_errors": cue6_16_errors,
        "bpm_stats": bpm_stats,
        "results": results,
    }
    
    output_path = Path("/workspace/accuracy_eval_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
