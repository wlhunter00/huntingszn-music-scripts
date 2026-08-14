"""Index stem folders from Stem Splitting/stem-output.

Scans {DRIVE}/Stem Splitting/stem-output/{model}/{song}/ folders.
Creates one row per song folder (not per wav file).

Accepts both Demucs-style names (vocals.wav) and stem_split output
({title}_vocals.wav, {title}_drums.wav, …).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from library_sync.db import LibraryDB, Stem, compute_track_id, utc_now_iso

# Check longer tokens first so no_vocals is not classified as vocals.
STEM_KINDS = ("no_vocals", "vocals", "drums", "bass", "other")
_DRUMS_COPY_SUFFIXES = ("_drums_2.wav", "_drums_3.wav", "_drums_4.wav")


def _to_posix_relative(path: Path, root: Path) -> str:
    """Convert path to POSIX-style relative path string."""
    try:
        rel = path.relative_to(root)
        return str(PurePosixPath(rel))
    except ValueError:
        return str(PurePosixPath(path))


def _stem_kind(filename: str) -> str | None:
    """Return stem kind for a wav filename, or None if it is not a stem."""
    lower = filename.lower()
    if not lower.endswith(".wav"):
        return None
    if any(lower.endswith(suffix) for suffix in _DRUMS_COPY_SUFFIXES):
        return None
    if lower == "drums_2.wav" or lower == "drums_3.wav" or lower == "drums_4.wav":
        return None
    for kind in STEM_KINDS:
        if lower == f"{kind}.wav" or lower.endswith(f"_{kind}.wav"):
            return kind
    return None


def stem_files_in_folder(folder: Path) -> dict[str, Path]:
    """Map stem kind → file path for a song folder."""
    found: dict[str, Path] = {}
    try:
        entries = list(folder.iterdir())
    except OSError:
        return found
    for path in entries:
        if not path.is_file():
            continue
        kind = _stem_kind(path.name)
        if kind and kind not in found:
            found[kind] = path
    return found


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

            if not stem_files_in_folder(song_dir):
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

    If stem-output is missing, do not mark existing rows missing — the tree
    was not scanned.

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

    def _index_one() -> None:
        nonlocal stats
        for folder_path, relative_path, song_name, model in folders:
            stats["scanned"] += 1
            seen_paths.add(relative_path)

            stem_map = stem_files_in_folder(folder_path)
            total_size = 0
            latest_mtime = 0.0
            for stem_path in stem_map.values():
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
                has_vocals=int("vocals" in stem_map),
                has_drums=int("drums" in stem_map),
                has_bass=int("bass" in stem_map),
                has_other=int("other" in stem_map),
                has_no_vocals=int("no_vocals" in stem_map),
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

    if dry_run:
        _index_one()
    else:
        with db.transaction():
            _index_one()

    return stats
