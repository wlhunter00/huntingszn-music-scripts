"""Query library tracks with harmonic mixing rules.

Match rules:
- Camelot ±1 including relative major/minor (e.g., 8A matches 7A, 8A, 9A, 8B)
- BPM ±6 of target, AND also ±6 of 0.5× and 2× (half-time/double-time)
- Null bpm/key rows do not match a keyed query
"""

from __future__ import annotations

from library_sync.camelot import get_compatible_keys, normalize_camelot
from library_sync.db import LibraryDB, Track


def bpm_matches(target: float, candidate: float | None, tolerance: float = 6.0) -> bool:
    """Check if candidate BPM matches target within tolerance.

    Matches if candidate is within ±tolerance of:
    - target
    - target × 0.5 (half-time)
    - target × 2 (double-time)
    """
    if candidate is None:
        return False

    if abs(candidate - target) <= tolerance:
        return True

    if abs(candidate - target * 0.5) <= tolerance:
        return True

    if abs(candidate - target * 2) <= tolerance:
        return True

    return False


def query_tracks(
    db: LibraryDB,
    *,
    camelot: str | None = None,
    bpm: float | None = None,
    bpm_tolerance: float = 6.0,
    text_search: str | None = None,
    role: str | None = None,
    limit: int | None = None,
) -> list[Track]:
    """Query tracks with harmonic mixing rules.

    Args:
        db: Database connection
        camelot: Target Camelot key (matches ±1 and relative)
        bpm: Target BPM (matches ±6 including half/double time)
        bpm_tolerance: BPM tolerance (default: 6)
        text_search: Case-insensitive search in artist/title/filename
        role: Filter by role (vocal, drop, unknown)
        limit: Maximum results

    Returns:
        List of matching tracks
    """
    camelot_keys: set[str] | None = None
    if camelot:
        normalized = normalize_camelot(camelot)
        if normalized:
            camelot_keys = get_compatible_keys(normalized)
        else:
            return []

    if bpm is not None:
        bpm_min = min(bpm - bpm_tolerance, bpm * 0.5 - bpm_tolerance, bpm * 2 - bpm_tolerance)
        bpm_max = max(bpm + bpm_tolerance, bpm * 0.5 + bpm_tolerance, bpm * 2 + bpm_tolerance)
        bpm_range = (bpm_min, bpm_max)
    else:
        bpm_range = None

    tracks = db.query_tracks(
        camelot_keys=camelot_keys,
        bpm_range=bpm_range,
        text_search=text_search,
        role=role,
        limit=None,
    )

    if bpm is not None:
        tracks = [t for t in tracks if bpm_matches(bpm, t.bpm, bpm_tolerance)]

    if limit:
        tracks = tracks[:limit]

    return tracks


def format_tracks_table(tracks: list[Track]) -> str:
    """Format tracks as a readable text table."""
    if not tracks:
        return "No matching tracks."

    lines = []
    header = f"{'Artist':<30} {'Title':<40} {'BPM':>6} {'Key':>4} {'Source':<15}"
    lines.append(header)
    lines.append("-" * len(header))

    for track in tracks:
        artist = (track.artist or "")[:30]
        title = (track.title or track.filename)[:40]
        bpm = f"{track.bpm:.0f}" if track.bpm else ""
        key = track.camelot_key or ""
        source = (track.source_root or "")[:15]
        lines.append(f"{artist:<30} {title:<40} {bpm:>6} {key:>4} {source:<15}")

    return "\n".join(lines)


def tracks_to_json(tracks: list[Track]) -> list[dict]:
    """Convert tracks to JSON-serializable list."""
    return [
        {
            "id": t.id,
            "relative_path": t.relative_path,
            "filename": t.filename,
            "artist": t.artist,
            "title": t.title,
            "album": t.album,
            "genre": t.genre,
            "duration_sec": t.duration_sec,
            "bpm": t.bpm,
            "key": t.key,
            "camelot_key": t.camelot_key,
            "audio_object_key": t.audio_object_key,
            "role": t.role,
            "source_root": t.source_root,
        }
        for t in tracks
    ]
