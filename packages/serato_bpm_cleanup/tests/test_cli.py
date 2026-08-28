from pathlib import Path

from serato_bpm_cleanup.cli import build_parser, main
from serato_bpm_cleanup.tags import read_track

from .fixtures import make_track


def test_help_documents_dry_run_and_write():
    help_text = build_parser().format_help()
    lowered = help_text.lower()
    assert "dry-run" in lowered
    assert "--write" in help_text
    assert "close serato" in lowered or "serato dj" in lowered
    assert "Markers2" in help_text or "cues" in help_text.lower()


def test_cli_dry_run_does_not_write(tmp_path: Path, capsys, monkeypatch):
    make_track(tmp_path, "a.mp3", bpm=128.31, cues=0)
    make_track(tmp_path, "b.mp3", bpm=128.31, cues=2)
    make_track(tmp_path, "c.mp3", bpm=128.00, cues=0)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.mp3")}
    monkeypatch.setattr("serato_bpm_cleanup.cli.serato_is_running", lambda: False)
    csv_path = tmp_path / "out.csv"
    code = main(["--library", str(tmp_path), "--csv", str(csv_path)])
    assert code == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "WARNING" in captured.err
    assert "Close Serato" in captured.err
    assert "128.31" in combined
    assert "skip-has-cues" in captured.out
    assert "Has cues, left alone" in captured.out
    assert csv_path.is_file()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "fix" in csv_text
    assert "skip-has-cues" in csv_text
    assert "skip-already-integer" in csv_text
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.mp3")} == before


def test_cli_write_refuses_if_serato_running(tmp_path: Path, monkeypatch):
    path = make_track(tmp_path, "a.mp3", bpm=128.31, cues=0)
    before = path.read_bytes()
    monkeypatch.setattr("serato_bpm_cleanup.cli.serato_is_running", lambda: True)
    code = main(["--library", str(tmp_path), "--write"])
    assert code == 1
    assert path.read_bytes() == before


def test_cli_write_fixes_and_skips_cues(tmp_path: Path, monkeypatch):
    a = make_track(tmp_path, "a.mp3", bpm=128.31, cues=0, first_beat_s=0.215)
    b = make_track(tmp_path, "b.mp3", bpm=128.31, cues=2)
    c = make_track(tmp_path, "c.mp3", bpm=128.00, cues=0)
    b_before = b.read_bytes()
    c_before = c.read_bytes()
    monkeypatch.setattr("serato_bpm_cleanup.cli.serato_is_running", lambda: False)
    backup = tmp_path / "bak"
    code = main(["--library", str(tmp_path), "--write", "--backup-dir", str(backup)])
    assert code == 0
    assert read_track(a).serato_bpm == 128.0
    grid = read_track(a).beatgrid
    assert grid is not None
    assert abs(grid.first_beat_s - 0.215) < 1e-5
    assert b.read_bytes() == b_before
    assert c.read_bytes() == c_before
    assert any(backup.rglob("a.mp3"))
