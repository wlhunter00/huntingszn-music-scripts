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
    "phase_support",
]


def has_32beat_build(features: TrackFeatures, beat: int | None) -> bool | None:
    """Whether bass and RMS rise from the preceding 32 to the following 16 beats."""
    audio = features.beat_features
    if beat is None or beat < 32 or beat + 16 > len(audio):
        return None
    values = np.array([[b.low_db, b.rms_db] for b in audio[beat - 32:beat + 16]])
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite audio in build prior")
    return bool(np.all(values[32:].mean(axis=0) > values[:32].mean(axis=0)))


def apply_build_prior(
    features: TrackFeatures,
    picks: tuple[int | None, int | None],
    rankings: tuple[list[int], list[int]],
) -> tuple[int | None, int | None]:
    """Replace unsupported picks with build-supported ranked candidates, preserving order."""
    result = list(picks)
    for index in (0, 1):
        if has_32beat_build(features, result[index]) is not False:
            continue
        for beat in rankings[index]:
            if beat not in features.drop_candidates:
                continue
            other = result[1 - index]
            if other is not None and (beat > other if index == 0 else beat < other):
                continue
            if has_32beat_build(features, beat) is True:
                result[index] = beat
                break
    return tuple(result)


def phrase_at_beat(features: TrackFeatures, beat: int) -> PhraseFeatures | None:
    """Phrase that starts at this beat, preferring the 32-beat phrase on that grid."""
    for phrase in features.phrases_32:
        if phrase.beat_start == beat:
            return phrase
    for phrase in features.phrases_16:
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
    phase_support = getattr(features, "phase_support", [])
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
            phase_support[(beat % 16) // 4] if phase_support else 0.0,
        ],
        dtype=float,
    )
