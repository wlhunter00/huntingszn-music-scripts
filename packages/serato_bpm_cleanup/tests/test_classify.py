from pathlib import Path

import pytest
from serato_bpm_cleanup import ACTION_FIX, ACTION_SKIP_ALREADY_INTEGER, ACTION_SKIP_HAS_CUES
from serato_bpm_cleanup.classify import classify_track
from serato_bpm_cleanup.tags import read_track

from .fixtures import make_track


def test_golden_a_fractional_no_cues(tmp_path: Path):
    path = make_track(tmp_path, "a.mp3", bpm=128.31, cues=0)
    report = classify_track(read_track(path))
    assert report.action == ACTION_FIX
    assert report.current_bpm == pytest.approx(128.31, abs=0.001)
    assert report.proposed_bpm == 128
    assert report.cue_count == 0
    assert "Serato BeatGrid" in report.rewrites


def test_golden_b_fractional_with_cues(tmp_path: Path):
    path = make_track(tmp_path, "b.mp3", bpm=128.31, cues=2)
    report = classify_track(read_track(path))
    assert report.action == ACTION_SKIP_HAS_CUES
    assert report.cue_count == 2
    assert report.proposed_bpm == 128
    assert report.rewrites == ""


def test_golden_c_already_integer(tmp_path: Path):
    path = make_track(tmp_path, "c.mp3", bpm=128.00, cues=0)
    report = classify_track(read_track(path))
    assert report.action == ACTION_SKIP_ALREADY_INTEGER
    assert report.cue_count == 0
    assert report.proposed_bpm == 128


def test_loop_is_a_cue(tmp_path: Path):
    path = make_track(tmp_path, "loop.mp3", bpm=128.31, loop=True)
    report = classify_track(read_track(path))
    assert report.action == ACTION_SKIP_HAS_CUES
    assert report.cue_count == 1


def test_id3_comm_is_not_a_cue(tmp_path: Path):
    path = make_track(tmp_path, "comm.mp3", bpm=128.31, cues=0, comment="hot cue 1 at 128.31")
    report = classify_track(read_track(path))
    assert report.cue_count == 0
    assert report.action == ACTION_FIX
