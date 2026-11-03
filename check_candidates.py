#!/usr/bin/env python3
"""Check what drop candidates are offered to LLM for error tracks."""

from pathlib import Path

from auto_cue.features import extract_features
from auto_cue.gold import load_gold_csv

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")

# Error cases where model picked 16 beats early
ERRORS = [
    ("qa01.mp3", 80, 96),   # pred, gold for cue4
    ("qa12.mp3", 48, 63),
    ("qa14.mp3", 64, 80),
    ("qa15.mp3", 80, 95),
    ("qa17.mp3", 48, 64),
    ("qa22.mp3", 64, 80),
    ("qa23.mp3", 64, 79),
]

def main():
    gold_tracks = load_gold_csv(GOLD_CSV)
    
    for track, pred, gold_beat in ERRORS:
        audio_path = AUDIO_DIR / track
        gold = gold_tracks[track]
        
        print(f"\n{'='*60}")
        print(f"{track}: pred={pred}, gold={gold_beat}")
        print(f"{'='*60}")
        
        features = extract_features(audio_path, gold.bpm, gold.first_beat_s, use_demucs=False)
        
        print(f"\nDrop candidates offered: {features.drop_candidates}")
        
        # Check if both pred and gold positions are in candidates
        pred_in = pred in features.drop_candidates
        gold_in = gold_beat in features.drop_candidates
        gold_minus_1 = (gold_beat - 1) in features.drop_candidates
        gold_rounded = (gold_beat // 16 * 16) in features.drop_candidates
        
        print(f"  Pred ({pred}) in candidates: {pred_in}")
        print(f"  Gold ({gold_beat}) in candidates: {gold_in}")
        print(f"  Gold-1 ({gold_beat-1}) in candidates: {gold_minus_1}")
        print(f"  Gold rounded to 16 ({gold_beat // 16 * 16}) in candidates: {gold_rounded}")
        
        # Show scores for relevant phrases
        relevant_beats = {pred, gold_beat, gold_beat - 1, gold_beat // 16 * 16}
        for phrase in features.phrases_32:
            if phrase.beat_start in relevant_beats:
                print(f"\n  Phrase at {phrase.beat_start}:")
                print(f"    low_db={phrase.low_db:.1f}, Δlow={phrase.delta_low:.1f}")
                print(f"    drop_score={phrase.drop_score:.2f}, is_candidate={phrase.is_drop_candidate}")

if __name__ == "__main__":
    main()
