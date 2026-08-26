from serato_bpm_cleanup.markers import (
    combine_marker_counts,
    parse_markers2_counts,
    parse_markers_v1_counts,
)

from .fixtures import empty_markers2, markers2_with_cues, markers2_with_loop


def test_empty_markers2_zero_cues():
    counts = parse_markers2_counts(empty_markers2())
    assert counts.cues == 0
    assert counts.loops == 0
    assert counts.total == 0


def test_two_hot_cues():
    counts = parse_markers2_counts(markers2_with_cues(2))
    assert counts.cues == 2
    assert counts.loops == 0
    assert counts.total == 2


def test_loop_counts_as_cue():
    counts = parse_markers2_counts(markers2_with_loop())
    assert counts.loops == 1
    assert counts.total == 1


def test_markers_v1_set_cue_slot():
    # version 02 05, 14 slots, first slot is a set cue (type 1)
    header = b"\x02\x05" + b"\x00\x00\x00\x0e"
    set_cue = bytearray(b"\x7f" * 22)
    set_cue[0] = 0x00  # start set
    set_cue[20] = 0x01  # cue
    unused_loop = bytearray(b"\x7f" * 22)
    unused_loop[20] = 0x03
    body = bytes(set_cue) + bytes(unused_loop) * 13
    footer = b"\x07\x7f\x7f\x7f"
    counts = parse_markers_v1_counts(header + body + footer)
    assert counts.cues == 1
    assert counts.loops == 0


def test_combine_takes_max():
    from serato_bpm_cleanup.markers import MarkerCounts

    combined = combine_marker_counts(MarkerCounts(cues=2, loops=0), MarkerCounts(cues=0, loops=1))
    assert combined.cues == 2
    assert combined.loops == 1
    assert combined.total == 3
