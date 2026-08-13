"""Normalize filenames for Platinum Notes (flip/remix naming conventions)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from library_tools.known_artists import is_known_artist

REMIX_MARKERS = re.compile(
    r"\b(?:flip|bootleg|remix|edit|mashup|vip|re-?up)\b",
    re.IGNORECASE,
)


def _strip_noise_phrase(text: str, phrase: str) -> str:
    text = re.sub(rf"[\[\(]\s*{phrase}\s*[\]\)]", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"(?<!\w){phrase}(?!\w)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    return text


def strip_title_noise(text: str) -> str:
    """Remove promo tags like 'final' and 'free dl' from titles/filenames."""
    text = _strip_noise_phrase(text, r"final")
    text = _strip_noise_phrase(text, r"free\s*dl")
    return normalize_parentheses(text.strip(" -"))


def strip_final(text: str) -> str:
    """Backward-compatible alias for strip_title_noise."""
    return strip_title_noise(text)


def normalize_parentheses(text: str) -> str:
    """Collapse doubled parens and trim whitespace inside them."""
    while "((" in text:
        text = text.replace("((", "(")
    while "))" in text:
        text = text.replace("))", ")")
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s+", "(", text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_stem(stem: str, *, flip_style: bool = False) -> str:
    """Return a Platinum Notes-friendly filename stem."""
    stem = stem.strip()

    # Cry Me a River(BLOOMx -> Cry Me a River (BLOOMx
    stem = re.sub(r"(?<!\()\w\(", lambda m: f"{m.group(0)[:-1]} (", stem)

    stem = strip_title_noise(stem)

    # Ampersands often break older Windows audio tools.
    stem = stem.replace(" & ", " and ")

    if " - " in stem:
        artist, rest = stem.split(" - ", 1)
        artist = re.sub(r",\s*", " x ", artist.strip())
        stem = f"{artist} - {rest.strip()}"

    if flip_style and " - " in stem and REMIX_MARKERS.search(stem):
        artist, rest = stem.split(" - ", 1)
        artist = artist.strip()
        if (
            not _keep_producer_prefix(artist, rest.strip())
            and not is_known_artist(artist)
        ):
            stem = rest.strip()

    return normalize_parentheses(stem)


def _keep_producer_prefix(artist: str, rest: str) -> bool:
    """Check if producer prefix should be kept.

    Producer flips like TYNAN - SONG FLIP keep the prefix.
    Retail Artist - Title (X FLIP) do not.
    """
    if not re.search(r"\bflip\b", rest, re.IGNORECASE):
        return False
    if re.search(r"\([^)]*\bflip\b", rest, re.IGNORECASE):
        return False
    words = artist.split()
    if len(words) > 3:
        return False
    return artist.isupper() or len(words) == 1


def rename_tree(root: Path, *, dry_run: bool, flip_style: bool) -> tuple[int, int]:
    renamed = 0
    skipped = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".wav", ".mp3", ".aiff", ".aif", ".flac"}:
            continue

        new_stem = sanitize_stem(path.stem, flip_style=flip_style)
        if new_stem == path.stem:
            skipped += 1
            continue

        target = path.with_name(new_stem + path.suffix)
        if target.exists() and target != path:
            print(f"skip (exists): {path.name} -> {target.name}")
            skipped += 1
            continue

        print(f"{'[dry-run] ' if dry_run else ''}{path.name}")
        print(f"       -> {target.name}")
        if not dry_run:
            path.rename(target)
        renamed += 1

    return renamed, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fix common Platinum Notes filename issues: spacing before '(', "
            "remove 'final' / 'free dl', '&' -> 'and', commas -> 'x'. "
            "Use --flip-style to also drop retail artist prefixes on flips."
        )
    )
    parser.add_argument("root", type=Path, help="Folder containing audio files")
    parser.add_argument(
        "--flip-style",
        action="store_true",
        help="Drop retail artist prefix on flips (Artist - Song (Flip) -> Song (Flip))",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")

    renamed, skipped = rename_tree(args.root, dry_run=args.dry_run, flip_style=args.flip_style)
    print(f"Done: {renamed} renamed, {skipped} unchanged.")


if __name__ == "__main__":
    main()
