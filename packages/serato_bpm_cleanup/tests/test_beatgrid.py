import pytest
from serato_bpm_cleanup.beatgrid import (
    BeatGrid,
    NonTerminalMarker,
    TerminalMarker,
    dump_beatgrid,
    parse_beatgrid,
)


def test_roundtrip_constant_grid():
    original = BeatGrid(markers=(TerminalMarker(position_s=0.215, bpm=128.31),), footer=0x37)
    blob = dump_beatgrid(original)
    parsed = parse_beatgrid(blob)
    assert parsed.is_constant
    assert parsed.bpm == pytest.approx(128.31)
    assert parsed.first_beat_s == pytest.approx(0.215)
    assert parsed.footer == 0x37


def test_rewrite_keeps_offset():
    grid = BeatGrid(markers=(TerminalMarker(position_s=0.215, bpm=128.31),), footer=0x37)
    rewritten = grid.with_constant_bpm(128)
    assert rewritten.first_beat_s == pytest.approx(0.215)
    assert rewritten.bpm == pytest.approx(128.0)
    assert rewritten.footer == 0x37


def test_dynamic_grid_refuses_rewrite():
    grid = BeatGrid(
        markers=(
            NonTerminalMarker(position_s=0.0, beats_till_next_marker=4),
            TerminalMarker(position_s=1.875, bpm=128.31),
        )
    )
    assert grid.is_dynamic
    with pytest.raises(ValueError, match="dynamic"):
        grid.with_constant_bpm(128)
