"""Camelot wheel key conversion helpers.

The Camelot system maps musical keys to a numbered wheel (1-12) with A/B suffixes:
- A = minor keys
- B = major keys

Harmonic mixing rules:
- Same number: compatible (e.g., 8A with 8B is relative major/minor)
- ±1 on the wheel: compatible (e.g., 8A with 7A or 9A)
"""

from __future__ import annotations

import re

MUSICAL_TO_CAMELOT: dict[str, str] = {
    "C major": "8B",
    "C minor": "5A",
    "C# major": "3B",
    "Db major": "3B",
    "C# minor": "12A",
    "Db minor": "12A",
    "D major": "10B",
    "D minor": "7A",
    "D# major": "5B",
    "Eb major": "5B",
    "D# minor": "2A",
    "Eb minor": "2A",
    "E major": "12B",
    "E minor": "9A",
    "F major": "7B",
    "F minor": "4A",
    "F# major": "2B",
    "Gb major": "2B",
    "F# minor": "11A",
    "Gb minor": "11A",
    "G major": "9B",
    "G minor": "6A",
    "G# major": "4B",
    "Ab major": "4B",
    "G# minor": "1A",
    "Ab minor": "1A",
    "A major": "11B",
    "A minor": "8A",
    "A# major": "6B",
    "Bb major": "6B",
    "A# minor": "3A",
    "Bb minor": "3A",
    "B major": "1B",
    "B minor": "10A",
}

CAMELOT_TO_MUSICAL: dict[str, str] = {
    "1A": "Ab minor",
    "1B": "B major",
    "2A": "Eb minor",
    "2B": "F# major",
    "3A": "Bb minor",
    "3B": "Db major",
    "4A": "F minor",
    "4B": "Ab major",
    "5A": "C minor",
    "5B": "Eb major",
    "6A": "G minor",
    "6B": "Bb major",
    "7A": "D minor",
    "7B": "F major",
    "8A": "A minor",
    "8B": "C major",
    "9A": "E minor",
    "9B": "G major",
    "10A": "B minor",
    "10B": "D major",
    "11A": "F# minor",
    "11B": "A major",
    "12A": "C# minor",
    "12B": "E major",
}

_CAMELOT_PATTERN = re.compile(r"^(1[0-2]|[1-9])[ABab]$")
_MUSICAL_KEY_PATTERN = re.compile(
    r"^([A-Ga-g])([#b])?\s*(major|minor|maj|min|m)?$", re.IGNORECASE
)


def normalize_camelot(key: str) -> str | None:
    """Normalize a Camelot key string to uppercase (e.g., '8a' -> '8A')."""
    key = key.strip()
    if _CAMELOT_PATTERN.match(key):
        return key.upper()
    return None


def parse_musical_key(key_str: str) -> str | None:
    """Parse a musical key string and return normalized form.

    Accepts: "Am", "A minor", "A min", "A m", "A", "C#m", "F# minor", etc.
    Returns: "A minor", "C# minor", "F# major", etc.
    """
    key_str = key_str.strip()
    match = _MUSICAL_KEY_PATTERN.match(key_str)
    if not match:
        if key_str.endswith("m") and len(key_str) >= 2:
            root = key_str[:-1].strip()
            return parse_musical_key(root + " minor")
        return None

    root = match.group(1).upper()
    accidental = match.group(2) or ""
    quality = match.group(3)

    if quality:
        quality = quality.lower()
        is_minor = quality in ("minor", "min", "m")
    else:
        is_minor = False

    quality_str = "minor" if is_minor else "major"
    return f"{root}{accidental} {quality_str}"


def musical_to_camelot(key: str) -> str | None:
    """Convert musical key notation to Camelot.

    Args:
        key: Musical key like "Am", "A minor", "C#m", "F# major"

    Returns:
        Camelot code like "8A", "12A", "2B", or None if unrecognized
    """
    camelot = normalize_camelot(key)
    if camelot:
        return camelot

    musical = parse_musical_key(key)
    if musical:
        return MUSICAL_TO_CAMELOT.get(musical)

    return None


def camelot_to_musical(camelot: str) -> str | None:
    """Convert Camelot code to musical key notation."""
    normalized = normalize_camelot(camelot)
    if normalized:
        return CAMELOT_TO_MUSICAL.get(normalized)
    return None


def get_relative_key(camelot: str) -> str | None:
    """Get the relative major/minor key (same number, opposite A/B)."""
    normalized = normalize_camelot(camelot)
    if not normalized:
        return None
    num = normalized[:-1]
    suffix = normalized[-1]
    return f"{num}{'B' if suffix == 'A' else 'A'}"


def get_adjacent_keys(camelot: str) -> list[str]:
    """Get keys ±1 on the wheel (wraps 12->1 and 1->12)."""
    normalized = normalize_camelot(camelot)
    if not normalized:
        return []
    num = int(normalized[:-1])
    suffix = normalized[-1]
    prev_num = 12 if num == 1 else num - 1
    next_num = 1 if num == 12 else num + 1
    return [f"{prev_num}{suffix}", f"{next_num}{suffix}"]


def get_compatible_keys(camelot: str) -> set[str]:
    """Get all harmonically compatible keys (±1 + relative major/minor).

    This returns the input key plus:
    - The relative major/minor (same number, different letter)
    - The key one step counterclockwise on the wheel
    - The key one step clockwise on the wheel
    """
    normalized = normalize_camelot(camelot)
    if not normalized:
        return set()

    compatible = {normalized}
    relative = get_relative_key(normalized)
    if relative:
        compatible.add(relative)
    compatible.update(get_adjacent_keys(normalized))
    return compatible
