"""Write ID3 title/artist from filenames, using folder-specific rules."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

from config.paths import PLATINUM_NOTES

AUDIO_SUFFIXES = {".mp3", ".m4a", ".flac", ".wav"}

# Folder names under Platinum Notes (case-insensitive).
MODE_DASH = "dash_or_title"  # first " - " split; otherwise title-only
MODE_TITLE_KEEP_ARTIST = "title_keep_artist"  # whole stem is title; keep existing artist
FOLDER_MODES = {
    "make it bump": MODE_DASH,
    "spotify": MODE_DASH,
    "huntingszn": MODE_TITLE_KEEP_ARTIST,
}


def infer_mode(path: Path, root: Path | None = None) -> str:
    """Pick a tagging mode from the file's parent folders under ``root``.

    Walks from the file upward and stops at ``root`` so a volume named
    HuntingSzn is not treated as the huntingszn library folder.
    """
    current = path.parent
    root_resolved = root.resolve() if root is not None else None
    while True:
        name = current.name.lower()
        mode = FOLDER_MODES.get(name)
        if mode and current.parent.name.lower() != "volumes":
            return mode
        if root_resolved is not None and current.resolve() == root_resolved:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return MODE_DASH


def strip_pn_suffix(stem: str) -> str:
    return re.sub(r"_PN$", "", stem, flags=re.IGNORECASE)


def desired_from_stem(stem: str, mode: str) -> tuple[str, str | None]:
    """Return (title, artist_or_none). None artist means do not take artist from the filename."""
    stem = strip_pn_suffix(stem)
    if mode == MODE_TITLE_KEEP_ARTIST:
        return stem, None
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        artist = artist.strip()
        title = title.strip()
        return title, artist or None
    return stem, None


def format_existing_artist(value: str) -> str:
    """Keep one artist string; turn slash-joined lists into ' x ' collabs."""
    value = value.strip()
    if "/" in value and " x " not in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        if len(parts) > 1:
            return " x ".join(parts)
    return value


def artist_from_tags(audio: EasyID3) -> str:
    values = [str(v).strip() for v in (audio.get("artist") or []) if str(v).strip()]
    if not values:
        return ""
    if len(values) > 1:
        return " x ".join(values)
    return format_existing_artist(values[0])


def title_from_tags(audio: EasyID3) -> str:
    values = audio.get("title") or []
    return str(values[0]).strip() if values else ""


def parse_song_info(
    filename: str, *, mode: str = MODE_DASH
) -> dict[str, str | list[str]]:
    """Filename → title/artist. Artist is a single string (no x/vs splitting)."""
    title, artist = desired_from_stem(Path(filename).stem, mode)
    return {
        "title": title,
        "contributing_artists": [artist] if artist else [],
    }


def process_folder(root: Path, *, force: bool, dry_run: bool) -> None:
    stats = {"total": 0, "already_ok": 0, "updated": 0, "skipped": 0, "errors": 0}
    for dirpath, _, files in os.walk(root):
        for filename in files:
            if filename.startswith("._"):
                stats["skipped"] += 1
                continue
            suffix = Path(filename).suffix.lower()
            if suffix not in AUDIO_SUFFIXES:
                continue
            stats["total"] += 1
            filepath = Path(dirpath) / filename
            mode = infer_mode(filepath, root)
            desired_title, artist_from_name = desired_from_stem(filepath.stem, mode)

            try:
                audio = EasyID3(filepath)
            except (ID3NoHeaderError, Exception):
                audio = EasyID3()
                audio.filename = filepath

            existing_title = title_from_tags(audio)
            existing_artist = artist_from_tags(audio)
            if artist_from_name:
                new_artist = artist_from_name
            elif existing_artist:
                new_artist = format_existing_artist(existing_artist)
            else:
                new_artist = ""

            already_ok = existing_title == desired_title and existing_artist == new_artist
            if already_ok and not force:
                stats["already_ok"] += 1
                continue

            artist_display = new_artist or "(keep empty)"
            print(
                f"{'[dry-run] ' if dry_run else ''}update: {filename} -> "
                f"{desired_title} / {artist_display}"
            )
            if not dry_run:
                try:
                    audio["title"] = desired_title
                    if new_artist:
                        audio["artist"] = new_artist
                    elif "artist" in audio:
                        # Title-only filename with no existing artist: leave artist absent.
                        del audio["artist"]
                    audio.save(filepath)
                except Exception as exc:
                    print(f"error: {filepath}: {exc}")
                    stats["errors"] += 1
                    continue
            stats["updated"] += 1

    print(
        f"total={stats['total']} already_ok={stats['already_ok']} "
        f"updated={stats['updated']} skipped_sidecars={stats['skipped']} "
        f"errors={stats['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Write ID3 title/artist from filenames. "
            "make it bump + spotify: split on the first ' - ' and keep both sides unchanged. "
            "huntingszn: title is the whole filename; existing artist is kept. "
            "Does not split collabs or rewrite title case."
        )
    )
    parser.add_argument("--root", type=Path, default=PLATINUM_NOTES)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite tags even when they already match the filename",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")
    process_folder(args.root, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
