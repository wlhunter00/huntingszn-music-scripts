"""Tests for the deterministic cue validator.

Tests:
- Cue 3/5 can be 16 or 32 beats before cue 4/6 (run-up)
- Cues 1, 2 on 16-beat lattice from cue4; cue1 can equal cue2
- Cues 7, 8 on 32-beat lattice from cue6
- Ordering constraints
- Bounds checking
- Confidence thresholds
- Partial cue sets
"""

from __future__ import annotations

from auto_cue.llm import CueConfidence, LLMPrediction
from auto_cue.validate import (
    CueSet,
    build_cues_deterministic,
    check_confidence_threshold,
    is_valid_partial,
    select_high_confidence_cues,
    validate_cue_set,
)


class TestBasicValidation:
    """Test basic cue set validation."""

    def test_valid_standard_cue_set(self):
        """Standard 8-cue set should validate."""
        cues = CueSet(
            cue1=0,
            cue2=32,
            cue3=64,
            cue4=96,
            cue5=160,
            cue6=192,
            cue7=224,
            cue8=256,
            total_beats=300,
        )
        result = validate_cue_set(cues)

        assert result.valid
        assert len(result.errors) == 0

    def test_missing_cue4_fails(self):
        """Missing cue4 should fail validation."""
        cues = CueSet(cue6=192)
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue4" in str(result.errors)

    def test_missing_cue6_fails(self):
        """Missing cue6 should fail validation."""
        cues = CueSet(cue4=96)
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue6" in str(result.errors)

    def test_negative_cue_fails(self):
        """Negative cue position should fail."""
        cues = CueSet(cue1=-32, cue4=96, cue6=192)
        result = validate_cue_set(cues)

        assert not result.valid
        assert "negative" in str(result.errors)


class TestLatticeConstraints:
    """Test lattice constraints."""

    def test_cue3_32_before_cue4(self):
        """cue3 can be 32 beats before cue4."""
        cues = CueSet(
            cue3=64,  # 96 - 32 = 64
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue3_16_before_cue4(self):
        """cue3 can be 16 beats before cue4 (run-up)."""
        cues = CueSet(
            cue3=80,  # 96 - 16 = 80
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue3_wrong_gap_fails(self):
        """cue3 with wrong gap (not 16 or 32) should fail."""
        cues = CueSet(
            cue3=70,  # Not 16 or 32 before cue4
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue3 must be 16 or 32 beats before cue4" in str(result.errors)

    def test_cue2_on_16_lattice(self):
        """cue2 must be on 16-beat lattice from cue4."""
        cues = CueSet(
            cue2=32,  # 96 - 64 = 32, on 16-lattice
            cue3=64,
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue2_16_beat_positions(self):
        """cue2 can be any multiple of 16 before cue3 (on 16-beat lattice)."""
        # cue2 must be <= cue3, and on 16-beat lattice from cue4
        # With cue3=64 and cue4=96, valid cue2 values are: 0, 16, 32, 48, 64
        for cue2_beat in [0, 16, 32, 48, 64]:
            cues = CueSet(
                cue2=cue2_beat,  # Various 16-beat positions <= cue3
                cue3=64,
                cue4=96,
                cue6=192,
                total_beats=300,
            )
            result = validate_cue_set(cues)
            assert result.valid, f"cue2 at {cue2_beat} should be valid"

    def test_cue1_on_16_lattice(self):
        """cue1 must be on 16-beat lattice from cue4."""
        cues = CueSet(
            cue1=0,  # 96 - 96 = 0, on 16-lattice
            cue2=32,
            cue3=64,
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue5_32_before_cue6(self):
        """cue5 can be 32 beats before cue6."""
        cues = CueSet(
            cue4=96,
            cue5=160,  # 192 - 32 = 160
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue5_16_before_cue6(self):
        """cue5 can be 16 beats before cue6 (run-up)."""
        cues = CueSet(
            cue4=96,
            cue5=176,  # 192 - 16 = 176
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue7_on_cue6_lattice(self):
        """cue7 must be on 32-beat lattice from cue6."""
        cues = CueSet(
            cue4=96,
            cue6=192,
            cue7=224,  # 192 + 32 = 224, on lattice
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue8_on_cue6_lattice(self):
        """cue8 must be on 32-beat lattice from cue6."""
        cues = CueSet(
            cue4=96,
            cue6=192,
            cue7=224,
            cue8=256,  # 192 + 64 = 256, on lattice
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid


class TestOrderingConstraints:
    """Test cue ordering constraints."""

    def test_cue1_before_cue2(self):
        """cue1 must be <= cue2."""
        cues = CueSet(
            cue1=64,
            cue2=32,  # Wrong order (cue1 > cue2)
            cue3=64,
            cue4=96,
            cue6=192,
        )
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue1" in str(result.errors) and "cue2" in str(result.errors)

    def test_cue1_equals_cue2_allowed(self):
        """cue1 == cue2 should be allowed."""
        cues = CueSet(
            cue1=32,
            cue2=32,  # Same position
            cue3=64,
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue6_gte_cue4(self):
        """cue6 must be >= cue4."""
        cues = CueSet(
            cue4=192,
            cue6=96,  # Wrong order
        )
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue6" in str(result.errors) and "cue4" in str(result.errors)

    def test_single_drop_allowed(self):
        """cue6 == cue4 (single drop) should be allowed."""
        cues = CueSet(
            cue4=96,
            cue6=96,  # Same position
            total_beats=200,
        )
        result = validate_cue_set(cues)
        assert result.valid


class TestBoundsChecking:
    """Test boundary constraints."""

    def test_cue8_too_close_to_end(self):
        """cue8 too close to end should fail."""
        cues = CueSet(
            cue4=96,
            cue6=192,
            cue7=224,
            cue8=295,  # Only 5 beats before end
            total_beats=300,
        )
        result = validate_cue_set(cues)

        assert not result.valid
        assert "cue8 too close to end" in str(result.errors)

    def test_cue8_far_from_end_warns(self):
        """cue8 unusually far from end should warn."""
        cues = CueSet(
            cue4=96,
            cue6=192,
            cue7=224,
            cue8=256,  # 144 beats before end (on lattice: 192 + 64)
            total_beats=400,
        )
        result = validate_cue_set(cues)

        assert result.valid
        assert "unusually far from end" in str(result.warnings)


class TestMidsongCue7:
    """Test mid-song cue7 special case."""

    def test_midsong_cue7_valid(self):
        """Mid-song cue7 between cue4 and cue5 should be valid."""
        cues = CueSet(
            cue1=0,
            cue2=32,
            cue3=64,
            cue4=96,
            cue7=128,  # Mid-song, after cue4 but before cue5
            cue5=160,
            cue6=192,
            total_beats=300,
            cue7_midsong=True,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_midsong_cue7_before_cue4_fails(self):
        """Mid-song cue7 before cue4 should fail."""
        cues = CueSet(
            cue4=96,
            cue7=64,  # Before cue4
            cue5=160,
            cue6=192,
            total_beats=300,
            cue7_midsong=True,
        )
        result = validate_cue_set(cues)

        assert not result.valid


class TestConfidenceThreshold:
    """Test confidence threshold checking."""

    def test_low_cue4_confidence_abstains(self):
        """Low cue4 confidence should cause abstain."""
        cues = CueSet(cue4=96, cue6=192)
        cues.confidences = {4: 0.3, 6: 0.9}

        filtered, reasons = check_confidence_threshold(cues, core_threshold=0.6)

        assert len(reasons) > 0
        assert "cue4 confidence" in str(reasons)

    def test_low_cue6_confidence_abstains(self):
        """Low cue6 confidence should cause abstain."""
        cues = CueSet(cue4=96, cue6=192)
        cues.confidences = {4: 0.9, 6: 0.3}

        filtered, reasons = check_confidence_threshold(cues, core_threshold=0.6)

        assert len(reasons) > 0
        assert "cue6 confidence" in str(reasons)

    def test_low_other_cue_drops_slot(self):
        """Low confidence on non-core cue should drop that slot."""
        cues = CueSet(cue1=0, cue4=96, cue6=192)
        cues.confidences = {1: 0.2, 4: 0.9, 6: 0.9}

        filtered, reasons = check_confidence_threshold(
            cues,
            core_threshold=0.6,
            other_threshold=0.4,
        )

        assert len(reasons) == 0
        assert filtered.cue1 is None
        assert filtered.cue4 == 96


class TestBuildCuesDeterministic:
    """Test deterministic cue building."""

    def test_standard_build(self):
        """Standard cue build from cue4 and cue6."""
        cues = build_cues_deterministic(
            cue4=96,
            cue6=192,
            total_beats=300,
        )

        assert cues.cue4 == 96
        assert cues.cue6 == 192
        assert cues.cue3 == 64
        assert cues.cue5 == 160
        assert cues.cue1 == 0
        assert cues.cue7 == 224
        assert cues.cue8 == 256

    def test_cue2_offset_options(self):
        """cue2 offset should be configurable."""
        cues32 = build_cues_deterministic(cue4=128, cue6=224, total_beats=300, cue2_offset=32)
        cues64 = build_cues_deterministic(cue4=128, cue6=224, total_beats=300, cue2_offset=64)

        assert cues32.cue2 == 64  # 96 - 32 = 64
        assert cues64.cue2 == 32  # 96 - 64 = 32


def _prediction(slots: dict[int, tuple[int | None, float]]) -> LLMPrediction:
    def cue(slot: int) -> CueConfidence:
        beat, conf = slots.get(slot, (None, 0.0))
        return CueConfidence(beat, conf)

    return LLMPrediction(
        cue1=cue(1),
        cue2=cue(2),
        cue4=cue(4),
        cue6=cue(6),
        cue7=cue(7),
        cue8=cue(8),
        cue7_midsong=False,
        rationale="",
    )


class TestHighConfidenceSelection:
    """Every model cue at or above the bar is kept. Uncertain cues stay blank."""

    def test_keeps_every_confident_cue_and_skips_derived_slots(self):
        prediction = _prediction(
            {1: (0, 0.95), 2: (32, 0.9), 4: (96, 0.99), 6: (192, 0.97), 7: (224, 0.7), 8: (256, 0.65)}
        )
        cues = CueSet(total_beats=300)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.filled_slots() == [1, 2, 4, 6, 7, 8]
        assert kept.cue3 is None
        assert kept.cue5 is None

    def test_missing_drop_still_keeps_other_confident_cues(self):
        prediction = _prediction({2: (32, 0.91), 4: (96, 0.93), 6: (None, 0.2)})
        cues = CueSet(total_beats=300)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.filled_slots() == [2, 4]
        assert kept.cue6 is None

    def test_low_confidence_cue_is_blank_not_a_track_skip(self):
        prediction = _prediction({4: (96, 0.58), 6: (192, 0.92), 8: (256, 0.8)})
        cues = CueSet(total_beats=400)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.cue4 is None
        assert kept.filled_slots() == [6, 8]

    def test_drops_cue_too_close_to_the_end(self):
        prediction = _prediction({4: (64, 0.9), 6: (128, 0.9), 8: (190, 0.95)})
        cues = CueSet(total_beats=194)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.cue8 is None
        assert kept.filled_slots() == [4, 6]

    def test_same_beat_keeps_the_more_important_slot(self):
        prediction = _prediction({1: (32, 0.9), 2: (32, 0.9), 4: (96, 0.95)})
        cues = CueSet(total_beats=200)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.cue1 is None
        assert kept.cue2 == 32
        assert kept.cue4 == 96

    def test_no_confident_cues_returns_empty(self):
        prediction = _prediction({4: (96, 0.4), 6: (160, 0.5)})
        cues = CueSet(total_beats=200)

        kept = select_high_confidence_cues(prediction, cues, min_confidence=0.6)

        assert kept.filled_slots() == []


class TestPartialSets:
    """Test partial cue set validation."""

    def test_full_set_valid(self):
        """Full 8-cue set is valid."""
        assert is_valid_partial({1, 2, 3, 4, 5, 6, 7, 8})

    def test_1_to_4_valid(self):
        """Slots 1-4 only is valid."""
        assert is_valid_partial({1, 2, 3, 4})

    def test_1_to_6_valid(self):
        """Slots 1-6 only is valid."""
        assert is_valid_partial({1, 2, 3, 4, 5, 6})

    def test_1_to_7_valid(self):
        """Slots 1-7 only is valid."""
        assert is_valid_partial({1, 2, 3, 4, 5, 6, 7})

    def test_random_subset_invalid(self):
        """Random subset like {1, 3, 5, 7} is not valid."""
        assert not is_valid_partial({1, 3, 5, 7})
