#!/usr/bin/env python3
"""Analyze ±16 errors in detail to find a better fix."""

import json
from pathlib import Path

from auto_cue.features import extract_features
from auto_cue.gold import load_gold_csv

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")

# Errors from baseline evaluation
ERRORS_16 = [
    # (track, cue, pred, gold)
    ("qa01.mp3", "cue4", 80, 96),
    ("qa12.mp3", "cue4", 48, 63),
    ("qa12.mp3", "cue6", 160, 175),
    ("qa14.mp3", "cue4", 64, 80),
    ("qa14.mp3", "cue6", 192, 208),
    ("qa15.mp3", "cue4", 80, 95),
    ("qa15.mp3", "cue6", 176, 191),
    ("qa17.mp3", "cue4", 48, 64),
    ("qa22.mp3", "cue4", 64, 80),
    ("qa22.mp3", "cue6", 224, 240),
    ("qa23.mp3", "cue4", 64, 79),
    ("qa23.mp3", "cue6", 192, 208),
    ("qa31.mp3", "cue4", 144, 127),  # This is +16 (pred > gold)
    ("qa38.mp3", "cue4", 128, 111),  # This is +16
]

def get_phrase_at_beat(phrases, beat):
    """Find phrase containing or starting at beat."""
    for p in phrases:
        if p.beat_start == beat or (p.beat_start <= beat < p.beat_end):
            return p
    return None

def main():
    gold_tracks = load_gold_csv(GOLD_CSV)
    
    results = []
    
    for track, cue, pred, gold in ERRORS_16:
        audio_path = AUDIO_DIR / track
        if not audio_path.exists():
            continue
            
        gold_data = gold_tracks.get(track)
        if not gold_data:
            continue
            
        print(f"\n{track} {cue}: pred={pred}, gold={gold}, error={pred-gold}")
        
        features = extract_features(audio_path, gold_data.bpm, gold_data.first_beat_s, use_demucs=False)
        
        # Get 16-beat phrases
        phrases_16 = features.phrases_16
        
        pred_phrase = get_phrase_at_beat(phrases_16, pred)
        gold_phrase = get_phrase_at_beat(phrases_16, gold)
        
        if pred_phrase and gold_phrase:
            print(f"  PRED ({pred}): low={pred_phrase.low_db:.1f}, Δlow={pred_phrase.delta_low:.1f}, "
                  f"Δkick={pred_phrase.delta_kick:.1f}, drop={pred_phrase.drop_score:.2f}")
            print(f"  GOLD ({gold}): low={gold_phrase.low_db:.1f}, Δlow={gold_phrase.delta_low:.1f}, "
                  f"Δkick={gold_phrase.delta_kick:.1f}, drop={gold_phrase.drop_score:.2f}")
            
            # Key discriminating features
            pred_is_transition = pred_phrase.delta_low > 5 or pred_phrase.delta_kick > 5
            gold_is_sustained = gold_phrase.low_db > -25 and abs(gold_phrase.delta_low) < 5
            
            print(f"  PRED is_transition (Δlow>5 or Δkick>5): {pred_is_transition}")
            print(f"  GOLD is_sustained (low>-25 and |Δlow|<5): {gold_is_sustained}")
            
            results.append({
                "track": track,
                "cue": cue,
                "pred": pred,
                "gold": gold,
                "error": pred - gold,
                "pred_low": pred_phrase.low_db,
                "pred_delta_low": pred_phrase.delta_low,
                "pred_delta_kick": pred_phrase.delta_kick,
                "pred_drop_score": pred_phrase.drop_score,
                "gold_low": gold_phrase.low_db,
                "gold_delta_low": gold_phrase.delta_low,
                "gold_delta_kick": gold_phrase.delta_kick,
                "gold_drop_score": gold_phrase.drop_score,
                "pred_is_transition": pred_is_transition,
                "gold_is_sustained": gold_is_sustained,
            })
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    minus_16 = [r for r in results if r["error"] < 0]
    plus_16 = [r for r in results if r["error"] > 0]
    
    print(f"\nTotal -16 errors (pred before gold): {len(minus_16)}")
    print(f"Total +16 errors (pred after gold): {len(plus_16)}")
    
    # Check pattern: for -16 errors, is pred a transition and gold sustained?
    pred_trans_gold_sust = sum(1 for r in minus_16 if r["pred_is_transition"] and r["gold_is_sustained"])
    print(f"\n-16 errors where pred=transition and gold=sustained: {pred_trans_gold_sust}/{len(minus_16)}")
    
    # Average features
    if minus_16:
        avg_pred_delta_low = sum(r["pred_delta_low"] for r in minus_16) / len(minus_16)
        avg_gold_delta_low = sum(r["gold_delta_low"] for r in minus_16) / len(minus_16)
        print(f"\n-16 errors avg Δlow: pred={avg_pred_delta_low:.1f}, gold={avg_gold_delta_low:.1f}")
    
    with open("/workspace/16_error_analysis_v2.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to: /workspace/16_error_analysis_v2.json")

if __name__ == "__main__":
    main()
