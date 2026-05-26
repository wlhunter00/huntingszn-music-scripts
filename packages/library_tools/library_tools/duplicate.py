"""Find and remove duplicate audio files in the DJ Spotify library.

Detects (1)/(2) filename copies and same-basename/different-extension pairs,
confirming duplicates via matching artist tags before deletion.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from mutagen import File

from config.paths import DJ_SPOTIFY

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg"}


def collect_audio_files(library: Path) -> dict[str, Path]:
    """Map basename -> full path for all audio files under library."""
    files: dict[str, Path] = {}
    for dirpath, _, filenames in os.walk(library):
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            files[name] = Path(dirpath) / name
    return files


def get_artist(path: Path) -> str | None:
    try:
        audio = File(path, easy=True)
        if audio is None:
            print(f"Unsupported file format or no metadata: {path}")
            return None
        artist = (audio.get("artist") or [None])[0]
        return artist
    except Exception as exc:
        print(f"Error processing {path}: {exc}")
        return None


def artists_match(path_a: Path, path_b: Path) -> bool:
    artist_a = get_artist(path_a)
    artist_b = get_artist(path_b)
    if not artist_a or not artist_b:
        return False
    return artist_a.strip().lower() == artist_b.strip().lower()


def find_numbered_copy_duplicates(files: dict[str, Path]) -> list[tuple[Path, Path]]:
    """Find (1)/(2) copies where the base filename also exists."""
    pairs: list[tuple[Path, Path]] = []
    names = set(files)
    for name, dup_path in files.items():
        if "(1)" not in name and "(2)" not in name:
            continue
        existing_name = name.replace("(2)", "").replace("(1)", "")
        if existing_name in names:
            pairs.append((files[existing_name], dup_path))
    return pairs


def find_extension_duplicates(files: dict[str, Path]) -> list[tuple[Path, Path]]:
    """Find same basename with different extensions; keep first extension seen."""
    seen: dict[str, tuple[str, Path]] = {}
    pairs: list[tuple[Path, Path]] = []
    for name in sorted(files):
        stem, ext = os.path.splitext(name)
        if stem in seen:
            keep_ext, keep_path = seen[stem]
            if ext.lower() != keep_ext.lower():
                pairs.append((keep_path, files[name]))
        else:
            seen[stem] = (ext, files[name])
    return pairs


def find_duplicates(library: Path) -> list[tuple[Path, Path]]:
    files = collect_audio_files(library)
    pairs: list[tuple[Path, Path]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for keep, dup in find_numbered_copy_duplicates(files) + find_extension_duplicates(files):
        key = (str(keep), str(dup))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        pairs.append((keep, dup))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate files in DJ library (filename/extension dupes)."
    )
    parser.add_argument("--library", type=Path, default=DJ_SPOTIFY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.library.is_dir():
        raise SystemExit(f"Not a directory: {args.library}")

    candidates = find_duplicates(args.library)
    if not candidates:
        print("No duplicate candidates found.")
        return

    removed = 0
    for keep, dup in candidates:
        print(keep.name)
        if not artists_match(keep, dup):
            print(f"non-duplicate (artist mismatch): keep {keep.name}, skip {dup.name}")
            continue
        print(f"duplicate: delete {dup.name} (keep {keep.name})")
        print(f"{'[dry-run] ' if args.dry_run else ''}{dup} -> deleted")
        if not args.dry_run:
            dup.unlink()
        removed += 1

    print(f"{'Would remove' if args.dry_run else 'Removed'} {removed} file(s).")


if __name__ == "__main__":
    main()
