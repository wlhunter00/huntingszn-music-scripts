"""CLI path resolution and query/status without a mounted drive."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from library_sync.cli import (
    _resolve_db_path,
    cmd_detect,
    cmd_index,
    cmd_pull,
    cmd_query,
    cmd_query_projects,
    cmd_query_stems,
    cmd_status,
)
from library_sync.db import AbletonProject, LibraryDB, Stem, Track, utc_now_iso


def _seed_db(db_path: Path) -> None:
    with LibraryDB(db_path) as db:
        db.upsert_track(
            Track(
                id="t1",
                relative_path="DJ Music/halo.mp3",
                filename="halo.mp3",
                artist="Beyonce",
                title="Halo",
                bpm=128.0,
                camelot_key="5A",
                file_size=1,
                mtime=1.0,
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )
        db.upsert_stem(
            Stem(
                id="s1",
                relative_path="Stem Splitting/stem-output/htdemucs_ft/As It Was",
                song_name="As It Was",
                model="htdemucs_ft",
                has_vocals=1,
                updated_at=utc_now_iso(),
            )
        )
        db.upsert_ableton(
            AbletonProject(
                id="a1",
                relative_path="Ableton/HuntingSzn Mashup Template Project/Mashup.als",
                name="Mashup",
                folder="HuntingSzn Mashup Template Project",
                kind="template",
                updated_at=utc_now_iso(),
            )
        )


def test_resolve_db_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARY_SQLITE", str(tmp_path / "env.sqlite"))
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: tmp_path / "drive")
    explicit = tmp_path / "explicit.sqlite"
    assert _resolve_db_path(explicit) == explicit


def test_resolve_db_env_when_unmounted(tmp_path, monkeypatch):
    monkeypatch.delenv("MUSIC_DRIVE_ROOT", raising=False)
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    env_path = tmp_path / "from-env.sqlite"
    monkeypatch.setenv("LIBRARY_SQLITE", str(env_path))
    assert _resolve_db_path(None) == env_path


def test_detect_unmounted_exits_2(monkeypatch):
    monkeypatch.delenv("MUSIC_DRIVE_ROOT", raising=False)
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    assert cmd_detect(Namespace()) == 2


def test_index_unmounted_exits_2(monkeypatch):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    assert cmd_index(Namespace(root=None, dry_run=False)) == 2


def test_query_camelot_ignores_key_column(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    db_path = tmp_path / "library.sqlite"
    with LibraryDB(db_path) as db:
        db.upsert_track(
            Track(
                id="decoy",
                relative_path="DJ Music/decoy.mp3",
                filename="decoy.mp3",
                artist="Decoy",
                title="Key Column Decoy",
                bpm=140.0,
                key="8A",
                camelot_key=None,
                file_size=1,
                mtime=1.0,
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )
        db.upsert_track(
            Track(
                id="real",
                relative_path="DJ Music/real.mp3",
                filename="real.mp3",
                artist="Real",
                title="Camelot Hit",
                bpm=140.0,
                key=None,
                camelot_key="8A",
                file_size=1,
                mtime=1.0,
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )

    rc = cmd_query(
        Namespace(
            db=db_path, camelot="8A", bpm=140.0, q=None, role=None, limit=200, json=True
        )
    )
    assert rc == 0
    payload = capsys.readouterr().out
    assert "Camelot Hit" in payload
    assert "Key Column Decoy" not in payload


def test_pull_unmounted_exits_2(monkeypatch):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    assert cmd_pull(Namespace(root=None, dry_run=True)) == 2


def test_query_with_db_flag_without_drive(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MUSIC_DRIVE_ROOT", raising=False)
    monkeypatch.delenv("LIBRARY_SQLITE", raising=False)
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    db_path = tmp_path / "library.sqlite"
    _seed_db(db_path)

    rc = cmd_query(
        Namespace(db=db_path, camelot=None, bpm=None, q="halo", role=None, limit=200, json=False)
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Halo" in out
    assert "1 track(s) found" in out


def test_query_stems_and_projects_with_db_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    db_path = tmp_path / "library.sqlite"
    _seed_db(db_path)

    rc_stems = cmd_query_stems(
        Namespace(db=db_path, q="as it was", model=None, limit=200, json=True)
    )
    assert rc_stems == 0
    stems_out = capsys.readouterr().out
    assert "As It Was" in stems_out
    assert "htdemucs_ft" in stems_out

    rc_projects = cmd_query_projects(
        Namespace(db=db_path, q="mashup", kind="template", limit=200, json=False)
    )
    assert rc_projects == 0
    projects_out = capsys.readouterr().out
    assert "Mashup" in projects_out
    assert "1 project(s) found" in projects_out


def test_status_with_library_sqlite_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    db_path = tmp_path / "library.sqlite"
    _seed_db(db_path)
    monkeypatch.setenv("LIBRARY_SQLITE", str(db_path))

    rc = cmd_status(Namespace(db=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "not mounted" in out
    assert "Total: 1" in out
    assert "Stems" in out
    assert "Ableton" in out


def test_query_missing_db_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: None)
    monkeypatch.delenv("LIBRARY_SQLITE", raising=False)
    rc = cmd_query(
        Namespace(
            db=tmp_path / "missing.sqlite",
            camelot=None,
            bpm=None,
            q=None,
            role=None,
            limit=200,
            json=False,
        )
    )
    assert rc == 2


def test_index_all_catalogs_via_cli(tmp_path, monkeypatch, capsys):
    drive = tmp_path / "drive"
    dj = drive / "DJ Music"
    stems = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft" / "Song"
    als_dir = drive / "Ableton" / "Sessions"
    dj.mkdir(parents=True)
    stems.mkdir(parents=True)
    als_dir.mkdir(parents=True)
    (dj / "track.mp3").write_bytes(b"dj")
    (stems / "vocals.wav").write_bytes(b"v")
    (als_dir / "Live.als").write_bytes(b"als")
    (drive / "Ableton" / "Sessions" / "bounce.wav").write_bytes(b"not-a-track")

    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: drive)

    rc = cmd_index(Namespace(root=None, dry_run=False))
    assert rc == 0

    db_path = drive / "Scripts" / "data" / "library.sqlite"
    with LibraryDB(db_path, create=False) as db:
        tracks = db.query_tracks()
        assert {t.relative_path for t in tracks} == {"DJ Music/track.mp3"}
        assert db.count_stems(status="present") == 1
        assert db.count_ableton(status="present") == 1
