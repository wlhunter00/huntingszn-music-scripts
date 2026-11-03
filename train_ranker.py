#!/usr/bin/env python3
"""Train a small candidate ranker (logistic/GBM) on gold-pool candidates.

Compares:
- LLM-only (current approach)
- Ranker-only
- Combined (ranker filters, then LLM)
"""

import json
import os
import pickle
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score

from auto_cue.features import extract_features, PhraseFeatures
from auto_cue.gold import load_gold_csv, load_gold_pool

POOL_DIR = Path("/workspace/gold-pool")
EVAL_DIR = Path("/workspace/qa-all")
GOLD_CSV = Path("/workspace/qa-all/gold.csv")
RANDOM_SEED = 42


@dataclass
class CandidateFeature:
    """Features for a single candidate beat position."""
    beat: int
    is_cue4_gold: bool = False
    is_cue6_gold: bool = False
    
    # Phrase features
    low_db: float = 0.0
    delta_low: float = 0.0
    delta_kick: float = 0.0
    contrast_score: float = 0.0
    novelty_score: float = 0.0
    pre_drop_gap: float = 0.0
    post_sustain: float = 0.0
    build_score: float = 0.0
    drop_score: float = 0.0
    track_pct: float = 0.0  # Position in track (0-1)
    
    # Context features
    bpm: float = 0.0
    bpm_band: str = ""
    total_beats: int = 0
    
    def to_array(self) -> np.ndarray:
        """Convert to feature array for ML."""
        return np.array([
            self.low_db,
            self.delta_low,
            self.delta_kick,
            self.contrast_score,
            self.novelty_score,
            self.pre_drop_gap,
            self.post_sustain,
            self.build_score,
            self.drop_score,
            self.track_pct,
            self.bpm,
            # One-hot encode BPM band
            1.0 if "bass" in self.bpm_band else 0.0,
            1.0 if "dnb" in self.bpm_band else 0.0,
            1.0 if "house" in self.bpm_band else 0.0,
        ])


def extract_candidate_features(
    track_features,
    gold_cue4: Optional[float],
    gold_cue6: Optional[float],
    bpm: float,
    bpm_band: str,
) -> list[CandidateFeature]:
    """Extract features for all drop candidates in a track."""
    candidates = []
    
    # Build phrase lookup
    phrase_map = {}
    for p in track_features.phrases_16:
        phrase_map[p.beat_start] = p
    for p in track_features.phrases_32:
        phrase_map[p.beat_start] = p
    
    for beat in track_features.drop_candidates:
        phrase = phrase_map.get(beat)
        if phrase is None:
            # Find closest phrase
            closest = min(track_features.phrases_16, key=lambda p: abs(p.beat_start - beat))
            phrase = closest
        
        cf = CandidateFeature(
            beat=beat,
            is_cue4_gold=(gold_cue4 is not None and abs(beat - gold_cue4) <= 1),
            is_cue6_gold=(gold_cue6 is not None and abs(beat - gold_cue6) <= 1),
            low_db=phrase.low_db,
            delta_low=phrase.delta_low,
            delta_kick=phrase.delta_kick,
            contrast_score=phrase.contrast_score,
            novelty_score=phrase.novelty_score,
            pre_drop_gap=phrase.pre_drop_gap,
            post_sustain=phrase.post_sustain,
            build_score=phrase.build_score,
            drop_score=phrase.drop_score,
            track_pct=beat / track_features.total_beats if track_features.total_beats > 0 else 0,
            bpm=bpm,
            bpm_band=bpm_band,
            total_beats=track_features.total_beats,
        )
        candidates.append(cf)
    
    return candidates


def build_training_data(limit: int = 200):
    """Build training data from gold pool."""
    print("Building training data from gold pool...")
    
    pool_csv = POOL_DIR / "gold_pool_clean.csv"
    audio_sel = POOL_DIR / "audio_sel.csv"
    pool = load_gold_pool(pool_csv, audio_sel)
    
    # Exclude eval set
    eval_tracks = load_gold_csv(GOLD_CSV)
    eval_filenames = set(eval_tracks.keys())
    
    all_candidates = []
    processed = 0
    
    for name, track in pool.tracks.items():
        if name in eval_filenames:
            continue
        if not track.has_audio:
            continue
            
        small_file = pool.audio_map.get(name)
        if not small_file:
            continue
        audio_path = POOL_DIR / small_file
        if not audio_path.exists():
            continue
        
        if processed >= limit:
            break
            
        try:
            features = extract_features(audio_path, track.bpm, track.first_beat_s, use_demucs=False)
            
            gold_cue4 = track.cues.get(3)
            gold_cue6 = track.cues.get(5)
            
            candidates = extract_candidate_features(
                features, gold_cue4, gold_cue6, track.bpm, track.bpm_band
            )
            all_candidates.extend(candidates)
            processed += 1
            
            if processed % 20 == 0:
                print(f"  Processed {processed}/{limit} tracks, {len(all_candidates)} candidates")
                
        except Exception as e:
            print(f"  Error processing {name}: {e}")
    
    print(f"\nTotal: {processed} tracks, {len(all_candidates)} candidates")
    
    # Count positive examples
    cue4_pos = sum(1 for c in all_candidates if c.is_cue4_gold)
    cue6_pos = sum(1 for c in all_candidates if c.is_cue6_gold)
    print(f"Cue4 positives: {cue4_pos} ({cue4_pos/len(all_candidates)*100:.1f}%)")
    print(f"Cue6 positives: {cue6_pos} ({cue6_pos/len(all_candidates)*100:.1f}%)")
    
    return all_candidates


def train_ranker(candidates: list[CandidateFeature], cue_type: str = "cue4"):
    """Train ranker for a specific cue type."""
    print(f"\nTraining {cue_type} ranker...")
    
    # Prepare data
    X = np.array([c.to_array() for c in candidates])
    if cue_type == "cue4":
        y = np.array([1 if c.is_cue4_gold else 0 for c in candidates])
    else:
        y = np.array([1 if c.is_cue6_gold else 0 for c in candidates])
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_SEED, stratify=y
    )
    
    print(f"  Train: {len(X_train)} samples, {sum(y_train)} positives")
    print(f"  Test: {len(X_test)} samples, {sum(y_test)} positives")
    
    # Train models
    models = {}
    
    # Logistic Regression
    lr = LogisticRegression(random_state=RANDOM_SEED, max_iter=1000, class_weight='balanced')
    lr.fit(X_train, y_train)
    models['logistic'] = lr
    
    # Gradient Boosting
    gbm = GradientBoostingClassifier(
        n_estimators=100, max_depth=3, random_state=RANDOM_SEED
    )
    gbm.fit(X_train, y_train)
    models['gbm'] = gbm
    
    # Evaluate
    print(f"\n  {cue_type} Results on test set:")
    for name, model in models.items():
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]
        
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        print(f"    {name}: precision={prec:.3f}, recall={rec:.3f}, F1={f1:.3f}")
    
    return models, X_test, y_test


def main():
    print("=" * 60)
    print("CANDIDATE RANKER TRAINING")
    print("=" * 60)
    
    # Build training data
    candidates = build_training_data(limit=150)
    
    # Train cue4 ranker
    cue4_models, X_test_4, y_test_4 = train_ranker(candidates, "cue4")
    
    # Train cue6 ranker  
    cue6_models, X_test_6, y_test_6 = train_ranker(candidates, "cue6")
    
    # Save models
    model_data = {
        'cue4': {
            'logistic': cue4_models['logistic'],
            'gbm': cue4_models['gbm'],
        },
        'cue6': {
            'logistic': cue6_models['logistic'],
            'gbm': cue6_models['gbm'],
        },
    }
    
    model_path = Path("/workspace/ranker_models.pkl")
    with open(model_path, 'wb') as f:
        pickle.dump(model_data, f)
    print(f"\nSaved models to {model_path}")
    
    # Feature importance for GBM
    print("\n" + "=" * 60)
    print("FEATURE IMPORTANCE (GBM)")
    print("=" * 60)
    
    feature_names = [
        'low_db', 'delta_low', 'delta_kick', 'contrast', 'novelty',
        'pre_gap', 'post_sust', 'build', 'drop_score', 'track_pct',
        'bpm', 'is_bass', 'is_dnb', 'is_house'
    ]
    
    for cue_type in ['cue4', 'cue6']:
        gbm = model_data[cue_type]['gbm']
        importances = gbm.feature_importances_
        sorted_idx = np.argsort(importances)[::-1]
        
        print(f"\n{cue_type}:")
        for i in sorted_idx[:7]:
            print(f"  {feature_names[i]}: {importances[i]:.3f}")


if __name__ == "__main__":
    main()
