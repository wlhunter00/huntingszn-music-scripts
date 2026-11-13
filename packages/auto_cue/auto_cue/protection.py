"""Grid and track protection logic.

A track is protected (never written to) if ANY of these is true:
- Has any existing cue points (human cues, legacy cues, or MIK cues)
- Has BPM lock enabled
- Has a multi-marker (dynamic) grid
- Has loops or flips
- Any ambiguity or error reading tags

Crate membership does not protect a track. Tracks with only MIK
"Energy N" cues can be replaced when --replace-mik is set.
Protected tracks may be analyzed and reported, but never written.
"""

from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from serato_bpm_cleanup.markers import MARKERS_V1_ENTRY_LEN, parse_markers_v1_counts

from auto_cue.tags import TrackTags


@dataclass
class ProtectionStatus:
    """Result of protection check."""
    protected: bool
    reasons: list[str]
    can_replace_mik: bool = False

    def __str__(self) -> str:
        if not self.protected:
            return "not protected"
        return f"protected: {', '.join(self.reasons)}"


def normalize_path(path: str) -> str:
    """NFC-normalize a path for matching."""
    return unicodedata.normalize("NFC", path)


def parse_crate_file(crate_path: Path) -> list[str]:
    """Parse a Serato .crate file and return list of track paths.

    Crate format: entries are `ptrk` chunks with UTF-16BE paths.
    """
    def parse_chunks(data: bytes) -> list[str]:
        paths = []
        pos = 0
        while pos < len(data):
            if len(data) - pos < 8:
                raise ValueError("truncated crate chunk header")
            chunk_type = data[pos:pos + 4]
            chunk_len = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            pos += 8
            end = pos + chunk_len
            if end > len(data):
                raise ValueError("truncated crate chunk payload")
            payload = data[pos:end]
            if chunk_type == b"otrk":
                paths.extend(parse_chunks(payload))
            elif chunk_type == b"ptrk":
                paths.append(normalize_path(payload.decode("utf-16-be").rstrip("\x00")))
            pos = end
        return paths

    try:
        return parse_chunks(crate_path.read_bytes())
    except (OSError, ValueError, RecursionError) as e:
        message = f"cannot read crate {crate_path}: {e}"
        raise ValueError(message) from e


def check_protection(track: TrackTags) -> ProtectionStatus:
    """Check if a track is protected from modification.

    Existing cue points always protect the track. Crate membership does not.

    Args:
        track: Parsed track tags

    Returns:
        ProtectionStatus with reasons if protected
    """
    reasons = []
    can_replace_mik = False

    if track.error:
        reasons.append(f"tag error: {track.error}")

    if track.markers_v1_raw is not None:
        try:
            data = track.markers_v1_raw
            if len(data) < 6:
                raise ValueError("truncated legacy marker header")
            count = struct.unpack(">I", data[2:6])[0]
            if len(data) < 6 + count * MARKERS_V1_ENTRY_LEN + 4:
                raise ValueError("truncated legacy marker entries")
            if parse_markers_v1_counts(data).total:
                reasons.append("has legacy cues or loops")
        except ValueError as e:
            reasons.append(f"legacy marker error: {e}")

    if track.markers2:
        if track.markers2.has_human_cues():
            reasons.append("has human cues")
        elif track.markers2.all_mik_cues():
            can_replace_mik = True

        if track.markers2.bpm_lock:
            reasons.append("BPM locked")

        if track.markers2.loops:
            reasons.append("has loops")

        if track.markers2.flip_entries:
            reasons.append("has flips")

    if track.beatgrid and track.beatgrid.is_dynamic:
        reasons.append("dynamic (multi-marker) grid")

    return ProtectionStatus(
        protected=len(reasons) > 0,
        reasons=reasons,
        can_replace_mik=can_replace_mik and len(reasons) == 0,
    )


def check_grid_protection(track: TrackTags) -> ProtectionStatus:
    """Check if a track's grid is protected from modification.

    Grids have stricter protection than cues:
    - All cue protection reasons apply
    - Additionally protected if track has ANY cues (even MIK)
    """
    base_status = check_protection(track)

    reasons = list(base_status.reasons)

    if track.markers2 and track.markers2.cues:
        if "has human cues" not in reasons:
            reasons.append("has existing cues (grid is established)")

    return ProtectionStatus(
        protected=len(reasons) > 0,
        reasons=reasons,
        can_replace_mik=False,
    )


@dataclass
class CueWriteDecision:
    """Decision about whether/how to write cues to a track."""
    action: str  # write, skip, replace-mik, abstain
    reasons: list[str]

    @property
    def should_write(self) -> bool:
        return self.action in ("write", "replace-mik")


def decide_cue_write(
    track: TrackTags,
    *,
    replace_mik: bool = False,
) -> CueWriteDecision:
    """Decide whether to write cues to a track.

    Any existing cue point blocks the write. MIK-only cues are replaced
    only when replace_mik is set. Crate membership is ignored.

    Args:
        track: Parsed track tags
        replace_mik: Whether --replace-mik flag is set

    Returns:
        CueWriteDecision with action and reasons
    """
    protection = check_protection(track)

    if protection.protected:
        return CueWriteDecision(action="skip", reasons=protection.reasons)

    if track.markers2 and track.markers2.cues:
        if track.markers2.all_mik_cues() and replace_mik:
            return CueWriteDecision(action="replace-mik", reasons=["replacing MIK cues"])
        else:
            return CueWriteDecision(action="skip", reasons=["has existing cues"])

    if not track.beatgrid:
        return CueWriteDecision(action="abstain", reasons=["no beatgrid"])

    return CueWriteDecision(action="write", reasons=["no existing cues, has grid"])
