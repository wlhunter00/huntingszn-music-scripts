from pathlib import Path

from serato_bpm_cleanup import ACTION_FIX, ACTION_SKIP_HAS_CUES
from serato_bpm_cleanup.beatgrid import parse_beatgrid
from serato_bpm_cleanup.classify import classify_track
from serato_bpm_cleanup.process import apply_fix, inspect_library
from serato_bpm_cleanup.tags import BEATGRID_GEOB, read_track

from .fixtures import id3_geob, make_track


def _fingerprint(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in folder.glob("*.mp3")}


def test_dry_run_never_mutates(tmp_path: Path):
    make_track(tmp_path, "a.mp3", bpm=128.31, cues=0)
    make_track(tmp_path, "b.mp3", bpm=128.31, cues=2)
    make_track(tmp_path, "c.mp3", bpm=128.00, cues=0)
    before = _fingerprint(tmp_path)
    reports = inspect_library([tmp_path])
    assert {r.path.name: r.action for r in reports} == {
        "a.mp3": ACTION_FIX,
        "b.mp3": ACTION_SKIP_HAS_CUES,
        "c.mp3": "skip-already-integer",
    }
    assert _fingerprint(tmp_path) == before


def test_write_updates_constant_grid_keeps_offset(tmp_path: Path):
    path = make_track(tmp_path, "a.mp3", bpm=128.31, cues=0, first_beat_s=0.215)
    report = classify_track(read_track(path))
    backup = tmp_path / "backups"
    stores = apply_fix(report, backup_root=backup, library_root=tmp_path)
    assert "Serato BeatGrid" in stores
    assert "Serato Autotags" in stores
    assert "TBPM" in stores
    assert (backup / "a.mp3").is_file()

    data = read_track(path)
    assert data.cue_count == 0
    assert data.serato_bpm == 128.0
    grid = parse_beatgrid(id3_geob(path, BEATGRID_GEOB))
    assert grid.bpm == 128.0
    assert abs(grid.first_beat_s - 0.215) < 1e-5


def test_write_noops_when_cues_present(tmp_path: Path):
    path = make_track(tmp_path, "b.mp3", bpm=128.31, cues=2)
    before = path.read_bytes()
    report = classify_track(read_track(path))
    assert report.action == ACTION_SKIP_HAS_CUES
    assert apply_fix(report, backup_root=tmp_path / "backups", library_root=tmp_path) == []
    assert path.read_bytes() == before
