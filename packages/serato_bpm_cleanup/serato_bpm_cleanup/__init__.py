"""Serato decimal-BPM / beatgrid cleanup."""

from __future__ import annotations

__version__ = "0.1.0"

FRACTION_THRESHOLD = 0.02

ACTION_FIX = "fix"
ACTION_SKIP_HAS_CUES = "skip-has-cues"
ACTION_SKIP_ALREADY_INTEGER = "skip-already-integer"
ACTION_SKIP_NO_BPM = "skip-no-bpm"
