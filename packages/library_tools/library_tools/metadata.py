"""Parse Artist - Title filenames and write ID3 metadata (EasyID3)."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

from config.paths import PLATINUM_NOTES
from library_tools.known_artists import KNOWN_ARTISTS
from library_tools.pn_filename import normalize_parentheses, strip_title_noise

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
PARENTHETICAL_REMIX = re.compile(
    r"\([^)]*(?:remix|flip|bootleg|edit|mashup|vip|re-?up|version)[^)]*\)",
    re.IGNORECASE,
)


def title_case_preserve(text: str) -> str:
    words = text.split()
    return " ".join(
        word
        if word and word[0].isupper()
        else (word[0].upper() + word[1:] if word and word[0].isalpha() else word)
        for word in words
    )


def apply_file_namer_title_cleanup(title: str) -> str:
    """Strip trailing BPM/key and label brackets (from file-namer.py)."""
    title = re.sub(r"\s+[A-Ga-g]b?\s+\d+$", "", title)
    title = re.sub(r"\s+\d{1,2}[AB]\s+\d{2,3}$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\[[^\]]+\]\s*$", "", title)
    return title.strip()


def split_simple_artists(artist_part: str) -> list[str]:
    """Split artist string on vs/x/comma/& (from file-namer.py)."""
    parts = re.split(r" [Vv][Ss] ", artist_part)
    parts = [p for artist in parts for p in artist.split(" x ")]
    parts = [p for artist in parts for p in artist.split(",")]
    parts = [p for artist in parts for p in artist.split("&")]
    return [title_case_preserve(a.strip()) for a in parts if a.strip()]


def parse_song_info(filename: str) -> dict[str, str | list[str]] | None:
    """Parse song title and artists from filename."""
    name_without_ext = os.path.splitext(filename)[0]
    name_without_pn = re.sub(r"_PN$", "", name_without_ext, flags=re.IGNORECASE)

    artists: list[str] = []
    title = ""
    remix_info = ""

    if " - " not in name_without_pn:
        # No Artist - Title separator: use the whole filename as title, leave artist blank.
        title = name_without_pn.replace("-", " ")
        artists = []
    else:
        artist_part, title_part = name_without_pn.split(" - ", 1)
        artist_part = artist_part.strip()
        title_part = title_part.strip()
        title_with_spaces = title_part.replace("-", " ")

        lower_name = (artist_part + " " + title_part).lower()
        found_artists = []
        for artist in KNOWN_ARTISTS:
            if artist in lower_name:
                found_artists.append(artist)

        if "(Evalution" in artist_part:
            title = artist_part
            artists = split_simple_artists(title_part)
        elif found_artists:
            artists = [a.title() for a in found_artists]
            title = title_with_spaces
        else:
            artist_split = False
            for indicator in COLLAB_INDICATORS:
                if indicator.lower() in artist_part.lower():
                    split_artists = re.split(re.escape(indicator), artist_part, flags=re.IGNORECASE)
                    artists.extend([a.strip() for a in split_artists if a.strip()])
                    artist_split = True
                    break
            if not artist_split:
                artists = split_simple_artists(artist_part) or [artist_part]
            title = title_with_spaces

        for pattern in FEATURE_PATTERNS:
            feature_match = re.search(rf"{pattern}(.*?)($|\()", title, re.IGNORECASE)
            if feature_match:
                feature_artists = feature_match.group(1).strip()
                feature_split = False
                for indicator in COLLAB_INDICATORS:
                    if indicator.lower() in feature_artists.lower():
                        split_features = re.split(
                            re.escape(indicator), feature_artists, flags=re.IGNORECASE
                        )
                        artists.extend([a.strip() for a in split_features if a.strip()])
                        feature_split = True
                        break
                if not feature_split and feature_artists:
                    artists.append(feature_artists)
                title = re.sub(rf"{pattern}.*?($|\()", " ", title, flags=re.IGNORECASE).strip()
                break

        if not PARENTHETICAL_REMIX.search(title):
            for pattern in REMIX_PATTERNS:
                remix_match = re.search(rf"\b{pattern}\b", title, re.IGNORECASE)
                if remix_match:
                    remix_start = remix_match.start()
                    remix_prefix = ""
                    if remix_start > 0:
                        prefix_words = title[:remix_start].strip().split()
                        if prefix_words:
                            remix_prefix = prefix_words[-1]
                    remix_end = len(title)
                    for sep in [" - ", " | "]:
                        sep_pos = title.find(sep, remix_start)
                        if sep_pos != -1 and sep_pos < remix_end:
                            remix_end = sep_pos
                    remix_pattern = remix_match.group(0)
                    remix_suffix = title[remix_match.end() : remix_end].strip()
                    suffix_part = f" {remix_suffix}" if remix_suffix else ""
                    if remix_prefix:
                        remix_info = f"{remix_prefix} {remix_pattern}{suffix_part}"
                        title_words = title[:remix_start].strip().split()
                        if title_words:
                            title_words.pop()
                            title = " ".join(title_words) + " " + title[remix_end:].strip()
                    else:
                        remix_info = f"{remix_pattern}{suffix_part}"
                        title = title[:remix_start].strip() + " " + title[remix_end:].strip()
                    title = re.sub(r"\s+", " ", title).strip()
                    break

    cleaned_artists: list[str] = []
    for artist in artists:
        artist = re.sub(r"\([^)]*\)", "", artist).strip()
        for pattern in REMIX_PATTERNS:
            artist = re.sub(rf"\b{pattern}\b", "", artist, flags=re.IGNORECASE).strip()
        if artist:
            cleaned_artists.append(artist)

    title = apply_file_namer_title_cleanup(title.strip())

    if remix_info:
        remix_info = title_case_preserve(remix_info).strip()
        if remix_info and not re.search(r"\([^)]*\)", title):
            if remix_info.startswith("("):
                title = f"{title} {remix_info}"
            else:
                title = f"{title} ({remix_info})"

    title = normalize_parentheses(strip_title_noise(title.strip()))
    title = title_case_preserve(title)
    cleaned_artists = [title_case_preserve(a) for a in cleaned_artists]

    if not title or title.strip() == "()":
        title = "Unknown Title"

    return {"title": title, "contributing_artists": cleaned_artists}


def process_folder(root: Path, *, force: bool, dry_run: bool) -> None:
    stats = {"total": 0, "has_meta": 0, "updated": 0, "unparsed": 0}
    for dirpath, _, files in os.walk(root):
        for filename in files:
            if not filename.lower().endswith((".mp3", ".m4a", ".flac", ".wav")):
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

            artists = info["contributing_artists"]
            artist_display = ", ".join(artists) if artists else ""
            print(
                f"{'[dry-run] ' if dry_run else ''}update: {filename} -> "
                f"{info['title']}" + (f" / {artist_display}" if artist_display else "")
            )
            if not dry_run:
                audio["title"] = info["title"]
                if artists:
                    audio["artist"] = artists
                elif "artist" in audio:
                    del audio["artist"]
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
