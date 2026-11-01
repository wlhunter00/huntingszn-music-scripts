"""Grid and track protection logic.

A track is protected (never written to) if ANY of these is true:
- Has any human (non-MIK) cues
- Has BPM lock enabled
- Is in Sets/, Perma Playlists/, or Produced by me crates
- Has a multi-marker (dynamic) grid
- Has loops or flips
- Any ambiguity or error reading tags

Protected tracks may be analyzed and reported, but never written.
"""

from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

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


PROTECTED_CRATE_PREFIXES = (
    "Sets/",
    "Perma Playlists/",
    "Produced by me",
)


def normalize_path(path: str) -> str:
    """NFC-normalize a path for matching."""
    return unicodedata.normalize("NFC", path)


def parse_crate_file(crate_path: Path) -> list[str]:
    """Parse a Serato .crate file and return list of track paths.

    Crate format: entries are `ptrk` chunks with UTF-16BE paths.
    """
    paths = []
    try:
        data = crate_path.read_bytes()
    except OSError:
        return paths

    pos = 0
    while pos < len(data) - 8:
        chunk_type = data[pos:pos+4]
        if len(data) < pos + 8:
            break
        chunk_len = struct.unpack(">I", data[pos+4:pos+8])[0]
        pos += 8

        if chunk_type == b"ptrk":
            try:
                path_bytes = data[pos:pos+chunk_len]
                path_str = path_bytes.decode("utf-16-be").rstrip("\x00")
                paths.append(normalize_path(path_str))
            except (UnicodeDecodeError, ValueError):
                pass

        pos += chunk_len

    return paths


def load_protected_paths(serato_dir: Path) -> set[str]:
    """Load all paths from protected crates."""
    protected = set()

    subcrates_dir = serato_dir / "Subcrates"
    if not subcrates_dir.is_dir():
        return protected

    for crate_file in subcrates_dir.glob("*.crate"):
        crate_name = crate_file.stem

        is_protected = any(
            crate_name.startswith(prefix.rstrip("/")) or
            crate_name == prefix.rstrip("/")
            for prefix in PROTECTED_CRATE_PREFIXES
        )

        if "Sets" in crate_name or "Perma" in crate_name or "Produced" in crate_name:
            is_protected = True

        if is_protected:
            for track_path in parse_crate_file(crate_file):
                protected.add(track_path)

    return protected


def check_protection(
    track: TrackTags,
    *,
    protected_paths: set[str] | None = None,
    track_relative_path: str | None = None,
) -> ProtectionStatus:
    """Check if a track is protected from modification.

    Args:
        track: Parsed track tags
        protected_paths: Set of paths from protected crates (NFC-normalized)
        track_relative_path: Path relative to library root for crate matching

    Returns:
        ProtectionStatus with reasons if protected
    """
    reasons = []
    can_replace_mik = False

    if track.error:
        reasons.append(f"tag error: {track.error}")

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

    if protected_paths and track_relative_path:
        normalized = normalize_path(track_relative_path)
        if normalized in protected_paths:
            reasons.append("in protected crate")

        for pp in protected_paths:
            if normalized.endswith(pp) or pp.endswith(normalized):
                reasons.append("in protected crate")
                break

    return ProtectionStatus(
        protected=len(reasons) > 0,
        reasons=reasons,
        can_replace_mik=can_replace_mik and len(reasons) == 0,
    )


def check_grid_protection(
    track: TrackTags,
    *,
    protected_paths: set[str] | None = None,
    track_relative_path: str | None = None,
) -> ProtectionStatus:
    """Check if a track's grid is protected from modification.

    Grids have stricter protection than cues:
    - All cue protection reasons apply
    - Additionally protected if track has ANY cues (even MIK)
    """
    base_status = check_protection(
        track,
        protected_paths=protected_paths,
        track_relative_path=track_relative_path,
    )

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
    protected_paths: set[str] | None = None,
    track_relative_path: str | None = None,
) -> CueWriteDecision:
    """Decide whether to write cues to a track.

    Args:
        track: Parsed track tags
        replace_mik: Whether --replace-mik flag is set
        protected_paths: Paths from protected crates
        track_relative_path: Relative path for crate matching

    Returns:
        CueWriteDecision with action and reasons
    """
    protection = check_protection(
        track,
        protected_paths=protected_paths,
        track_relative_path=track_relative_path,
    )

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
