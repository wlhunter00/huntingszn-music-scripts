"""Candidate ranker features shared by training and leak-free evaluation.

The position prior `track_pct` is optional so a fold can ablate it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from auto_cue.features import PhraseFeatures, TrackFeatures

FEATURE_NAMES = [
    "low_db",
    "delta_low",
    "delta_kick",
    "contrast",
    "novelty",
    "pre_gap",
    "post_sust",
    "build",
    "drop_score",
    "track_pct",
    "bpm",
    "is_bass",
    "is_dnb",
    "is_house",
]


def phrase_at_beat(features: TrackFeatures, beat: int) -> PhraseFeatures | None:
    """Phrase that starts at this beat, preferring the 32-beat phrase on that grid."""
    if beat % 32 == 0:
        for phrase in features.phrases_32:
            if phrase.beat_start == beat:
                return phrase
    for phrase in features.phrases_16:
        if phrase.beat_start == beat:
            return phrase
    for phrase in features.phrases_32:
        if phrase.beat_start == beat:
            return phrase
    return None


def candidate_vector(
    features: TrackFeatures,
    beat: int,
    *,
    include_track_pct: bool,
) -> np.ndarray | None:
    """One candidate row. `track_pct` is zeroed when ablated so the column stays aligned."""
    phrase = phrase_at_beat(features, beat)
    if phrase is None:
        return None
    bpm = features.bpm
    total = features.total_beats or 1
    track_pct = (beat / total) if include_track_pct else 0.0
    return np.array(
        [
            phrase.low_db,
            phrase.delta_low,
            phrase.delta_kick,
            phrase.contrast_score,
            phrase.novelty_score,
            phrase.pre_drop_gap,
            phrase.post_sustain,
            phrase.build_score,
            phrase.drop_score,
            track_pct,
            bpm,
            1.0 if bpm < 80 else 0.0,
            1.0 if 80 <= bpm < 100 else 0.0,
            1.0 if bpm >= 115 else 0.0,
        ],
        dtype=float,
    )
