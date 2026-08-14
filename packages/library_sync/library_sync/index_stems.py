"""Index stem folders from Stem Splitting/stem-output.

Scans {DRIVE}/Stem Splitting/stem-output/{model}/{song}/ folders.
Creates one row per song folder (not per wav file).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from library_sync.db import LibraryDB, Stem, compute_track_id, utc_now_iso

STEM_FILES = frozenset({"vocals.wav", "drums.wav", "bass.wav", "other.wav", "no_vocals.wav"})


def _to_posix_relative(path: Path, root: Path) -> str:
    """Convert path to POSIX-style relative path string."""
    try:
        rel = path.relative_to(root)
        return str(PurePosixPath(rel))
    except ValueError:
        return str(PurePosixPath(path))


def scan_stem_folders(
    stem_output_root: Path,
    drive_root: Path,
) -> list[tuple[Path, str, str, str]]:
    """Scan for stem song folders.

    Args:
        stem_output_root: Path to stem-output directory
        drive_root: Drive root for relative path calculation

    Returns:
        List of (folder_path, relative_path, song_name, model) tuples
    """
    folders: list[tuple[Path, str, str, str]] = []

    if not stem_output_root.exists():
        return folders

    for model_dir in stem_output_root.iterdir():
        if not model_dir.is_dir():
            continue
        model_name = model_dir.name

        for song_dir in model_dir.iterdir():
            if not song_dir.is_dir():
                continue

            has_any_stem = any((song_dir / stem).exists() for stem in STEM_FILES)
            if not has_any_stem:
                continue

            relative_path = _to_posix_relative(song_dir, drive_root)
            folders.append((song_dir, relative_path, song_dir.name, model_name))

    return folders


def index_stems(
    db: LibraryDB,
    drive_root: Path,
    *,
    dry_run: bool = False,
    progress_callback: object = None,
) -> dict[str, int]:
    """Index stem folders into the database.

    Args:
        db: Database connection
        drive_root: Root of the music drive
        dry_run: If True, don't write to database
        progress_callback: Optional callback(action, path, stem) for progress

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

    stem_output_root = drive_root / "Stem Splitting" / "stem-output"
    if not stem_output_root.exists():
        return stats

    existing_paths = db.get_all_present_stem_paths() if not dry_run else set()
    seen_paths: set[str] = set()

    folders = scan_stem_folders(stem_output_root, drive_root)

    for folder_path, relative_path, song_name, model in folders:
        stats["scanned"] += 1
        seen_paths.add(relative_path)

        total_size = 0
        latest_mtime = 0.0

        for stem_file in STEM_FILES:
            stem_path = folder_path / stem_file
            if stem_path.exists():
                try:
                    st = stem_path.stat()
                    total_size += st.st_size
                    latest_mtime = max(latest_mtime, st.st_mtime)
                except OSError:
                    pass

        existing_size, existing_mtime = db.get_stem_for_update_check(relative_path)
        if (
            existing_size is not None
            and existing_size == total_size
            and existing_mtime is not None
            and existing_mtime == latest_mtime
        ):
            stats["skipped"] += 1
            if progress_callback:
                progress_callback("skip", relative_path, None)
            continue

        stem = Stem(
            id=compute_track_id(relative_path, total_size),
            relative_path=relative_path,
            song_name=song_name,
            model=model,
            has_vocals=int((folder_path / "vocals.wav").exists()),
            has_drums=int((folder_path / "drums.wav").exists()),
            has_bass=int((folder_path / "bass.wav").exists()),
            has_other=int((folder_path / "other.wav").exists()),
            has_no_vocals=int((folder_path / "no_vocals.wav").exists()),
            file_size=total_size,
            mtime=latest_mtime,
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
            progress_callback(action, relative_path, stem)

        if not dry_run:
            db.upsert_stem(stem)

    if not dry_run:
        missing_paths = existing_paths - seen_paths
        if missing_paths:
            stats["missing"] = db.mark_stems_missing(missing_paths)

    return stats
