#!/usr/bin/env python3
"""Analyze cue6 candidate recall - how often is gold cue6 in the candidate list?"""

from pathlib import Path

from auto_cue.features import extract_features
from auto_cue.gold import load_gold_csv

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")


def main():
    gold_tracks = load_gold_csv(GOLD_CSV)
    
    total = 0
    gold_in_candidates = 0
    gold_within_1 = 0
    
    errors = []
    
    for filename, track in gold_tracks.items():
        audio_path = AUDIO_DIR / filename
        if not audio_path.exists():
            continue
            
        gold_cue6 = track.cues.get(5)  # 0-indexed
        if gold_cue6 is None:
            continue
            
        total += 1
        
        features = extract_features(audio_path, track.bpm, track.first_beat_s, use_demucs=False)
        
        # Check if gold is in candidates
        gold_beat = int(round(gold_cue6))
        
        if gold_beat in features.drop_candidates:
            gold_in_candidates += 1
        elif any(abs(c - gold_beat) <= 1 for c in features.drop_candidates):
            gold_within_1 += 1
        else:
            # Find nearest candidate
            if features.drop_candidates:
                nearest = min(features.drop_candidates, key=lambda c: abs(c - gold_beat))
                error = nearest - gold_beat
            else:
                nearest = None
                error = float('inf')
            errors.append({
                "track": filename,
                "gold": gold_beat,
                "nearest_candidate": nearest,
                "error": error,
                "bpm_band": track.bpm_band,
                "candidates": features.drop_candidates[:10],
            })
    
    print(f"Cue6 Candidate Recall Analysis")
    print(f"=" * 60)
    print(f"\nTotal tracks with gold cue6: {total}")
    print(f"Gold exactly in candidates: {gold_in_candidates} ({gold_in_candidates/total*100:.1f}%)")
    print(f"Gold within ±1 of candidate: {gold_within_1} ({gold_within_1/total*100:.1f}%)")
    print(f"Gold NOT covered: {len(errors)} ({len(errors)/total*100:.1f}%)")
    
    print(f"\n\nMissing gold cue6 positions:")
    for e in errors:
        print(f"  {e['track']} ({e['bpm_band']}): gold={e['gold']}, nearest={e['nearest_candidate']}, err={e['error']}")
        print(f"    candidates: {e['candidates']}")


if __name__ == "__main__":
    main()
