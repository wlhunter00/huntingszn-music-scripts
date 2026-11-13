"""Deterministic validator for cue point placement.

Enforces Will's cue system constraints:
- Cue 3 is 16 or 32 beats before cue 4 (run-up)
- Cue 5 is 16 or 32 beats before cue 6 (run-up)
- Cues 1, 2 on 16-beat lattice anchored at cue 4; cue 1 can equal cue 2
- Cues 7, 8 on 32-beat lattice anchored at cue 6
- Proper ordering and bounds

Per-cue abstention: ordering conflicts are repaired by nulling low-confidence cues
rather than rejecting the entire set. Only whole-song skip for grid uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of validating a cue set."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nulled_slots: list[int] = field(default_factory=list)  # Slots nulled due to conflicts

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
        if cues.cue3 is not None:
            gap = cues.cue4 - cues.cue3
            if gap not in (16, 32):
                errors.append(f"cue3 must be 16 or 32 beats before cue4 (gap={gap})")

        for slot in [1, 2]:
            beat = cues.get(slot)
            if beat is not None:
                offset = (cues.cue4 - beat) % 16
                if offset != 0:
                    msg = f"cue{slot} not on 16-lattice from cue4 (off={offset})"
                    errors.append(msg)

    if cues.cue6 is not None:
        if cues.cue5 is not None:
            gap = cues.cue6 - cues.cue5
            if gap not in (16, 32):
                errors.append(f"cue5 must be 16 or 32 beats before cue6 (gap={gap})")

        for slot in [7, 8]:
            beat = cues.get(slot)
            if beat is not None:
                offset = (beat - cues.cue6) % 32
                if offset != 0:
                    msg = f"cue{slot} not on 32-lattice from cue6 (off={offset})"
                    errors.append(msg)

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
        if cues.cue1 > cues.cue2:
            errors.append(f"cue1 ({cues.cue1}) must be <= cue2 ({cues.cue2})")

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


def repair_ordering_conflicts(cues: CueSet) -> tuple[CueSet, list[int]]:
    """Repair ordering conflicts by nulling low-confidence/conflicting cues.

    Instead of rejecting the entire cue set, we null out the problematic cues
    and keep the good ones. Will prefers 3 good cues over 8 questionable ones.

    Args:
        cues: Input CueSet with potential conflicts

    Returns:
        (repaired_cues, nulled_slots) - repaired CueSet and list of slots that were nulled
    """
    result = CueSet(
        cue1=cues.cue1,
        cue2=cues.cue2,
        cue3=cues.cue3,
        cue4=cues.cue4,
        cue5=cues.cue5,
        cue6=cues.cue6,
        cue7=cues.cue7,
        cue8=cues.cue8,
        total_beats=cues.total_beats,
        cue7_midsong=cues.cue7_midsong,
        confidences=cues.confidences.copy(),
    )
    nulled: list[int] = []

    # Fix cue1 > cue2 by nulling cue1 (cue2 is more important as pre-vocal entry)
    if result.cue1 is not None and result.cue2 is not None and result.cue1 > result.cue2:
        result.cue1 = None
        nulled.append(1)

    # Fix cue2 > cue3 by nulling cue2 (cue3 is derived from cue4)
    if result.cue2 is not None and result.cue3 is not None and result.cue2 > result.cue3:
        result.cue2 = None
        nulled.append(2)

    # Fix cue3 >= cue4 by nulling cue3 (keep cue4, it's the anchor)
    if result.cue3 is not None and result.cue4 is not None and result.cue3 >= result.cue4:
        result.cue3 = None
        nulled.append(3)

    # Handle cue4 > cue5 conflict
    if not result.cue7_midsong:
        if result.cue4 is not None and result.cue5 is not None and result.cue4 > result.cue5:
            # This usually means single-drop track - null cue5
            result.cue5 = None
            nulled.append(5)

        # Fix cue5 >= cue6 by nulling cue5
        if result.cue5 is not None and result.cue6 is not None and result.cue5 >= result.cue6:
            result.cue5 = None
            if 5 not in nulled:
                nulled.append(5)

        # Fix cue6 >= cue7 by nulling cue7
        if result.cue6 is not None and result.cue7 is not None and result.cue6 >= result.cue7:
            result.cue7 = None
            nulled.append(7)
    else:
        # Mid-song cue7 conflicts
        if result.cue4 is not None and result.cue7 is not None and result.cue7 <= result.cue4:
            result.cue7 = None
            nulled.append(7)
        if result.cue7 is not None and result.cue5 is not None and result.cue7 >= result.cue5:
            result.cue7 = None
            if 7 not in nulled:
                nulled.append(7)

    # Fix cue7 > cue8 by nulling cue8
    if result.cue7 is not None and result.cue8 is not None and result.cue7 > result.cue8:
        result.cue8 = None
        nulled.append(8)

    return result, nulled


def validate_and_repair(cues: CueSet) -> tuple[CueSet, ValidationResult]:
    """Validate and repair a cue set, nulling conflicting cues instead of rejecting.

    This is the main entry point for per-cue abstention. It:
    1. Repairs ordering conflicts by nulling the lower-priority cue
    2. Validates the repaired set
    3. Returns the repaired set with a ValidationResult

    Hard errors (that still cause validation failure):
    - Negative beat positions
    - Lattice violations (cue not on expected grid)

    Soft errors (repaired by nulling):
    - Ordering conflicts (cue4 > cue5, cue7 > cue8, etc.)

    Args:
        cues: Input CueSet

    Returns:
        (repaired_cues, validation_result)
    """
    repaired, nulled = repair_ordering_conflicts(cues)

    # Now validate the repaired set
    result = validate_cue_set(repaired)
    result.nulled_slots = nulled

    # Add warnings for nulled slots
    for slot in nulled:
        result.warnings.append(f"cue{slot} nulled due to ordering conflict")

    return repaired, result


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


# Slots the model predicts. Cue 3 and cue 5 are derived from cue 4 and cue 6.
_WRITE_SLOTS = (1, 2, 4, 6, 7, 8)
# Anchors outrank their run-ups, which outrank the other slots.
_SLOT_RANK = {slot: rank for rank, slot in enumerate((4, 6, 3, 5, 2, 1, 7, 8))}
# These pairs must be strictly ordered. Other neighbors may share a beat.
_STRICT_BEFORE = {(3, 4), (5, 6), (6, 7)}


def select_high_confidence_cues(
    prediction: object,
    cues: CueSet,
    *,
    min_confidence: float = 0.6,
) -> CueSet:
    """Keep every cue the model scored at or above `min_confidence`.

    A cue under the bar is left blank. The track is not rejected because another
    cue is missing or uncertain. Cue 3 and cue 5 are then placed 32 beats before
    cue 4 and cue 6, or 16 beats before when 32 does not fit.
    """
    chosen: list[tuple[int, int, float]] = []
    for slot in _WRITE_SLOTS:
        beat, conf = _explicit_cue(prediction, cues, slot)
        if beat is None or conf is None or conf < min_confidence:
            continue
        if beat < 0 or (cues.total_beats > 0 and beat >= cues.total_beats):
            continue
        if slot == 8 and cues.total_beats > 0 and cues.total_beats - beat < 8:
            continue
        chosen.append((slot, int(beat), float(conf)))

    chosen = _dedupe_same_beat(chosen)
    chosen = _drop_order_conflicts(chosen)
    chosen = _with_run_ups(chosen)
    chosen = _dedupe_same_beat(chosen)
    chosen = _drop_order_conflicts(chosen)

    result = CueSet(total_beats=cues.total_beats, cue7_midsong=cues.cue7_midsong)
    for slot, beat, conf in chosen:
        result.set(slot, beat)
        result.confidences[slot] = conf
    return result


def _explicit_cue(prediction: object, cues: CueSet, slot: int) -> tuple[int | None, float | None]:
    """Read a model cue. Fall back to the cue set only when the prediction has no slots."""
    attr = f"cue{slot}"
    if hasattr(prediction, attr):
        cue = getattr(prediction, attr)
        if cue is None or not hasattr(cue, "beat"):
            return None, None
        return cue.beat, float(cue.confidence)
    if any(hasattr(prediction, f"cue{other}") for other in _WRITE_SLOTS):
        return None, None
    return cues.get(slot), cues.confidences.get(slot)


def _dedupe_same_beat(
    chosen: list[tuple[int, int, float]],
) -> list[tuple[int, int, float]]:
    best: dict[int, tuple[int, int, float]] = {}
    for item in chosen:
        current = best.get(item[1])
        rank = -_SLOT_RANK[item[0]]
        current_rank = None if current is None else -_SLOT_RANK[current[0]]
        if current is None or (item[2], rank) > (current[2], current_rank):
            best[item[1]] = item
    return list(best.values())


def run_up_beat(anchor: int, *, not_before: int | None = None) -> int | None:
    """Beat of the run-up cue before ``anchor``.

    Prefer 32 beats earlier. Use 16 when 32 would land before ``not_before``
    or before the start of the track.
    """
    if anchor >= 32:
        beat = anchor - 32
    elif anchor >= 16:
        beat = anchor - 16
    else:
        return None
    if not_before is not None and beat <= not_before:
        if anchor - 16 > not_before:
            beat = anchor - 16
        else:
            return None
    if beat < 0 or beat >= anchor:
        return None
    return beat


def _with_run_ups(
    chosen: list[tuple[int, int, float]],
) -> list[tuple[int, int, float]]:
    by_slot = {slot: item for item in chosen for slot, _, _ in (item,)}
    cue4 = by_slot.get(4)
    cue6 = by_slot.get(6)
    if cue4 is not None and 3 not in by_slot:
        cue3 = run_up_beat(cue4[1])
        if cue3 is not None:
            by_slot[3] = (3, cue3, cue4[2])
    if cue6 is not None and 5 not in by_slot:
        cue5 = run_up_beat(cue6[1], not_before=None if cue4 is None else cue4[1])
        if cue5 is not None:
            by_slot[5] = (5, cue5, cue6[2])
    return list(by_slot.values())


def _time_matches_slot_order(chosen: list[tuple[int, int, float]]) -> bool:
    ordered = sorted(chosen, key=lambda item: item[0])
    for prev, nxt in zip(ordered, ordered[1:]):
        if (prev[0], nxt[0]) in _STRICT_BEFORE:
            if prev[1] >= nxt[1]:
                return False
        elif prev[1] > nxt[1]:
            return False
    return True


def _drop_order_conflicts(
    chosen: list[tuple[int, int, float]],
) -> list[tuple[int, int, float]]:
    chosen = list(chosen)
    while chosen and not _time_matches_slot_order(chosen):
        chosen.remove(min(chosen, key=lambda item: (item[2], -_SLOT_RANK[item[0]])))
    return chosen


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
    cue3_gap: int = 32,
    cue5_gap: int = 32,
    cue7_midsong: bool = False,
) -> CueSet:
    """Build a complete cue set deterministically from cue4 and cue6.

    Args:
        cue4: Beat position of first drop
        cue6: Beat position of last drop
        total_beats: Total beats in track
        cue1_at_start: If True, place cue1 at beat 0
        cue2_offset: Offset from cue3 (any multiple of 16)
        cue3_gap: Gap from cue3 to cue4 (16 or 32 beats)
        cue5_gap: Gap from cue5 to cue6 (16 or 32 beats)
        cue7_midsong: If True, cue7 is between cue4 and cue5

    Returns:
        Complete CueSet
    """
    cues = CueSet(total_beats=total_beats, cue7_midsong=cue7_midsong)

    cues.cue4 = cue4
    cues.cue6 = cue6

    cues.cue3 = max(0, cue4 - cue3_gap)
    cues.cue5 = max(0, cue6 - cue5_gap)

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
        while candidate > 0 and (cue4 - candidate) % 16 == 0:
            candidate -= 16
        cues.cue1 = max(0, candidate + 16)

    if cues.cue1 > cues.cue2 and cues.cue2 >= 0:
        cues.cue1 = max(0, cues.cue2 - 16)
        if cues.cue1 < 0:
            cues.cue1 = 0

    if cues.cue1 > cues.cue2:
        if cues.cue2 > 16:
            cues.cue1 = cues.cue2 - 16
        elif cues.cue2 >= 0:
            cues.cue1 = cues.cue2

    if cue7_midsong:
        cues.cue7 = cue4 + 32
        cues.cue8 = None
    else:
        cues.cue7 = cue6 + 32
        cues.cue8 = cue6 + 64

        min_end_margin = 16
        max_cue8 = total_beats - min_end_margin

        if cues.cue8 > max_cue8:
            k = (max_cue8 - cue6) // 32
            cues.cue8 = cue6 + k * 32

        if cues.cue8 <= cues.cue7:
            cues.cue8 = cues.cue7 + 32

    return cues
