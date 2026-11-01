"""Deterministic validator for cue point placement.

Enforces Will's cue system constraints:
- Cues 1-4 on a 32-beat lattice anchored at cue 4
- Cues 5-8 on a 32-beat lattice anchored at cue 6
- Proper ordering and bounds
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of validating a cue set."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    def __bool__(self) -> bool:
        return self.valid


@dataclass
class CuePrediction:
    """A predicted cue with confidence."""
    slot: int  # 1-8 (user-facing), internally 0-7
    beat: int
    confidence: float = 1.0
    
    @property
    def index(self) -> int:
        """0-indexed slot for Serato."""
        return self.slot - 1


@dataclass
class CueSet:
    """Complete set of predicted cues."""
    cue1: int | None = None
    cue2: int | None = None
    cue3: int | None = None
    cue4: int | None = None  # First drop - required
    cue5: int | None = None
    cue6: int | None = None  # Last drop - required
    cue7: int | None = None
    cue8: int | None = None
    
    confidences: dict[int, float] = field(default_factory=dict)
    
    total_beats: int = 0
    cue7_midsong: bool = False
    
    def get(self, slot: int) -> int | None:
        """Get beat position for slot 1-8."""
        return getattr(self, f"cue{slot}", None)
    
    def set(self, slot: int, beat: int | None) -> None:
        """Set beat position for slot 1-8."""
        setattr(self, f"cue{slot}", beat)
    
    def to_dict(self) -> dict[int, int]:
        """Return dict of slot -> beat for non-None cues."""
        result = {}
        for i in range(1, 9):
            beat = self.get(i)
            if beat is not None:
                result[i - 1] = beat  # Convert to 0-indexed
        return result
    
    def filled_slots(self) -> list[int]:
        """Return list of filled slot numbers (1-8)."""
        return [i for i in range(1, 9) if self.get(i) is not None]


def validate_cue_set(cues: CueSet, *, tolerance: float = 0.5) -> ValidationResult:
    """Validate a complete cue set against Will's rules.
    
    Args:
        cues: The cue set to validate
        tolerance: Beat tolerance for grid alignment (default 0.5)
    
    Returns:
        ValidationResult with errors and warnings
    """
    errors = []
    warnings = []
    
    if cues.cue4 is None:
        errors.append("cue4 (first drop) is required")
    if cues.cue6 is None:
        errors.append("cue6 (last drop) is required")
    
    if errors:
        return ValidationResult(valid=False, errors=errors)
    
    for i in range(1, 9):
        beat = cues.get(i)
        if beat is not None and beat < 0:
            errors.append(f"cue{i} is negative ({beat})")
    
    if cues.cue4 is not None:
        for slot in [1, 2, 3]:
            beat = cues.get(slot)
            if beat is not None:
                offset = (cues.cue4 - beat) % 32
                if offset != 0:
                    if slot == 3 and offset == 16:
                        warnings.append(f"cue{slot} is 16-offset from cue4 (allowed)")
                    else:
                        errors.append(f"cue{slot} not on 32-beat lattice from cue4 (offset={offset})")
    
    if cues.cue6 is not None:
        for slot in [5, 7, 8]:
            beat = cues.get(slot)
            if beat is not None:
                offset = (beat - cues.cue6) % 32
                if offset != 0:
                    if slot == 5 and offset == 16:
                        warnings.append(f"cue{slot} is 16-offset from cue6 (allowed)")
                    else:
                        errors.append(f"cue{slot} not on 32-beat lattice from cue6 (offset={offset})")
    
    _check_order(cues, errors)
    
    if cues.cue4 is not None and cues.cue6 is not None:
        if cues.cue6 < cues.cue4:
            errors.append(f"cue6 ({cues.cue6}) must be >= cue4 ({cues.cue4})")
    
    if cues.cue1 is not None and cues.cue1 < 0:
        errors.append(f"cue1 ({cues.cue1}) must be >= 0")
    
    if cues.total_beats > 0 and cues.cue8 is not None:
        beats_before_end = cues.total_beats - cues.cue8
        if beats_before_end < 8:
            errors.append(f"cue8 too close to end ({beats_before_end} beats before end)")
        elif beats_before_end < 16:
            warnings.append(f"cue8 close to end ({beats_before_end} beats)")
        elif beats_before_end > 80:
            warnings.append(f"cue8 unusually far from end ({beats_before_end} beats)")
    
    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _check_order(cues: CueSet, errors: list[str]) -> None:
    """Check cue ordering constraints."""
    if cues.cue1 is not None and cues.cue2 is not None:
        if cues.cue1 >= cues.cue2:
            errors.append(f"cue1 ({cues.cue1}) must be < cue2 ({cues.cue2})")
    
    if cues.cue2 is not None and cues.cue3 is not None:
        if cues.cue2 > cues.cue3:
            errors.append(f"cue2 ({cues.cue2}) must be <= cue3 ({cues.cue3})")
    
    if cues.cue3 is not None and cues.cue4 is not None:
        if cues.cue3 >= cues.cue4:
            errors.append(f"cue3 ({cues.cue3}) must be < cue4 ({cues.cue4})")
    
    if not cues.cue7_midsong:
        if cues.cue4 is not None and cues.cue5 is not None:
            if cues.cue4 > cues.cue5:
                errors.append(f"cue4 ({cues.cue4}) must be <= cue5 ({cues.cue5})")
        
        if cues.cue5 is not None and cues.cue6 is not None:
            if cues.cue5 >= cues.cue6:
                errors.append(f"cue5 ({cues.cue5}) must be < cue6 ({cues.cue6})")
        
        if cues.cue6 is not None and cues.cue7 is not None:
            if cues.cue6 >= cues.cue7:
                errors.append(f"cue6 ({cues.cue6}) must be < cue7 ({cues.cue7})")
    else:
        if cues.cue4 is not None and cues.cue7 is not None:
            if cues.cue7 <= cues.cue4:
                errors.append(f"mid-song cue7 ({cues.cue7}) must be > cue4 ({cues.cue4})")
        if cues.cue7 is not None and cues.cue5 is not None:
            if cues.cue7 >= cues.cue5:
                errors.append(f"mid-song cue7 ({cues.cue7}) must be < cue5 ({cues.cue5})")
    
    if cues.cue7 is not None and cues.cue8 is not None:
        if cues.cue7 > cues.cue8:
            errors.append(f"cue7 ({cues.cue7}) must be <= cue8 ({cues.cue8})")


def check_confidence_threshold(
    cues: CueSet,
    *,
    core_threshold: float = 0.6,
    other_threshold: float = 0.4,
) -> tuple[CueSet, list[str]]:
    """Check confidence thresholds and drop low-confidence cues.
    
    Args:
        cues: Input cue set with confidences
        core_threshold: Minimum confidence for cue4 and cue6
        other_threshold: Minimum confidence for other cues
    
    Returns:
        (filtered_cues, abstain_reasons) - None cues if we should abstain entirely
    """
    abstain_reasons = []
    
    for core in [4, 6]:
        conf = cues.confidences.get(core, 1.0)
        if conf < core_threshold:
            abstain_reasons.append(f"cue{core} confidence {conf:.2f} < {core_threshold}")
    
    if abstain_reasons:
        return cues, abstain_reasons
    
    result = CueSet(
        cue4=cues.cue4,
        cue6=cues.cue6,
        total_beats=cues.total_beats,
        cue7_midsong=cues.cue7_midsong,
        confidences=cues.confidences.copy(),
    )
    
    for slot in [1, 2, 3, 5, 7, 8]:
        conf = cues.confidences.get(slot, 1.0)
        if conf >= other_threshold:
            result.set(slot, cues.get(slot))
    
    return result, []


VALID_PARTIAL_SETS = [
    {1, 2, 3, 4},           # Just first drop section
    {1, 2, 3, 4, 5, 6},     # Both drops, no outro markers
    {1, 2, 3, 4, 5, 6, 7},  # Missing only cue8
]


def is_valid_partial(filled: set[int]) -> bool:
    """Check if a partial cue set is valid (matches Will's habits)."""
    if len(filled) == 8:
        return True
    return filled in VALID_PARTIAL_SETS


def build_cues_deterministic(
    *,
    cue4: int,
    cue6: int,
    total_beats: int,
    cue1_at_start: bool = True,
    cue2_offset: int = 32,
    cue7_midsong: bool = False,
) -> CueSet:
    """Build a complete cue set deterministically from cue4 and cue6.
    
    Args:
        cue4: Beat position of first drop
        cue6: Beat position of last drop
        total_beats: Total beats in track
        cue1_at_start: If True, place cue1 at beat 0
        cue2_offset: Offset from cue3 (32, 64, or 96)
        cue7_midsong: If True, cue7 is between cue4 and cue5
    
    Returns:
        Complete CueSet
    """
    cues = CueSet(total_beats=total_beats, cue7_midsong=cue7_midsong)
    
    cues.cue4 = cue4
    cues.cue6 = cue6
    
    cues.cue3 = max(0, cue4 - 32)
    cues.cue5 = max(0, cue6 - 32)
    
    cues.cue2 = cues.cue3 - cue2_offset
    if cues.cue2 < 0:
        cues.cue2 = cues.cue3 - 32
    if cues.cue2 < 0:
        cues.cue2 = max(0, cues.cue3 - 16)
    if cues.cue2 < 0:
        cues.cue2 = cues.cue3
    
    if cue1_at_start:
        cues.cue1 = 0
    else:
        candidate = cue4 - 96
        while candidate > 0 and (cue4 - candidate) % 32 == 0:
            candidate -= 32
        cues.cue1 = max(0, candidate + 32)
    
    if cues.cue1 >= cues.cue2 and cues.cue2 > 0:
        cues.cue1 = max(0, cues.cue2 - 32)
        if cues.cue1 < 0:
            cues.cue1 = 0
    
    if cues.cue1 >= cues.cue2:
        if cues.cue2 > 16:
            cues.cue1 = cues.cue2 - 16
        elif cues.cue2 > 0:
            cues.cue1 = 0
        else:
            cues.cue2 = 16
            cues.cue1 = 0
    
    if cue7_midsong:
        cues.cue7 = cue4 + 32
        cues.cue8 = None
    else:
        cues.cue7 = cue6 + 32
        cues.cue8 = cue6 + 64
        
        # cue8 must stay on 32-beat lattice from cue6
        min_end_margin = 16
        max_cue8 = total_beats - min_end_margin
        
        if cues.cue8 > max_cue8:
            # Find highest valid lattice point: cue6 + k*32 <= max_cue8
            k = (max_cue8 - cue6) // 32
            cues.cue8 = cue6 + k * 32
        
        # cue8 must be > cue7
        if cues.cue8 <= cues.cue7:
            cues.cue8 = cues.cue7 + 32
    
    return cues
