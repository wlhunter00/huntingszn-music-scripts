"""Locked BPM rounding rules.

A stored BPM is “bad” (non-integer) when ``abs(bpm - round(bpm)) >= 0.02``.
The proposed fix is nearest-integer rounding. Tempo is never doubled or halved.
"""

from __future__ import annotations

from serato_bpm_cleanup import FRACTION_THRESHOLD


def is_non_integer_bpm(bpm: float, threshold: float = FRACTION_THRESHOLD) -> bool:
    """True when BPM is far enough from an integer to be treated as fractional."""
    return abs(bpm - round(bpm)) >= threshold


def proposed_integer_bpm(bpm: float) -> int:
    """Round to nearest integer (128.31 → 128, 127.6 → 128)."""
    return int(round(bpm))
