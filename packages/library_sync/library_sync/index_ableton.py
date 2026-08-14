"""Index Ableton projects from {DRIVE}/Ableton/**/*.als.

Skips **/Backup/** directories.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from library_sync.db import (
    AbletonProject,
    LibraryDB,
    compute_track_id,
    is_present_and_unchanged,
    utc_now_iso,
)


def _to_posix_relative(path: Path, root: Path) -> str:
    """Convert path to POSIX-style relative path string."""
    try:
        rel = path.relative_to(root)
        return str(PurePosixPath(rel))
    except ValueError:
        return str(PurePosixPath(path))


def _get_folder(relative_path: str) -> str:
    """Get top-level folder under Ableton/ from relative path."""
    parts = relative_path.split("/")
    if len(parts) >= 2 and parts[0] == "Ableton":
        return parts[1]
    return ""


def _get_kind(relative_path: str) -> str:
    """Template if any path component contains 'template' (case-insensitive)."""
    parts = relative_path.replace("\\", "/").split("/")
    if any("template" in part.lower() for part in parts):
        return "template"
    return "project"


def scan_ableton_projects(
    ableton_root: Path,
    drive_root: Path,
) -> list[tuple[Path, str]]:
    """Scan for .als files under Ableton/, skipping Backup folders.

    Args:
        ableton_root: Path to Ableton directory
        drive_root: Drive root for relative path calculation

    Returns:
        List of (file_path, relative_path) tuples
    """
    files: list[tuple[Path, str]] = []

    if not ableton_root.exists():
        return files

    for dirpath, dirnames, filenames in os.walk(ableton_root):
        dirnames[:] = [
            d for d in dirnames if d.lower() != "backup" and not d.startswith("._")
        ]

        for filename in filenames:
            if filename.startswith("._"):
                continue
            if not filename.lower().endswith(".als"):
                continue

            filepath = Path(dirpath) / filename
            relative_path = _to_posix_relative(filepath, drive_root)
            files.append((filepath, relative_path))

    return files


def index_ableton(
    db: LibraryDB,
    drive_root: Path,
    *,
    dry_run: bool = False,
    progress_callback: object = None,
) -> dict[str, int]:
    """Index Ableton projects into the database.

    Args:
        db: Database connection
        drive_root: Root of the music drive
        dry_run: If True, don't write to database
        progress_callback: Optional callback(action, path, project) for progress

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

    ableton_root = drive_root / "Ableton"
    if not ableton_root.exists():
        return stats

    existing_paths = db.get_all_present_ableton_paths() if not dry_run else set()
    seen_paths: set[str] = set()

    files = scan_ableton_projects(ableton_root, drive_root)

    def _index_one() -> None:
        nonlocal stats
        for filepath, relative_path in files:
            stats["scanned"] += 1
            seen_paths.add(relative_path)

            try:
                file_stat = filepath.stat()
                file_size = file_stat.st_size
                mtime = file_stat.st_mtime
            except OSError:
                continue

            existing_size, existing_mtime, existing_status = db.get_ableton_for_update_check(
                relative_path
            )
            if is_present_and_unchanged(
                existing_size, existing_mtime, existing_status, file_size, mtime
            ):
                stats["skipped"] += 1
                if progress_callback:
                    progress_callback("skip", relative_path, None)
                continue

            name = filepath.stem
            folder = _get_folder(relative_path)
            kind = _get_kind(relative_path)

            project = AbletonProject(
                id=compute_track_id(relative_path, file_size),
                relative_path=relative_path,
                name=name,
                folder=folder,
                kind=kind,
                file_size=file_size,
                mtime=mtime,
                updated_at=utc_now_iso(),
                status="present",
            )

            if existing_size is not None:
                stats["updated"] += 1
                action = "update"
            else:
                stats["added"] += 1
                action = "add"

            if progress_callback:
                progress_callback(action, relative_path, project)

            if not dry_run:
                db.upsert_ableton(project)

        if not dry_run:
            missing_paths = existing_paths - seen_paths
            if missing_paths:
                stats["missing"] = db.mark_ableton_missing(missing_paths)

    if dry_run:
        _index_one()
    else:
        with db.transaction():
            _index_one()

    return stats
