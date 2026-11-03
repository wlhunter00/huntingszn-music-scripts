#!/usr/bin/env python3
"""Fit calibrated confidence thresholds on gold pool (not eval set).

This script:
1. Runs predictions on gold pool tracks
2. Computes calibrated confidence signals
3. Fits thresholds for 80%/90%/95% precision targets
4. Reports precision/coverage curves
"""

import json
import os
import sys
from pathlib import Path

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import extract_features, TrackFeatures
from auto_cue.gold import load_gold_pool
from auto_cue.llm import predict_cues_llm, get_api_key
from auto_cue.calibrated_confidence import (
    compute_cue_confidence_signals,
    fit_thresholds_on_gold_pool,
    ThresholdFitResult,
)

POOL_DIR = Path("/workspace/gold-pool")
MODEL = "gpt-6.1-terra"
REASONING = "medium"
MAX_TRACKS = 50  # Limit for cost control (fits thresholds reasonably)


def main():
    print("=" * 60)
    print("FITTING CALIBRATED CONFIDENCE THRESHOLDS")
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Pool: {POOL_DIR}")
    print(f"Max tracks: {MAX_TRACKS}")
    print("")
    
    # Load gold pool
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    print(f"Loaded {len(pool.tracks)} gold pool tracks")
    
    # Filter to tracks with audio available
    tracks_with_audio = []
    for track in list(pool.tracks.values())[:MAX_TRACKS * 2]:  # Check more, take MAX
        if track.audio_path and Path(track.audio_path).exists():
            tracks_with_audio.append(track)
            if len(tracks_with_audio) >= MAX_TRACKS:
                break
    
    print(f"Tracks with audio: {len(tracks_with_audio)}")
    
    # Run predictions and collect data
    gold_data: list[tuple[TrackFeatures, dict[int, int]]] = []
    predictions: list[tuple[int | None, int | None]] = []
    
    total_cost = 0.0
    
    for i, track in enumerate(tracks_with_audio):
        print(f"\n[{i+1}/{len(tracks_with_audio)}] {track.name}")
        
        try:
            # Extract features
            audio_path = Path(track.audio_path)
            features = extract_features(
                audio_path, track.bpm, track.first_beat_s, use_demucs=True
            )
            
            # Get gold cues
            gold_cues = {slot: int(beat) for slot, beat in track.cues.items()}
            gold_data.append((features, gold_cues))
            
            # Run LLM prediction
            prediction = predict_cues_llm(
                features,
                model=MODEL,
                reasoning_effort=REASONING,
                genre_bucket=features.bpm_band,
            )
            total_cost += prediction.cost_usd
            
            # Store cue4/cue6 predictions
            cue4_pred = prediction.cue4_beat
            cue6_pred = prediction.cue6_beat
            predictions.append((cue4_pred, cue6_pred))
            
            # Quick check
            gold_cue4 = gold_cues.get(3)  # 0-indexed
            gold_cue6 = gold_cues.get(5)
            
            cue4_err = abs(cue4_pred - gold_cue4) if cue4_pred and gold_cue4 else None
            cue6_err = abs(cue6_pred - gold_cue6) if cue6_pred and gold_cue6 else None
            
            # Compute signals for display
            cue4_signals = compute_cue_confidence_signals(features, cue4_pred, cue_slot=4)
            cue6_signals = compute_cue_confidence_signals(features, cue6_pred, cue_slot=6)
            
            print(f"  Cue4: pred={cue4_pred}, gold={gold_cue4}, err={cue4_err}, conf={cue4_signals.calibrated_confidence:.2f}")
            print(f"  Cue6: pred={cue6_pred}, gold={gold_cue6}, err={cue6_err}, conf={cue6_signals.calibrated_confidence:.2f}")
            
        except Exception as e:
            print(f"  ERROR: {e}")
            predictions.append((None, None))
            gold_data.append((None, {}))
    
    print(f"\n\nTotal API cost: ${total_cost:.2f}")
    
    # Filter out failed tracks
    valid_data = [
        (g, p) for (g, p) in zip(gold_data, predictions) if g[0] is not None
    ]
    gold_data_valid = [g for g, _ in valid_data]
    predictions_valid = [p for _, p in valid_data]
    
    print(f"Valid tracks for threshold fitting: {len(gold_data_valid)}")
    
    if len(gold_data_valid) < 10:
        print("ERROR: Not enough valid tracks to fit thresholds")
        sys.exit(1)
    
    # Fit thresholds
    print("\n" + "=" * 60)
    print("FITTING THRESHOLDS")
    print("=" * 60)
    
    result = fit_thresholds_on_gold_pool(gold_data_valid, predictions_valid)
    
    # Print precision/coverage curves
    print("\nCUE4 PRECISION/COVERAGE CURVE:")
    print(f"{'Threshold':>10} | {'Precision':>10} | {'Coverage':>10}")
    print("-" * 40)
    for thresh, prec, cov in result.cue4_precision_curve:
        marker = ""
        if abs(prec - 0.80) < 0.05:
            marker = " <- 80%"
        elif abs(prec - 0.90) < 0.05:
            marker = " <- 90%"
        elif abs(prec - 0.95) < 0.025:
            marker = " <- 95%"
        print(f"{thresh:>10.2f} | {prec:>10.1%} | {cov:>10.1%}{marker}")
    
    print("\nCUE6 PRECISION/COVERAGE CURVE:")
    print(f"{'Threshold':>10} | {'Precision':>10} | {'Coverage':>10}")
    print("-" * 40)
    for thresh, prec, cov in result.cue6_precision_curve:
        marker = ""
        if abs(prec - 0.80) < 0.05:
            marker = " <- 80%"
        elif abs(prec - 0.90) < 0.05:
            marker = " <- 90%"
        elif abs(prec - 0.95) < 0.025:
            marker = " <- 95%"
        print(f"{thresh:>10.2f} | {prec:>10.1%} | {cov:>10.1%}{marker}")
    
    # Print recommended thresholds
    print("\n" + "=" * 60)
    print("RECOMMENDED THRESHOLDS")
    print("=" * 60)
    print("\nCUE4:")
    for target, thresh in result.cue4_thresholds.items():
        print(f"  {target}% precision: threshold >= {thresh:.2f}")
    
    print("\nCUE6:")
    for target, thresh in result.cue6_thresholds.items():
        print(f"  {target}% precision: threshold >= {thresh:.2f}")
    
    # Save results
    output = {
        "model": MODEL,
        "n_tracks": len(gold_data_valid),
        "cue4_thresholds": result.cue4_thresholds,
        "cue6_thresholds": result.cue6_thresholds,
        "cue4_curve": [{"threshold": t, "precision": p, "coverage": c} 
                       for t, p, c in result.cue4_precision_curve],
        "cue6_curve": [{"threshold": t, "precision": p, "coverage": c}
                       for t, p, c in result.cue6_precision_curve],
    }
    
    output_path = Path("/workspace/calibrated_thresholds.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
