#!/usr/bin/env python3
"""Compare LLM-only vs Ranker-only vs Combined for cue prediction.

Tests on 42-track eval set.
"""

import json
import os
import pickle
import sys
from pathlib import Path
from dataclasses import dataclass

import numpy as np

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    sys.exit(1)

from auto_cue.features import extract_features, PhraseFeatures
from auto_cue.gold import load_gold_csv, load_gold_pool, get_pool_fewshot_examples
from auto_cue.llm import predict_cues_llm

AUDIO_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
POOL_DIR = Path("/workspace/gold-pool")
MODEL_PATH = Path("/workspace/ranker_models.pkl")
MODEL = "gpt-6.1-terra"
REASONING = "medium"


def candidate_to_features(
    beat: int,
    phrase_map: dict,
    bpm: float,
    bpm_band: str,
    total_beats: int,
) -> np.ndarray:
    """Convert candidate to feature array for ranker."""
    phrase = phrase_map.get(beat)
    if phrase is None:
        # Find closest
        closest_beat = min(phrase_map.keys(), key=lambda b: abs(b - beat))
        phrase = phrase_map[closest_beat]
    
    return np.array([
        phrase.low_db,
        phrase.delta_low,
        phrase.delta_kick,
        phrase.contrast_score,
        phrase.novelty_score,
        phrase.pre_drop_gap,
        phrase.post_sustain,
        phrase.build_score,
        phrase.drop_score,
        beat / total_beats if total_beats > 0 else 0,
        bpm,
        1.0 if "bass" in bpm_band else 0.0,
        1.0 if "dnb" in bpm_band else 0.0,
        1.0 if "house" in bpm_band else 0.0,
    ])


def ranker_predict(
    candidates: list[int],
    model,
    phrase_map: dict,
    bpm: float,
    bpm_band: str,
    total_beats: int,
    half_track: bool = False,
) -> tuple[int, float]:
    """Use ranker to predict best candidate.
    
    Args:
        half_track: If True, only consider candidates in second half (for cue6)
    """
    if half_track:
        half = total_beats // 2
        candidates = [c for c in candidates if c >= half]
    
    if not candidates:
        return None, 0.0
    
    X = np.array([
        candidate_to_features(c, phrase_map, bpm, bpm_band, total_beats)
        for c in candidates
    ])
    
    probs = model.predict_proba(X)[:, 1]
    best_idx = np.argmax(probs)
    
    return candidates[best_idx], probs[best_idx]


def main():
    print("=" * 60)
    print("LLM vs RANKER vs COMBINED COMPARISON")
    print("=" * 60)
    
    # Load models
    with open(MODEL_PATH, 'rb') as f:
        models = pickle.load(f)
    
    cue4_model = models['cue4']['gbm']
    cue6_model = models['cue6']['gbm']
    print(f"Loaded ranker models from {MODEL_PATH}")
    
    # Load gold
    eval_tracks = load_gold_csv(GOLD_CSV)
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    # Results
    results = {
        'llm': {'cue4_correct': 0, 'cue4_total': 0, 'cue6_correct': 0, 'cue6_total': 0},
        'ranker': {'cue4_correct': 0, 'cue4_total': 0, 'cue6_correct': 0, 'cue6_total': 0},
        'combined': {'cue4_correct': 0, 'cue4_total': 0, 'cue6_correct': 0, 'cue6_total': 0},
    }
    
    total_cost = 0.0
    
    for i, (filename, gold) in enumerate(eval_tracks.items()):
        audio_path = AUDIO_DIR / filename
        if not audio_path.exists():
            continue
        
        print(f"\n[{i+1}/{len(eval_tracks)}] {filename} BPM={gold.bpm:.0f}")
        
        try:
            features = extract_features(
                audio_path, gold.bpm, gold.first_beat_s, use_demucs=False
            )
            
            # Build phrase map
            phrase_map = {}
            for p in features.phrases_16:
                phrase_map[p.beat_start] = p
            for p in features.phrases_32:
                phrase_map[p.beat_start] = p
            
            # Get examples for LLM
            examples = get_pool_fewshot_examples(
                pool, gold.bpm, features.total_beats, POOL_DIR, max_examples=5
            )
            
            # LLM prediction
            llm_pred = predict_cues_llm(
                features, model=MODEL, reasoning_effort=REASONING,
                genre_bucket=features.bpm_band, examples=examples,
            )
            total_cost += llm_pred.cost_usd
            
            # Ranker prediction
            ranker_cue4, ranker_cue4_prob = ranker_predict(
                features.drop_candidates, cue4_model, phrase_map,
                gold.bpm, gold.bpm_band, features.total_beats, half_track=False
            )
            ranker_cue6, ranker_cue6_prob = ranker_predict(
                features.drop_candidates, cue6_model, phrase_map,
                gold.bpm, gold.bpm_band, features.total_beats, half_track=True
            )
            
            # Combined: Use ranker if high confidence, else LLM
            # Threshold tuned for ~70% precision
            cue4_thresh = 0.3
            cue6_thresh = 0.3
            
            combined_cue4 = ranker_cue4 if ranker_cue4_prob > cue4_thresh else llm_pred.cue4_beat
            combined_cue6 = ranker_cue6 if ranker_cue6_prob > cue6_thresh else llm_pred.cue6_beat
            
            # Evaluate cue4
            gold_cue4 = gold.cues.get(3)
            if gold_cue4 is not None:
                for method, pred in [
                    ('llm', llm_pred.cue4_beat),
                    ('ranker', ranker_cue4),
                    ('combined', combined_cue4),
                ]:
                    results[method]['cue4_total'] += 1
                    if pred is not None and abs(pred - gold_cue4) <= 1:
                        results[method]['cue4_correct'] += 1
            
            # Evaluate cue6
            gold_cue6 = gold.cues.get(5)
            if gold_cue6 is not None:
                for method, pred in [
                    ('llm', llm_pred.cue6_beat),
                    ('ranker', ranker_cue6),
                    ('combined', combined_cue6),
                ]:
                    results[method]['cue6_total'] += 1
                    if pred is not None and abs(pred - gold_cue6) <= 1:
                        results[method]['cue6_correct'] += 1
            
            # Print progress
            for method in ['llm', 'ranker', 'combined']:
                c4 = results[method]['cue4_correct'] / results[method]['cue4_total'] * 100 if results[method]['cue4_total'] > 0 else 0
                c6 = results[method]['cue6_correct'] / results[method]['cue6_total'] * 100 if results[method]['cue6_total'] > 0 else 0
                print(f"  {method}: cue4={c4:.0f}%, cue6={c6:.0f}%")
            
        except Exception as e:
            print(f"  ERROR: {e}")
    
    # Final summary
    print("\n" + "=" * 60)
    print("FINAL COMPARISON")
    print("=" * 60)
    
    print("\n| Method | Cue4 | Cue6 |")
    print("|--------|------|------|")
    
    for method in ['llm', 'ranker', 'combined']:
        c4 = results[method]['cue4_correct'] / results[method]['cue4_total'] * 100 if results[method]['cue4_total'] > 0 else 0
        c6 = results[method]['cue6_correct'] / results[method]['cue6_total'] * 100 if results[method]['cue6_total'] > 0 else 0
        print(f"| {method:8s} | {c4:4.1f}% | {c6:4.1f}% |")
    
    print(f"\nTotal LLM cost: ${total_cost:.2f}")
    
    # Save results
    output = {
        'results': results,
        'cost': total_cost,
    }
    with open("/workspace/ranker_comparison_results.json", "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
