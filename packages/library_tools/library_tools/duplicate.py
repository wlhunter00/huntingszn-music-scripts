"""Find duplicate tracks in DJ Spotify library by artist tag and delete extras."""

from __future__ import annotations

import argparse
from pathlib import Path

from mutagen import File

from config.paths import DJ_SPOTIFY


def find_duplicates(library: Path) -> list[tuple[Path, Path]]:
    """Return pairs (keep, delete) for duplicate artist tags."""
    by_artist: dict[str, Path] = {}
    to_delete: list[tuple[Path, Path]] = []
    for path in sorted(library.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".mp3", ".flac", ".m4a"}:
            continue
        audio = File(path, easy=True)
        if audio is None:
            continue
        artist = (audio.get("artist") or [None])[0]
        if not artist:
            continue
        key = artist.strip().lower()
        if key in by_artist:
            to_delete.append((by_artist[key], path))
        else:
            by_artist[key] = path
    return to_delete


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove duplicate artist entries in DJ library.")
    parser.add_argument("--library", type=Path, default=DJ_SPOTIFY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.library.is_dir():
        raise SystemExit(f"Not a directory: {args.library}")

    pairs = find_duplicates(args.library)
    if not pairs:
        print("No duplicates found.")
        return

    for keep, dup in pairs:
        print(f"{'[dry-run] ' if args.dry_run else ''}delete {dup.name} (keep {keep.name}, artist match)")
        if not args.dry_run:
            dup.unlink()
    print(f"{'Would remove' if args.dry_run else 'Removed'} {len(pairs)} file(s).")


if __name__ == "__main__":
    main()
