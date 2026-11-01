"""Tests for Serato tag read/write round-trips.

Tests:
1. Markers2 parse/encode round-trip for MP3 and FLAC
2. BeatGrid parse/encode round-trip
3. Write then re-read produces identical data
4. Untouched fields are preserved
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from auto_cue.tags import (
    CuePoint,
    Loop,
    Markers2Data,
    parse_markers2,
    encode_markers2,
    read_track_tags,
    write_track_markers2,
    write_track_beatgrid,
    SERATO_DEFAULT_COLORS,
)
from serato_bpm_cleanup.beatgrid import (
    BeatGrid,
    TerminalMarker,
    parse_beatgrid,
    dump_beatgrid,
)


class TestMarkers2ParseEncode:
    """Test Markers2 parse/encode round-trips."""

    def test_empty_markers2_roundtrip(self):
        """Empty markers should round-trip."""
        markers = Markers2Data()
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert decoded.cues == []
        assert decoded.loops == []
        assert decoded.bpm_lock is False

    def test_single_cue_roundtrip(self):
        """Single cue should round-trip with exact values."""
        markers = Markers2Data(
            cues=[CuePoint(index=0, position_ms=1000, color=(0xCC, 0x00, 0x00), name="")]
        )
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert len(decoded.cues) == 1
        assert decoded.cues[0].index == 0
        assert decoded.cues[0].position_ms == 1000
        assert decoded.cues[0].color == (0xCC, 0x00, 0x00)

    def test_all_eight_cues_roundtrip(self):
        """All 8 cues with different positions should round-trip."""
        cues = []
        for i in range(8):
            cues.append(CuePoint(
                index=i,
                position_ms=i * 10000,
                color=SERATO_DEFAULT_COLORS[i],
                name="",
            ))
        
        markers = Markers2Data(cues=cues)
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert len(decoded.cues) == 8
        for i, cue in enumerate(decoded.cues):
            assert cue.index == i
            assert cue.position_ms == i * 10000
            assert cue.color == SERATO_DEFAULT_COLORS[i]

    def test_cue_with_name_roundtrip(self):
        """Cue with name should preserve name."""
        markers = Markers2Data(
            cues=[CuePoint(index=3, position_ms=5000, name="Drop")]
        )
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert decoded.cues[0].name == "Drop"

    def test_loop_roundtrip(self):
        """Loops should round-trip."""
        markers = Markers2Data(
            loops=[Loop(index=0, start_ms=1000, end_ms=5000, locked=True)]
        )
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert len(decoded.loops) == 1
        assert decoded.loops[0].start_ms == 1000
        assert decoded.loops[0].end_ms == 5000
        assert decoded.loops[0].locked is True

    def test_bpm_lock_roundtrip(self):
        """BPM lock should round-trip."""
        markers = Markers2Data(bpm_lock=True)
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert decoded.bpm_lock is True

    def test_track_color_roundtrip(self):
        """Track color should round-trip."""
        markers = Markers2Data(track_color=(0x12, 0x34, 0x56))
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert decoded.track_color == (0x12, 0x34, 0x56)

    def test_complex_markers_roundtrip(self):
        """Complex markers with all features should round-trip."""
        markers = Markers2Data(
            cues=[
                CuePoint(index=0, position_ms=0, name="Intro"),
                CuePoint(index=3, position_ms=30000, name="Drop"),
                CuePoint(index=7, position_ms=90000, name="Outro"),
            ],
            loops=[
                Loop(index=0, start_ms=30000, end_ms=60000),
            ],
            track_color=(0xFF, 0x00, 0xFF),
            bpm_lock=True,
        )
        encoded = encode_markers2(markers)
        decoded = parse_markers2(encoded)
        
        assert len(decoded.cues) == 3
        assert len(decoded.loops) == 1
        assert decoded.track_color == (0xFF, 0x00, 0xFF)
        assert decoded.bpm_lock is True


class TestBeatGridRoundtrip:
    """Test BeatGrid parse/encode round-trips."""

    def test_constant_grid_roundtrip(self):
        """Constant (single-marker) grid should round-trip."""
        grid = BeatGrid(
            markers=(TerminalMarker(position_s=0.215, bpm=128.0),),
            footer=0x37,
        )
        encoded = dump_beatgrid(grid)
        decoded = parse_beatgrid(encoded)
        
        assert decoded.is_constant
        assert decoded.bpm == pytest.approx(128.0)
        assert decoded.first_beat_s == pytest.approx(0.215)
        assert decoded.footer == 0x37


class TestMP3WriteReadRoundtrip:
    """Test write then read on MP3 files."""

    def test_write_markers2_then_read(self, sample_mp3: Path):
        """Written markers should be readable."""
        markers = Markers2Data(
            cues=[
                CuePoint(index=0, position_ms=0),
                CuePoint(index=3, position_ms=30000),
                CuePoint(index=5, position_ms=60000),
            ]
        )
        
        write_track_markers2(sample_mp3, markers)
        
        tags = read_track_tags(sample_mp3)
        assert tags.markers2 is not None
        assert len(tags.markers2.cues) == 3
        assert tags.markers2.cues[0].position_ms == 0
        assert tags.markers2.cues[1].position_ms == 30000
        assert tags.markers2.cues[2].position_ms == 60000

    def test_write_beatgrid_then_read(self, sample_mp3: Path):
        """Written beatgrid should be readable."""
        grid = BeatGrid(
            markers=(TerminalMarker(position_s=0.1, bpm=126.0),),
        )
        
        write_track_beatgrid(sample_mp3, grid)
        
        tags = read_track_tags(sample_mp3)
        assert tags.beatgrid is not None
        assert tags.beatgrid.bpm == pytest.approx(126.0)
        assert tags.beatgrid.first_beat_s == pytest.approx(0.1)

    def test_preserve_existing_markers_on_grid_write(self, sample_mp3: Path):
        """Writing beatgrid should preserve existing markers."""
        markers = Markers2Data(
            cues=[CuePoint(index=0, position_ms=5000)],
            bpm_lock=True,
        )
        write_track_markers2(sample_mp3, markers)
        
        grid = BeatGrid(markers=(TerminalMarker(position_s=0.2, bpm=128.0),))
        write_track_beatgrid(sample_mp3, grid)
        
        tags = read_track_tags(sample_mp3)
        assert tags.markers2 is not None
        assert len(tags.markers2.cues) == 1
        assert tags.markers2.bpm_lock is True
        assert tags.beatgrid is not None
        assert tags.beatgrid.bpm == pytest.approx(128.0)


class TestFLACWriteReadRoundtrip:
    """Test write then read on FLAC files."""

    def test_write_markers2_then_read(self, sample_flac: Path):
        """Written markers should be readable from FLAC."""
        markers = Markers2Data(
            cues=[
                CuePoint(index=0, position_ms=0),
                CuePoint(index=3, position_ms=30000),
            ]
        )
        
        write_track_markers2(sample_flac, markers)
        
        tags = read_track_tags(sample_flac)
        assert tags.markers2 is not None
        assert len(tags.markers2.cues) == 2

    def test_write_beatgrid_then_read(self, sample_flac: Path):
        """Written beatgrid should be readable from FLAC."""
        grid = BeatGrid(
            markers=(TerminalMarker(position_s=0.15, bpm=140.0),),
        )
        
        write_track_beatgrid(sample_flac, grid)
        
        tags = read_track_tags(sample_flac)
        assert tags.beatgrid is not None
        assert tags.beatgrid.bpm == pytest.approx(140.0)


class TestRealQASongs:
    """Test tag operations on real QA songs (if available)."""

    def test_read_real_mp3_tags(self, qa_songs_dir: Path | None):
        """Read tags from real QA MP3 files."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")
        
        mp3_files = list(qa_songs_dir.glob("*.mp3"))
        assert len(mp3_files) > 0, "No MP3 files in QA directory"
        
        for mp3 in mp3_files:
            tags = read_track_tags(mp3)
            assert tags.error is None, f"Error reading {mp3.name}: {tags.error}"
            assert tags.markers2 is not None, f"No markers2 in {mp3.name}"
            assert tags.beatgrid is not None, f"No beatgrid in {mp3.name}"
            assert len(tags.markers2.cues) == 8, f"Expected 8 cues in {mp3.name}, got {len(tags.markers2.cues)}"
            assert tags.beatgrid.is_constant, f"Expected constant grid in {mp3.name}"

    def test_roundtrip_on_copy(self, qa_songs_dir: Path | None, temp_dir: Path):
        """Write/read roundtrip on copies of real files."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")
        
        mp3_files = list(qa_songs_dir.glob("*.mp3"))[:1]
        
        for mp3 in mp3_files:
            copy_path = temp_dir / mp3.name
            shutil.copy2(mp3, copy_path)
            
            original_tags = read_track_tags(copy_path)
            assert original_tags.markers2 is not None
            
            write_track_markers2(copy_path, original_tags.markers2)
            
            reread_tags = read_track_tags(copy_path)
            assert reread_tags.markers2 is not None
            
            assert len(reread_tags.markers2.cues) == len(original_tags.markers2.cues)
            for orig, reread in zip(original_tags.markers2.cues, reread_tags.markers2.cues):
                assert orig.index == reread.index
                assert orig.position_ms == reread.position_ms
