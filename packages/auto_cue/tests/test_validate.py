"""Tests for the deterministic 32-grid validator.

Tests:
- 32-beat lattice constraints for cues 1-4 and 5-8
- Ordering constraints
- Bounds checking
- Confidence thresholds
- Partial cue sets
"""

from __future__ import annotations

import pytest

from auto_cue.validate import (
    CueSet,
    ValidationResult,
    validate_cue_set,
    check_confidence_threshold,
    build_cues_deterministic,
    is_valid_partial,
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
    """Test 32-beat lattice constraints."""

    def test_cue3_on_cue4_lattice(self):
        """cue3 must be on 32-beat lattice from cue4."""
        cues = CueSet(
            cue3=64,  # 96 - 32 = 64, on lattice
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue3_off_lattice_fails(self):
        """cue3 off 32-beat lattice should fail (unless 16-offset)."""
        cues = CueSet(
            cue3=70,  # Not on lattice
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        
        assert not result.valid
        assert "cue3 not on 32-beat lattice" in str(result.errors)

    def test_cue3_16_offset_warns(self):
        """cue3 at 16-offset should warn but pass."""
        cues = CueSet(
            cue3=80,  # 96 - 16 = 80, 16-offset
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        
        assert result.valid
        assert "16-offset" in str(result.warnings)

    def test_cue2_on_lattice(self):
        """cue2 must be on 32-beat lattice from cue4."""
        cues = CueSet(
            cue2=32,
            cue3=64,
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue1_on_lattice(self):
        """cue1 must be on 32-beat lattice from cue4."""
        cues = CueSet(
            cue1=0,  # 96 - 96 = 0, on lattice
            cue2=32,
            cue3=64,
            cue4=96,
            cue6=192,
            total_beats=300,
        )
        result = validate_cue_set(cues)
        assert result.valid

    def test_cue5_on_cue6_lattice(self):
        """cue5 must be on 32-beat lattice from cue6."""
        cues = CueSet(
            cue4=96,
            cue5=160,  # 192 - 32 = 160, on lattice
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
        """cue1 must be < cue2."""
        cues = CueSet(
            cue1=64,
            cue2=32,  # Wrong order
            cue3=64,
            cue4=96,
            cue6=192,
        )
        result = validate_cue_set(cues)
        
        assert not result.valid
        assert "cue1" in str(result.errors) and "cue2" in str(result.errors)

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
