"""Multi-word artists that should not be split or stripped during library prep."""

from __future__ import annotations

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


def is_known_artist(artist: str) -> bool:
    lower = artist.lower()
    return any(known in lower for known in KNOWN_ARTISTS)
