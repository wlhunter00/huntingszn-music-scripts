"""Parse Artist - Title filenames and write ID3 metadata (EasyID3)."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from mutagen import File
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

from config.paths import PLATINUM_NOTES

KNOWN_ARTISTS = [
    "baby keem",
    "kendrick lamar",
    "daft punk",
    "a ap rocky",
    "a ap ferg",
    "jay z",
    "kanye west",
    "kid cudi",
    "the black eyed peas",
    "rae sremmurd",
    "city girls",
    "megan thee stallion",
    "sofi tukker",
    "carly rae jepsen",
]

FEATURE_PATTERNS = [
    r"\bft\.?\b",
    r"\bfeat\.?\b",
    r"\bfeatures?\b",
    r"\bfeaturing\b",
    r"\bwith\b",
]
REMIX_PATTERNS = [
    r"\bremix\b",
    r"\bedit\b",
    r"\bflip\b",
    r"\bbootleg\b",
    r"\breboot\b",
    r"\bversion\b",
    r"\bvip\b",
    r"\bmashup\b",
]
COLLAB_INDICATORS = [" x ", " vs ", " & ", " and "]


def parse_song_info(filename: str) -> dict[str, str] | None:
    name = re.sub(r"_PN$", "", os.path.splitext(filename)[0], flags=re.IGNORECASE)
    name = name.replace("-", " ")

    for artist in KNOWN_ARTISTS:
        if artist in name.lower():
            pass  # reserved for future smarter parsing

    if " - " not in name:
        return None

    part1, part2 = name.split(" - ", 1)
    if "(Evalution" in part1:
        title, artists = part1.strip(), part2.strip()
    else:
        artists, title = part1.strip(), part2.strip()

    if not artists or not title:
        return None
    return {"title": title, "contributing_artists": artists}


def process_folder(root: Path, *, force: bool, dry_run: bool) -> None:
    stats = {"total": 0, "has_meta": 0, "updated": 0, "unparsed": 0}
    for dirpath, _, files in os.walk(root):
        for filename in files:
            if not filename.lower().endswith((".mp3", ".m4a", ".flac")):
                continue
            stats["total"] += 1
            filepath = Path(dirpath) / filename
            try:
                audio = EasyID3(filepath)
                if not force and "title" in audio and "artist" in audio:
                    stats["has_meta"] += 1
                    continue
            except (ID3NoHeaderError, Exception):
                audio = EasyID3()
                audio.filename = filepath

            info = parse_song_info(filename)
            if not info:
                print(f"unparsed: {filepath}")
                stats["unparsed"] += 1
                continue

            print(f"{'[dry-run] ' if dry_run else ''}update: {filename} -> {info['title']} / {info['contributing_artists']}")
            if not dry_run:
                audio["title"] = info["title"]
                audio["artist"] = info["contributing_artists"]
                audio.save(filepath)
            stats["updated"] += 1

    print(
        f"total={stats['total']} already_tagged={stats['has_meta']} "
        f"updated={stats['updated']} unparsed={stats['unparsed']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write ID3 tags from filenames.")
    parser.add_argument("--root", type=Path, default=PLATINUM_NOTES)
    parser.add_argument("--force", action="store_true", help="Update even if tags exist")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")
    process_folder(args.root, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
