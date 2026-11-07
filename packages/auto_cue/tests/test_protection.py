"""Tests for grid protection logic.

Tests that protected conditions result in no grid/cue writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from auto_cue.protection import (
    check_grid_protection,
    check_protection,
    decide_cue_write,
)
from auto_cue.tags import (
    CuePoint,
    Loop,
    Markers2Data,
    TrackTags,
)
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker


def make_track_tags(
    *,
    cues: list[CuePoint] | None = None,
    loops: list[Loop] | None = None,
    bpm_lock: bool = False,
    has_grid: bool = True,
    dynamic_grid: bool = False,
    error: str | None = None,
) -> TrackTags:
    """Create a TrackTags for testing."""
    markers2 = Markers2Data(
        cues=cues or [],
        loops=loops or [],
        bpm_lock=bpm_lock,
    )

    beatgrid = None
    if has_grid:
        if dynamic_grid:
            from serato_bpm_cleanup.beatgrid import NonTerminalMarker
            beatgrid = BeatGrid(
                markers=(
                    NonTerminalMarker(position_s=0.0, beats_till_next_marker=32),
                    TerminalMarker(position_s=15.0, bpm=128.0),
                )
            )
        else:
            beatgrid = BeatGrid(
                markers=(TerminalMarker(position_s=0.1, bpm=128.0),)
            )

    return TrackTags(
        path=Path("/test/track.mp3"),
        markers2=markers2,
        beatgrid=beatgrid,
        error=error,
    )


class TestProtectionWithHumanCues:
    """Test protection when human cues are present."""

    def test_track_with_human_cues_is_protected(self):
        """Track with human (non-MIK) cues should be protected."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="Intro")]
        )
        status = check_protection(tags)

        assert status.protected
        assert "has human cues" in status.reasons

    def test_track_with_blank_name_cues_is_protected(self):
        """Track with blank-name cues (human) should be protected."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="")]
        )
        status = check_protection(tags)

        assert status.protected
        assert "has human cues" in status.reasons

    def test_track_with_only_mik_cues_not_protected(self):
        """Track with only MIK cues should not be protected (can replace)."""
        tags = make_track_tags(
            cues=[
                CuePoint(index=0, position_ms=0, name="Energy 1"),
                CuePoint(index=1, position_ms=10000, name="Energy 2"),
            ]
        )
        status = check_protection(tags)

        assert not status.protected
        assert status.can_replace_mik

    def test_track_with_mixed_cues_is_protected(self):
        """Track with mixed MIK and human cues should be protected."""
        tags = make_track_tags(
            cues=[
                CuePoint(index=0, position_ms=0, name="Energy 1"),
                CuePoint(index=1, position_ms=10000, name="Drop"),
            ]
        )
        status = check_protection(tags)

        assert status.protected
        assert "has human cues" in status.reasons


class TestProtectionWithBPMLock:
    """Test protection when BPM lock is enabled."""

    def test_bpm_locked_track_is_protected(self):
        """BPM-locked track should be protected."""
        tags = make_track_tags(bpm_lock=True)
        status = check_protection(tags)

        assert status.protected
        assert "BPM locked" in status.reasons


class TestProtectionWithLoopsAndFlips:
    """Test protection when loops or flips are present."""

    def test_track_with_loops_is_protected(self):
        """Track with saved loops should be protected."""
        tags = make_track_tags(
            loops=[Loop(index=0, start_ms=0, end_ms=10000)]
        )
        status = check_protection(tags)

        assert status.protected
        assert "has loops" in status.reasons

    def test_track_with_flips_is_protected(self):
        """Track with flip entries should be protected."""
        tags = make_track_tags()
        tags.markers2.flip_entries = [b"\x00\x01\x02"]
        status = check_protection(tags)

        assert status.protected
        assert "has flips" in status.reasons


class TestProtectionWithDynamicGrid:
    """Test protection when dynamic (multi-marker) grid is present."""

    def test_dynamic_grid_is_protected(self):
        """Track with dynamic grid should be protected."""
        tags = make_track_tags(dynamic_grid=True)
        status = check_protection(tags)

        assert status.protected
        assert "dynamic (multi-marker) grid" in status.reasons


class TestProtectionWithTagErrors:
    """Test protection when tags have errors."""

    def test_tag_error_causes_protection(self):
        """Track with tag errors should be protected."""
        tags = make_track_tags(error="corrupted markers")
        status = check_protection(tags)

        assert status.protected
        assert "tag error" in str(status.reasons)


class TestGridProtection:
    """Test stricter grid protection rules."""

    def test_track_with_any_cues_has_protected_grid(self):
        """Track with any cues (even MIK) should have protected grid."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="Energy 1")]
        )

        cue_status = check_protection(tags)
        assert not cue_status.protected

        grid_status = check_grid_protection(tags)
        assert grid_status.protected
        assert "has existing cues" in str(grid_status.reasons)

    def test_empty_track_has_unprotected_grid(self):
        """Track with no cues should have unprotected grid."""
        tags = make_track_tags()

        grid_status = check_grid_protection(tags)
        assert not grid_status.protected


class TestCueWriteDecision:
    """Test cue write decision logic."""

    def test_empty_track_allows_write(self):
        """Empty track with grid should allow writes."""
        tags = make_track_tags()
        decision = decide_cue_write(tags)

        assert decision.should_write
        assert decision.action == "write"

    def test_human_cues_block_write(self):
        """Human cues should block writes."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="")]
        )
        decision = decide_cue_write(tags)

        assert not decision.should_write
        assert decision.action == "skip"

    def test_mik_cues_block_write_without_flag(self):
        """MIK cues should block writes without --replace-mik."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="Energy 1")]
        )
        decision = decide_cue_write(tags, replace_mik=False)

        assert not decision.should_write
        assert decision.action == "skip"

    def test_mik_cues_allow_write_with_flag(self):
        """MIK cues should allow writes with --replace-mik."""
        tags = make_track_tags(
            cues=[CuePoint(index=0, position_ms=0, name="Energy 1")]
        )
        decision = decide_cue_write(tags, replace_mik=True)

        assert decision.should_write
        assert decision.action == "replace-mik"

    def test_no_grid_causes_abstain(self):
        """Track without grid should abstain."""
        tags = make_track_tags(has_grid=False)
        decision = decide_cue_write(tags)

        assert not decision.should_write
        assert decision.action == "abstain"


class TestProtectedCratePaths:
    """Test protection based on crate membership."""

    def test_sets_crate_is_protected(self):
        """Track in Sets/ crate should be protected."""
        tags = make_track_tags()
        protected_paths = {"DJ Music/Spotify/track.mp3"}

        status = check_protection(
            tags,
            protected_paths=protected_paths,
            track_relative_path="DJ Music/Spotify/track.mp3",
        )

        assert status.protected
        assert "in protected crate" in status.reasons


class TestRealQAProtection:
    """Test protection on real QA songs."""

    def test_qa_songs_protection_status(self, qa_songs_dir):
        """Check protection status of QA songs based on cue type."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")

        from auto_cue.tags import read_track_tags

        human_cue_tracks = []
        mik_cue_tracks = []

        for mp3 in qa_songs_dir.glob("*.mp3"):
            tags = read_track_tags(mp3)
            status = check_protection(tags)

            if tags.markers2 and tags.markers2.has_human_cues():
                human_cue_tracks.append(mp3.name)
                assert status.protected, f"{mp3.name} with human cues should be protected"
            elif tags.markers2 and tags.markers2.all_mik_cues():
                mik_cue_tracks.append(mp3.name)
                msg = f"{mp3.name} with only MIK cues should not be protected"
                assert not status.protected, msg
                assert status.can_replace_mik, f"{mp3.name} should allow MIK replacement"

        print(f"\nHuman cue tracks: {human_cue_tracks}")
        print(f"MIK cue tracks: {mik_cue_tracks}")

    def test_qa_songs_grid_protected(self, qa_songs_dir):
        """QA songs with any cues should have protected grids."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")

        from auto_cue.tags import read_track_tags

        for mp3 in qa_songs_dir.glob("*.mp3"):
            tags = read_track_tags(mp3)
            grid_status = check_grid_protection(tags)

            assert grid_status.protected, f"{mp3.name} grid should be protected (has cues)"

    def test_dry_run_writes_nothing_on_qa(self, qa_songs_dir, temp_dir):
        """Dry-run should write nothing to QA files."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")

        import shutil

        from auto_cue.cli import process_track

        for mp3 in qa_songs_dir.glob("*.mp3"):
            copy_path = temp_dir / mp3.name
            shutil.copy2(mp3, copy_path)

            original_bytes = copy_path.read_bytes()

            result = process_track(copy_path, write=False, use_llm=False)

            msg = f"Expected skip for {mp3.name}, got {result.action}"
            assert result.action.startswith("skip"), msg

            new_bytes = copy_path.read_bytes()
            assert original_bytes == new_bytes, f"{mp3.name} was modified during dry-run"
