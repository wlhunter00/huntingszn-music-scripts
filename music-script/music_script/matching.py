"""Pure harmonic-BPM matching logic. No I/O."""

from __future__ import annotations

_RATIOS: tuple[float, ...] = (1.0, 2.0, 0.5)
_RATIO_LABELS: dict[float, str] = {1.0: "1x", 2.0: "2x", 0.5: "0.5x"}


def is_harmonic_match(base_bpm: float, cand_bpm: float, tolerance: float) -> bool:
    """True if cand_bpm is within +/-tolerance of base_bpm, 2x, or 0.5x."""
    if base_bpm <= 0 or cand_bpm <= 0:
        return False
    lo, hi = 1.0 - tolerance, 1.0 + tolerance
    return any(base_bpm * r * lo <= cand_bpm <= base_bpm * r * hi for r in _RATIOS)


def classify_match_type(base_bpm: float, cand_bpm: float, tolerance: float) -> str:
    """Return the closest matching ratio label, or "" if none matches.

    "Closest" = smallest |cand_bpm / (base_bpm * r) - 1|.
    """
    if base_bpm <= 0 or cand_bpm <= 0:
        return ""
    lo, hi = 1.0 - tolerance, 1.0 + tolerance
    best: tuple[float, float] | None = None  # (deviation, ratio)
    for r in _RATIOS:
        target = base_bpm * r
        if target * lo <= cand_bpm <= target * hi:
            deviation = abs(cand_bpm / target - 1.0)
            if best is None or deviation < best[0]:
                best = (deviation, r)
    return _RATIO_LABELS[best[1]] if best is not None else ""


def ratio_to_base(base_bpm: float, cand_bpm: float) -> float:
    """Return cand_bpm / base_bpm (raw, unrounded). 0 if base is 0."""
    if base_bpm <= 0:
        return 0.0
    return cand_bpm / base_bpm
