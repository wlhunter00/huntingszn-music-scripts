"""Utility functions for slug generation and path handling."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug.

    Examples:
        >>> slugify("The Cure x Pray")
        'the-cure-x-pray'
        >>> slugify("Olivia Rodrigo: The Cure")
        'olivia-rodrigo-the-cure'
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def track_slug(track: str) -> str:
    """Convert 'Artist:Title' to a slug like 'artist-title'."""
    return slugify(track.replace(":", " "))


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_track(track: str) -> tuple[str, str]:
    """Parse 'Artist:Title' into (artist, title) tuple.

    Raises:
        ValueError: If track format is invalid.
    """
    if ":" not in track:
        raise ValueError(f"Track must be in 'Artist:Title' format, got: {track}")
    parts = track.split(":", 1)
    artist = parts[0].strip()
    title = parts[1].strip()
    if not artist or not title:
        raise ValueError(f"Both artist and title must be non-empty, got: {track}")
    return artist, title
