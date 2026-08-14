"""Index audio files from the music drive into SQLite.

Catalog roots (only these are indexed):
- {DRIVE}/DJ Music/
- {DRIVE}/Platnium Notes/

Skipped:
- Producing Sounds, Ableton, Instruments, serum / serum presets
- Stem Splitting/stem-output (do not catalog as library tracks)
- macOS AppleDouble files (._*) and .DS_Store
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from library_sync.db import (
    LibraryDB,
    Track,
    compute_track_id,
    is_present_and_unchanged,
    utc_now_iso,
)
from library_sync.tags import TrackTags, parse_filename_artist_title, read_tags

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a"})

SKIP_DIRS = frozenset(
    {
        "stem-output",
        "Producing Sounds",
        "Ableton",
        "Instruments",
        "serum presets",
        "serum",
    }
)
_SKIP_DIRS_LOWER = frozenset(name.lower() for name in SKIP_DIRS)

_NO_VOCAL_ROLE = re.compile(
    r"\b(no[\s_\-]?vocals?|instrumental|inst)\b", re.IGNORECASE
)
_VOCAL_ROLE = re.compile(r"\b(acapella|acappella|acap|vocal|vocals)\b", re.IGNORECASE)
_DROP_ROLE = re.compile(r"\bdrop\b", re.IGNORECASE)


def _should_skip_file(name: str) -> bool:
    """Check if file should be skipped (AppleDouble, DS_Store, etc.)."""
    if name.startswith("._"):
        return True
    if name == ".DS_Store":
        return True
    return False


def _should_skip_dir(name: str) -> bool:
    """Check if directory should be skipped (case-insensitive)."""
    return name.lower() in _SKIP_DIRS_LOWER


def _is_audio_file(path: Path) -> bool:
    """Check if file is an audio file we index."""
    return path.suffix.lower() in AUDIO_EXTENSIONS


def _to_posix_relative(path: Path, root: Path) -> str:
    """Convert path to POSIX-style relative path string."""
    try:
        rel = path.relative_to(root)
        return str(PurePosixPath(rel))
    except ValueError:
        return str(PurePosixPath(path))


def _get_source_root(relative_path: str) -> str:
    """Determine source root from relative path."""
    parts = relative_path.split("/")
    if parts:
        first = parts[0]
        if first == "DJ Music":
            return "DJ Music"
        if first == "Platnium Notes":
            return "Platnium Notes"
    return ""


def infer_role(filename: str, relative_path: str = "") -> str:
    """Infer vocal/drop/unknown from filename and path."""
    blob = f"{filename} {relative_path}"
    if _NO_VOCAL_ROLE.search(blob):
        return "drop"
    if _VOCAL_ROLE.search(blob):
        return "vocal"
    if _DROP_ROLE.search(blob):
        return "drop"
    return "unknown"


def _path_under_prefix(relative_path: str, prefix: str) -> bool:
    return relative_path == prefix or relative_path.startswith(prefix + "/")


def scan_directory(
    root: Path,
    drive_root: Path,
    *,
    callback: object = None,
) -> list[tuple[Path, str]]:
    """Scan directory for audio files.

    Args:
        root: Directory to scan
        drive_root: Drive root for relative path calculation
        callback: Optional callback(path, relative_path) for progress

    Returns:
        List of (absolute_path, relative_path) tuples
    """
    files: list[tuple[Path, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not _should_skip_dir(d) and not d.startswith("._")
        ]

        for filename in filenames:
            if _should_skip_file(filename):
                continue

            filepath = Path(dirpath) / filename
            if not _is_audio_file(filepath):
                continue

            relative_path = _to_posix_relative(filepath, drive_root)
            files.append((filepath, relative_path))

            if callback:
                callback(filepath, relative_path)

    return files


def index_files(
    db: LibraryDB,
    drive_root: Path,
    index_roots: list[Path],
    *,
    dry_run: bool = False,
    progress_callback: object = None,
) -> dict[str, int]:
    """Index audio files into the database.

    Roots that do not exist are skipped and their existing rows are left
    unchanged (not marked missing).

    Args:
        db: Database connection
        drive_root: Root of the music drive
        index_roots: List of directories to index
        dry_run: If True, don't write to database
        progress_callback: Optional callback(action, path, track) for progress

    Returns:
        Dict with counts: scanned, added, updated, skipped, missing
    """
    stats = {
        "scanned": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "missing": 0,
    }

    existing_paths = db.get_all_present_paths() if not dry_run else set()
    seen_paths: set[str] = set()
    scanned_prefixes: list[str] = []

    def _index_one() -> None:
        nonlocal stats
        for index_root in index_roots:
            if not index_root.exists():
                continue

            scanned_prefixes.append(_to_posix_relative(index_root, drive_root))
            files = scan_directory(index_root, drive_root)

            for filepath, relative_path in files:
                stats["scanned"] += 1
                seen_paths.add(relative_path)

                try:
                    file_stat = filepath.stat()
                    file_size = file_stat.st_size
                    mtime = file_stat.st_mtime
                except OSError:
                    continue

                existing_size, existing_mtime, existing_status = db.get_track_for_update_check(
                    relative_path
                )
                if is_present_and_unchanged(
                    existing_size, existing_mtime, existing_status, file_size, mtime
                ):
                    stats["skipped"] += 1
                    if progress_callback:
                        progress_callback("skip", relative_path, None)
                    continue

                try:
                    tags = read_tags(filepath)
                except Exception:
                    tags = TrackTags()
                    artist, title = parse_filename_artist_title(filepath.name)
                    tags.artist = artist
                    tags.title = title

                track = Track(
                    id=compute_track_id(relative_path, file_size),
                    relative_path=relative_path,
                    filename=filepath.name,
                    artist=tags.artist,
                    title=tags.title,
                    album=tags.album,
                    genre=tags.genre,
                    duration_sec=tags.duration_sec,
                    bpm=tags.bpm,
                    key=tags.key,
                    camelot_key=tags.camelot_key,
                    file_size=file_size,
                    mtime=mtime,
                    audio_object_key=relative_path,
                    updated_at=utc_now_iso(),
                    role=infer_role(filepath.name, relative_path),
                    source_root=_get_source_root(relative_path),
                    status="present",
                )

                if existing_size is not None:
                    stats["updated"] += 1
                    action = "update"
                else:
                    stats["added"] += 1
                    action = "add"

                if progress_callback:
                    progress_callback(action, relative_path, track)

                if not dry_run:
                    db.upsert_track(track)

        if not dry_run and scanned_prefixes:
            eligible = {
                path
                for path in existing_paths
                if any(_path_under_prefix(path, prefix) for prefix in scanned_prefixes)
            }
            missing_paths = eligible - seen_paths
            if missing_paths:
                stats["missing"] = db.mark_missing(missing_paths)

    if dry_run:
        _index_one()
    else:
        with db.transaction():
            _index_one()

    return stats
