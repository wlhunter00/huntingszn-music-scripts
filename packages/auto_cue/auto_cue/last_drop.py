"""Audio-only last-drop descriptors and fixed experimental filters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from auto_cue.ranker import apply_build_prior, candidate_vector

if TYPE_CHECKING:
    from auto_cue.features import TrackFeatures


LAST_DROP_NAMES = [
    "later_drop_sections", "beats_to_end_32", "post_bass_trend", "post_rms_trend",
    "post_kick_trend", "bass_relative_peak", "rms_relative_peak", "kick_relative_peak",
]


def last_drop_context(features: TrackFeatures) -> dict[int, dict]:
    audio = np.asarray([[b.low_db, b.rms_db, b.kick_onset] for b in features.beat_features])
    if not len(audio):
        return {}
    if not np.isfinite(audio).all():
        raise ValueError("Nonfinite audio in last-drop context")
    beats = [b for b in features.drop_candidates if 0 <= b and b + 16 <= len(audio)]
    if not beats:
        return {}
    levels = {b: audio[b:b + 16].mean(axis=0) for b in beats}
    peak = np.max(list(levels.values()), axis=0)
    strong = {
        b: bool(levels[b][0] >= peak[0] - 6 and levels[b][1] >= peak[1] - 6
                and peak[2] > 0 and levels[b][2] >= peak[2] * 0.5)
        for b in beats
    }
    result = {}
    for beat in beats:
        level = levels[beat]
        after = audio[beat + 16:beat + 48]
        trend = after.mean(axis=0) - level if len(after) else np.zeros(3)
        tail = audio[beat + 16:beat + 80]
        decline = tail.mean(axis=0) - level if len(tail) else np.zeros(3)
        later = []
        for b in sorted(beats):
            if b >= beat + 16 and strong[b] and (not later or b - later[-1] >= 16):
                later.append(b)
        near = any(strong[b] and beat + 16 <= b <= beat + 48 for b in beats)
        outro = bool((peak[2] > 0 and level[2] < peak[2] * 0.5)
                     or (features.total_beats - beat <= 64 and trend[0] < 0 and trend[1] < 0))
        result[beat] = dict(
            vector=np.array([
                len(later), (features.total_beats - beat) / 32,
                *trend, level[0] - peak[0], level[1] - peak[1],
                level[2] / peak[2] if peak[2] > 0 else 0,
            ]),
            strong=strong[beat], outro=outro,
            last_full=bool(strong[beat] and not near and len(tail) >= 32
                           and decline[0] <= -3 and decline[1] <= -3),
        )
    return result


def last_drop_vectors(
    features: TrackFeatures, *, include_track_pct: bool,
) -> tuple[list[int], np.ndarray]:
    context = last_drop_context(features)
    candidates = list(features.drop_candidates)
    later = [b for b in candidates if b >= features.total_beats // 2]
    candidates = later or candidates
    beats, vectors = [], []
    for beat in candidates:
        base = candidate_vector(features, beat, include_track_pct=include_track_pct)
        if base is not None:
            beats.append(beat)
            extra = context[beat]["vector"] if beat in context else np.zeros(len(LAST_DROP_NAMES))
            vectors.append(np.concatenate([base, extra]))
    return beats, np.asarray(vectors)


def filter_last_drop(
    features: TrackFeatures,
    picks: tuple[int | None, int | None],
    ranking: list[tuple[int, float]],
    *,
    rule: str,
) -> tuple[int | None, int | None]:
    if rule not in ("last_full", "outro_filter"):
        raise ValueError("Unknown last-drop rule")
    cue4, cue6 = picks
    if cue6 is None:
        return picks
    context = last_drop_context(features)
    valid = [b for b, _ in ranking if b in context and (cue4 is None or b >= cue4)]
    if rule == "last_full":
        passing = [b for b in valid if context[b]["last_full"]]
        return cue4, max(passing) if passing else cue6
    if cue6 not in context or not context[cue6]["outro"]:
        return picks
    passing = [b for b in valid if not context[b]["outro"]]
    return cue4, passing[0] if passing else cue6


def apply_last_drop_ranker(
    features: TrackFeatures,
    picks: tuple[int | None, int | None],
    ranking: list[tuple[int, float]],
    *,
    llm_beat: int | None,
    ranker_only: bool = False,
    build32: bool = False,
) -> tuple[int | None, int | None]:
    """Refine only cue6 with the fixed ranker gate, optionally retaining the build prior."""
    cue4, cue6 = picks
    if cue6 is None:
        return picks
    for beat, score in ranking:
        if beat not in features.drop_candidates or not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid last-drop ranking")
    valid = [(b, p) for b, p in ranking if cue4 is None or b >= cue4]
    if not valid:
        return picks
    beat, score = valid[0]
    selected = beat if ranker_only or score >= 0.3 else llm_beat
    if cue4 is not None and selected is not None and selected < cue4:
        return picks
    result = (cue4, selected)
    if build32:
        result = apply_build_prior(features, result, ([], [b for b, _ in valid]))
    return result
