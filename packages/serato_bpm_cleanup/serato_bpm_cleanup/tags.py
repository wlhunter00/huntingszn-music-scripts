"""Read/write Serato GEOB frames and ID3 TBPM via mutagen.

ID3 COMM is never used for cue counts or BPM decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.id3 import GEOB, ID3, TBPM, ID3NoHeaderError

from serato_bpm_cleanup.autotags import AutoTags, dump_autotags, parse_autotags
from serato_bpm_cleanup.beatgrid import BeatGrid, dump_beatgrid, parse_beatgrid
from serato_bpm_cleanup.markers import (
    MARKERS2_GEOB,
    MARKERS_V1_GEOB,
    MarkerCounts,
    combine_marker_counts,
    parse_markers2_counts,
    parse_markers_v1_counts,
)

BEATGRID_GEOB = "Serato BeatGrid"
AUTOTAGS_GEOB = "Serato Autotags"
SERATO_WRITE_SUFFIXES = {".mp3", ".aiff", ".aif"}
AUDIO_SUFFIXES = {".mp3", ".aiff", ".aif", ".flac", ".wav", ".m4a", ".aac", ".ogg"}


@dataclass
class TrackSeratoData:
    path: Path
    tbpm: float | None = None
    beatgrid: BeatGrid | None = None
    autotags: AutoTags | None = None
    markers: MarkerCounts = field(default_factory=MarkerCounts)
    beatgrid_error: str | None = None
    autotags_error: str | None = None
    markers_error: str | None = None

    @property
    def cue_count(self) -> int:
        return self.markers.total

    @property
    def serato_bpm(self) -> float | None:
        """Prefer BeatGrid BPM, then Autotags, then ID3 TBPM."""
        if self.beatgrid is not None and self.beatgrid.bpm is not None:
            return float(self.beatgrid.bpm)
        if self.autotags is not None:
            return float(self.autotags.bpm)
        return self.tbpm


def _load_id3(path: Path) -> ID3 | None:
    suffix = path.suffix.lower()
    try:
        if suffix in {".aiff", ".aif"}:
            audio = AIFF(path)
            return audio.tags
        return ID3(path)
    except (ID3NoHeaderError, OSError, ValueError, TypeError):
        return None


def _geob_map(tags: ID3) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for frame in tags.getall("GEOB"):
        desc = getattr(frame, "desc", None) or ""
        data = getattr(frame, "data", None)
        if desc and data is not None:
            out[desc] = bytes(data)
    return out


def _parse_tbpm(tags: ID3) -> float | None:
    frame = tags.get("TBPM")
    if frame is None or not getattr(frame, "text", None):
        return None
    raw = str(frame.text[0]).strip()
    try:
        return float(raw)
    except ValueError:
        return None


def read_track(path: Path) -> TrackSeratoData:
    """Load Serato GEOB + TBPM. Cue count comes only from marker GEOBs."""
    result = TrackSeratoData(path=path)
    tags = _load_id3(path)
    if tags is None:
        return result
    result.tbpm = _parse_tbpm(tags)
    geobs = _geob_map(tags)

    v2 = v1 = None
    if MARKERS2_GEOB in geobs:
        try:
            v2 = parse_markers2_counts(geobs[MARKERS2_GEOB])
        except ValueError as exc:
            result.markers_error = str(exc)
    if MARKERS_V1_GEOB in geobs:
        try:
            v1 = parse_markers_v1_counts(geobs[MARKERS_V1_GEOB])
        except ValueError as exc:
            result.markers_error = str(exc)
    result.markers = combine_marker_counts(v2, v1)

    if BEATGRID_GEOB in geobs:
        try:
            result.beatgrid = parse_beatgrid(geobs[BEATGRID_GEOB])
        except ValueError as exc:
            result.beatgrid_error = str(exc)

    if AUTOTAGS_GEOB in geobs:
        try:
            result.autotags = parse_autotags(geobs[AUTOTAGS_GEOB])
        except ValueError as exc:
            result.autotags_error = str(exc)

    return result


def _replace_geob(tags: ID3, desc: str, data: bytes) -> None:
    kept = [frame for frame in tags.getall("GEOB") if (frame.desc or "") != desc]
    tags.delall("GEOB")
    for frame in kept:
        tags.add(frame)
    tags.add(
        GEOB(
            encoding=0,
            mime="application/octet-stream",
            desc=desc,
            data=data,
        )
    )


def write_bpm_tags(
    path: Path,
    *,
    bpm: int,
    beatgrid: BeatGrid | None,
    autotags: AutoTags | None,
    update_beatgrid: bool,
    update_autotags: bool,
) -> list[str]:
    """Write TBPM + optional Autotags/BeatGrid. Returns names of stores written."""
    suffix = path.suffix.lower()
    if suffix not in SERATO_WRITE_SUFFIXES:
        raise ValueError(f"cannot write Serato GEOB for {suffix}")

    if suffix in {".aiff", ".aif"}:
        audio = AIFF(path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None
        _apply_bpm_frames(
            tags,
            bpm=bpm,
            beatgrid=beatgrid,
            autotags=autotags,
            update_beatgrid=update_beatgrid,
            update_autotags=update_autotags,
        )
        audio.save()
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        _apply_bpm_frames(
            tags,
            bpm=bpm,
            beatgrid=beatgrid,
            autotags=autotags,
            update_beatgrid=update_beatgrid,
            update_autotags=update_autotags,
        )
        tags.save(path)

    written: list[str] = ["TBPM"]
    if update_autotags and autotags is not None:
        written.append("Serato Autotags")
    if update_beatgrid and beatgrid is not None:
        written.append("Serato BeatGrid")
    return written


def _apply_bpm_frames(
    tags: ID3,
    *,
    bpm: int,
    beatgrid: BeatGrid | None,
    autotags: AutoTags | None,
    update_beatgrid: bool,
    update_autotags: bool,
) -> None:
    tags.delall("TBPM")
    tags.add(TBPM(encoding=3, text=[f"{bpm:.2f}"]))
    if update_autotags and autotags is not None:
        _replace_geob(tags, AUTOTAGS_GEOB, dump_autotags(autotags.with_bpm(float(bpm))))
    if update_beatgrid and beatgrid is not None:
        _replace_geob(tags, BEATGRID_GEOB, dump_beatgrid(beatgrid.with_constant_bpm(float(bpm))))
