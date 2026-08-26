"""Decide fix vs skip from BPM + Serato marker cue count."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from serato_bpm_cleanup import (
    ACTION_FIX,
    ACTION_SKIP_ALREADY_INTEGER,
    ACTION_SKIP_HAS_CUES,
    ACTION_SKIP_NO_BPM,
)
from serato_bpm_cleanup.bpm import is_non_integer_bpm, proposed_integer_bpm
from serato_bpm_cleanup.tags import TrackSeratoData


@dataclass
class TrackReport:
    path: Path
    current_bpm: float | None
    proposed_bpm: int | None
    cue_count: int
    action: str
    rewrites: str = ""
    notes: str = ""
    error: str | None = None
    grid_constant: bool | None = None
    first_beat_s: float | None = None
    sources: dict[str, float | None] = field(default_factory=dict)

    @property
    def has_cues(self) -> bool:
        return self.cue_count > 0


def planned_rewrites(data: TrackSeratoData, *, action: str) -> str:
    if action != ACTION_FIX:
        return ""
    parts: list[str] = ["TBPM"]
    if data.autotags is not None:
        parts.append("Serato Autotags")
    if data.beatgrid is not None and data.beatgrid.is_constant:
        parts.append("Serato BeatGrid")
    elif data.beatgrid is not None and data.beatgrid.is_dynamic:
        parts.append("BeatGrid-skipped-dynamic")
    return ",".join(parts)


def classify_track(data: TrackSeratoData, db_bpm: float | None = None) -> TrackReport:
    cue_count = data.cue_count
    current = data.serato_bpm
    if current is None:
        current = db_bpm

    sources = {
        "beatgrid": None if data.beatgrid is None else data.beatgrid.bpm,
        "autotags": None if data.autotags is None else data.autotags.bpm,
        "tbpm": data.tbpm,
        "database": db_bpm,
    }

    grid_constant = None
    first_beat_s = None
    if data.beatgrid is not None:
        grid_constant = data.beatgrid.is_constant
        first_beat_s = data.beatgrid.first_beat_s

    notes_parts: list[str] = []
    if data.markers_error:
        notes_parts.append(f"markers:{data.markers_error}")
    if data.beatgrid_error:
        notes_parts.append(f"beatgrid:{data.beatgrid_error}")
    if data.beatgrid is not None and data.beatgrid.is_dynamic:
        notes_parts.append("dynamic-grid-not-rewritten")

    if current is None:
        return TrackReport(
            path=data.path,
            current_bpm=None,
            proposed_bpm=None,
            cue_count=cue_count,
            action=ACTION_SKIP_NO_BPM,
            notes=";".join(notes_parts),
            grid_constant=grid_constant,
            first_beat_s=first_beat_s,
            sources=sources,
        )

    proposed = proposed_integer_bpm(current)
    fractional = is_non_integer_bpm(current)

    if not fractional:
        action = ACTION_SKIP_ALREADY_INTEGER
    elif cue_count > 0:
        action = ACTION_SKIP_HAS_CUES
        notes_parts.append("has cues, left alone")
    else:
        action = ACTION_FIX

    return TrackReport(
        path=data.path,
        current_bpm=current,
        proposed_bpm=proposed,
        cue_count=cue_count,
        action=action,
        rewrites=planned_rewrites(data, action=action),
        notes=";".join(notes_parts),
        grid_constant=grid_constant,
        first_beat_s=first_beat_s,
        sources=sources,
    )
