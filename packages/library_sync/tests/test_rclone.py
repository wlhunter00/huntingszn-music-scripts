"""Tests for rclone/B2 operations."""

import argparse
import os
import shlex
from pathlib import Path
from unittest.mock import patch

import pytest
from library_sync.cli import parse_cli_limit
from library_sync.rclone import (
    PUBLISH_EXCLUDES,
    PULL_AGENT_PREFIXES,
    PULL_DRIVE_PRIMARY_PREFIXES,
    RcloneConfig,
    publish_drive,
    publish_sqlite,
    publish_template,
    pull_drive,
    pull_projects,
)


def _rclone_sources(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t.startswith("b2:")]


def _is_bucket_root_source(token: str) -> bool:
    if ":" not in token or token.startswith("-"):
        return False
    path = token.split(":", 1)[1].strip("/")
    return bool(path) and "/" not in path


def _assert_safe_pull_tokens(tokens: list[str]) -> None:
    assert tokens[0] == "rclone"
    assert tokens[1] == "copy"
    assert "--update" in tokens
    assert "--ignore-case" in tokens
    assert "sync" not in tokens
    assert "--delete" not in tokens
    assert "--allow-delete" not in tokens
    sources = _rclone_sources(tokens)
    assert sources
    assert not any(_is_bucket_root_source(s) for s in sources)
    joined = " ".join(sources)
    for prefix in PULL_DRIVE_PRIMARY_PREFIXES:
        assert prefix.rstrip("/") not in joined
    assert "DJ Music" not in joined


class TestRcloneConfig:
    def test_from_env_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            for k in ["B2_REMOTE", "B2_BUCKET", "MASHUP_TEMPLATE_PATH"]:
                os.environ.pop(k, None)
            config = RcloneConfig.from_env()
            assert config.remote is None
            assert config.bucket is None
            assert config.mashup_template_path is None
            assert not config.is_configured

    def test_from_env_configured(self):
        with patch.dict(
            os.environ,
            {
                "B2_REMOTE": "b2",
                "B2_BUCKET": "my-bucket",
                "MASHUP_TEMPLATE_PATH": "/path/to/template",
            },
        ):
            config = RcloneConfig.from_env()
            assert config.remote == "b2"
            assert config.bucket == "my-bucket"
            assert config.mashup_template_path == Path("/path/to/template")
            assert config.is_configured

    def test_partial_config_not_ready(self):
        with patch.dict(os.environ, {"B2_REMOTE": "b2"}, clear=True):
            os.environ.pop("B2_BUCKET", None)
            config = RcloneConfig.from_env()
            assert not config.is_configured

    def test_default_template_path_from_drive_root(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        with patch.dict(os.environ, {}, clear=True):
            for k in ["B2_REMOTE", "B2_BUCKET", "MASHUP_TEMPLATE_PATH"]:
                os.environ.pop(k, None)
            config = RcloneConfig.from_env(drive_root)
            expected = drive_root / "Ableton" / "HuntingSzn Mashup Template Project"
            assert config.mashup_template_path == expected


class TestPublishExcludes:
    def test_excludes_system_files(self):
        assert "$RECYCLE.BIN/**" in PUBLISH_EXCLUDES
        assert "$Recycle.Bin/**" in PUBLISH_EXCLUDES
        assert "System Volume Information/**" in PUBLISH_EXCLUDES
        assert ".Spotlight-V100/**" in PUBLISH_EXCLUDES
        assert ".TemporaryItems/**" in PUBLISH_EXCLUDES
        assert ".Trashes/**" in PUBLISH_EXCLUDES
        assert ".fseventsd/**" in PUBLISH_EXCLUDES
        assert ".DS_Store" in PUBLISH_EXCLUDES
        assert "._*" in PUBLISH_EXCLUDES
        assert ".git/**" in PUBLISH_EXCLUDES
        assert ".venv/**" in PUBLISH_EXCLUDES
        assert "**/__pycache__/**" in PUBLISH_EXCLUDES
        assert "**/Backup/**" in PUBLISH_EXCLUDES
        assert ".env" in PUBLISH_EXCLUDES
        assert ".env.*" in PUBLISH_EXCLUDES
        assert "**/.env" in PUBLISH_EXCLUDES
        assert "cookies.txt" in PUBLISH_EXCLUDES
        assert "*.pem" in PUBLISH_EXCLUDES
        assert "/Scripts/data/library.sqlite" in PUBLISH_EXCLUDES
        assert "/Scripts/data/library.sqlite-wal" in PUBLISH_EXCLUDES
        assert "/Scripts/data/library.sqlite-shm" in PUBLISH_EXCLUDES
        assert "/Scripts/data/library.sqlite-journal" in PUBLISH_EXCLUDES
        assert "/projects/**" in PUBLISH_EXCLUDES
        assert "/metadata/**" in PUBLISH_EXCLUDES
        assert "/templates/**" in PUBLISH_EXCLUDES


class TestPullAllowlist:
    def test_agent_prefixes_are_thumbnails_only(self):
        assert PULL_AGENT_PREFIXES == ("Thumbnails/",)
        assert "DJ Music/" not in PULL_AGENT_PREFIXES
        assert "Ableton/" not in PULL_AGENT_PREFIXES
        assert "metadata/" not in PULL_AGENT_PREFIXES
        assert "templates/" not in PULL_AGENT_PREFIXES

    def test_drive_primary_trees_are_not_pull_sources(self):
        assert "DJ Music/" in PULL_DRIVE_PRIMARY_PREFIXES
        assert "Platnium Notes/" in PULL_DRIVE_PRIMARY_PREFIXES
        assert "Stem Splitting/" in PULL_DRIVE_PRIMARY_PREFIXES
        assert "Set Recording/" in PULL_DRIVE_PRIMARY_PREFIXES
        assert "Scripts/" in PULL_DRIVE_PRIMARY_PREFIXES
        assert "Ableton/" in PULL_DRIVE_PRIMARY_PREFIXES


class TestDryRun:
    def test_publish_drive_dry_run_no_subprocess(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        with patch("library_sync.rclone.subprocess") as mock_subprocess:
            commands = publish_drive(drive_root, config, dry_run=True)
            mock_subprocess.run.assert_not_called()

        captured = capsys.readouterr()
        assert "planned command" in captured.out.lower() or len(commands) > 0

    def test_publish_sqlite_dry_run_no_subprocess(self, tmp_path, capsys):
        db_path = tmp_path / "library.sqlite"
        db_path.write_bytes(b"fake sqlite")

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        with patch("library_sync.rclone.subprocess") as mock_subprocess:
            cmd = publish_sqlite(db_path, config, dry_run=True)
            mock_subprocess.run.assert_not_called()

        assert cmd is not None

    def test_pull_drive_dry_run_no_subprocess(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        with patch("library_sync.rclone.subprocess") as mock_subprocess:
            commands = pull_drive(drive_root, config, dry_run=True)
            mock_subprocess.run.assert_not_called()

        assert len(commands) == 2
        for cmd in commands:
            _assert_safe_pull_tokens(shlex.split(cmd))

        thumb_tokens = shlex.split(commands[0])
        assert any(t.endswith("/Thumbnails/") for t in thumb_tokens)
        assert str(drive_root / "Thumbnails") in thumb_tokens
        assert str(drive_root) not in thumb_tokens

        remap_tokens = shlex.split(commands[1])
        assert any(t.endswith("/projects/") for t in remap_tokens)
        assert str(drive_root / "Ableton" / "Music Production Agent") in remap_tokens


class TestPublishMode:
    def test_default_is_copy_not_sync(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config)
        tokens = shlex.split(commands[0])
        assert tokens[1] == "copy"
        assert "sync" not in tokens
        assert "--update" not in tokens
        assert "--progress" in tokens
        assert "--ignore-case" in tokens
        assert "$RECYCLE.BIN/**" in tokens
        assert "$Recycle.Bin/**" in tokens
        assert "._*" in tokens
        assert "/Scripts/data/library.sqlite-journal" in tokens

    def test_update_flag_is_copy_update_not_sync(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config, update=True)
        tokens = shlex.split(commands[0])
        assert tokens[1] == "copy"
        assert "--update" in tokens
        assert "sync" not in tokens
        assert "--allow-delete" not in tokens

    def test_progress_false_omits_progress_flag(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config, update=True, progress=False)
        tokens = shlex.split(commands[0])
        assert tokens[1] == "copy"
        assert "--update" in tokens
        assert "--progress" not in tokens

    def test_allow_delete_uses_sync(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config, allow_delete=True)
        assert any("rclone sync" in c for c in commands)
        assert all("--update" not in c for c in commands)
        tokens = shlex.split(commands[0])
        assert "/projects/**" in tokens
        assert "/metadata/**" in tokens
        assert "/templates/**" in tokens
        assert "--ignore-case" in tokens
        assert "$Recycle.Bin/**" in tokens

    def test_planned_command_quotes_spaces(self, tmp_path):
        drive_root = tmp_path / "Will Hunter Music"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config)
        tokens = shlex.split(commands[0])
        assert str(drive_root) in tokens

    def test_configured_run_raises_on_rclone_failure(self, tmp_path):
        from library_sync.rclone import RcloneError, _run_rclone

        fake = type("R", (), {})()
        fake.returncode = 1
        fake.stderr = "boom"
        fake.stdout = ""
        with patch("library_sync.rclone.subprocess.run", return_value=fake):
            try:
                _run_rclone(["copy", "a", "b"])
                raise AssertionError("expected RcloneError")
            except RcloneError as exc:
                assert exc.returncode == 1
                assert "see rclone output above" in str(exc)

    def test_missing_rclone_binary(self):
        from library_sync.rclone import RcloneError, _run_rclone

        with patch("library_sync.rclone.subprocess.run", side_effect=FileNotFoundError("rclone")):
            try:
                _run_rclone(["copy", "a", "b"])
                raise AssertionError("expected RcloneError")
            except RcloneError as exc:
                assert exc.returncode == 127
                assert "rclone not found" in str(exc)

    def test_oserror_starting_rclone(self):
        from library_sync.rclone import RcloneError, _run_rclone

        with patch(
            "library_sync.rclone.subprocess.run",
            side_effect=OSError(6, "The handle is invalid"),
        ):
            try:
                _run_rclone(["copy", "a", "b"])
                raise AssertionError("expected RcloneError")
            except RcloneError as exc:
                assert exc.returncode == 127
                assert "handle is invalid" in str(exc)


class TestUnconfiguredB2:
    def test_shows_planned_commands(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        publish_drive(drive_root, config, dry_run=True)
        captured = capsys.readouterr()

        assert "no B2 configured" in captured.out.lower() or "planned" in captured.out.lower()


class TestPullDestination:
    def test_pull_is_allowlisted_copy_update_never_delete(self, tmp_path):
        drive_root = tmp_path / "Will Hunter Music"
        drive_root.mkdir()
        config = RcloneConfig(remote="b2", bucket="huntingszn-music", mashup_template_path=None)
        captured: list[list[str]] = []

        class _Result:
            returncode = 0

        def fake_run(cmd, check=False):
            captured.append(cmd)
            return _Result()

        with patch("library_sync.rclone.subprocess.run", side_effect=fake_run):
            commands = pull_drive(drive_root, config, dry_run=False)

        assert len(captured) == 2
        assert len(commands) == 2
        for args in captured:
            _assert_safe_pull_tokens(args)

        thumb_args = captured[0]
        assert "b2:huntingszn-music/Thumbnails/" in thumb_args
        assert str(drive_root / "Thumbnails") in thumb_args
        assert str(drive_root) not in thumb_args
        assert "b2:huntingszn-music/" not in thumb_args
        assert (drive_root / "Thumbnails").is_dir()

        remap_args = captured[1]
        dest = drive_root / "Ableton" / "Music Production Agent"
        assert "b2:huntingszn-music/projects/" in remap_args
        assert str(dest) in remap_args
        assert dest.is_dir()

    def test_pull_does_not_target_dj_music_or_bucket_root(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote="b2", bucket="huntingszn-music", mashup_template_path=None)
        captured: list[list[str]] = []

        class _Result:
            returncode = 0

        def fake_run(cmd, check=False):
            captured.append(cmd)
            return _Result()

        with patch("library_sync.rclone.subprocess.run", side_effect=fake_run):
            pull_drive(drive_root, config, dry_run=False)

        all_args = [tok for args in captured for tok in args]
        assert "DJ Music" not in " ".join(all_args)
        assert not any(_is_bucket_root_source(t) for t in all_args)
        assert "b2:huntingszn-music/DJ Music/" not in all_args

    def test_pull_thumbnails_land_one_to_one(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = pull_drive(drive_root, config, dry_run=True)
        thumb_tokens = shlex.split(commands[0])
        # rclone copy remote:bucket/Thumbnails/ {DRIVE}/Thumbnails/
        # copies Releases/03-finals/... and root prompt txts 1:1.
        sources = _rclone_sources(thumb_tokens)
        assert sources == ["b2:BUCKET/Thumbnails/"]
        assert str(drive_root / "Thumbnails") in thumb_tokens
        assert str(drive_root) not in thumb_tokens

    def test_pull_projects_remaps_into_music_production_agent(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = pull_drive(drive_root, config, dry_run=True)
        remap_tokens = shlex.split(commands[1])
        _assert_safe_pull_tokens(remap_tokens)
        # rclone copy remote:bucket/projects/ dest/ copies projects/<slug>/
        # into Ableton/Music Production Agent/<slug>/. Sole writer of that dest.
        assert any(t.endswith("/projects/") for t in remap_tokens)
        assert str(drive_root / "Ableton" / "Music Production Agent") in remap_tokens
        assert not any(t.endswith("Ready to Mix") for t in remap_tokens)

    def test_first_pull_rclone_failure_does_not_start_remap(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote="b2", bucket="huntingszn-music", mashup_template_path=None)
        captured: list[list[str]] = []

        def fake_run(cmd, check=False):
            captured.append(cmd)
            raise FileNotFoundError("rclone")

        with patch("library_sync.rclone.subprocess.run", side_effect=fake_run):
            try:
                pull_drive(drive_root, config, dry_run=False)
                raise AssertionError("expected RcloneError")
            except Exception as exc:
                from library_sync.rclone import RcloneError

                assert isinstance(exc, RcloneError)
        assert len(captured) == 1
        assert "Thumbnails/" in captured[0][-2] or any(
            "Thumbnails/" in t for t in captured[0]
        )
        assert not any("/projects/" in t for t in captured[0])

    def test_pull_projects_alone_is_copy_update_into_ableton(self, tmp_path):
        drive_root = tmp_path / "Will Hunter Music"
        drive_root.mkdir()
        config = RcloneConfig(remote="b2", bucket="library", mashup_template_path=None)
        captured: list[list[str]] = []

        class _Result:
            returncode = 0

        def fake_run(cmd, check=False):
            captured.append(cmd)
            return _Result()

        with patch("library_sync.rclone.subprocess.run", side_effect=fake_run):
            cmd = pull_projects(drive_root, config, dry_run=False)

        assert captured
        args = captured[0]
        _assert_safe_pull_tokens(args)
        assert "b2:library/projects/" in args
        dest = drive_root / "Ableton" / "Music Production Agent"
        assert str(dest) in args
        assert dest.is_dir()
        assert cmd is not None


class TestPublishTemplate:
    def test_no_template_path(self):
        config = RcloneConfig(remote="b2", bucket="bucket", mashup_template_path=None)
        result = publish_template(config, dry_run=True)
        assert result is None

    def test_template_path_not_exists(self, tmp_path):
        config = RcloneConfig(
            remote="b2",
            bucket="bucket",
            mashup_template_path=tmp_path / "nonexistent",
        )
        result = publish_template(config, dry_run=True)
        assert result is None

    def test_template_path_exists(self, tmp_path, capsys):
        template_path = tmp_path / "template"
        template_path.mkdir()

        config = RcloneConfig(
            remote=None,
            bucket=None,
            mashup_template_path=template_path,
        )

        with patch("library_sync.rclone.subprocess"):
            result = publish_template(config, dry_run=True)

        assert result is not None
        assert "templates/mashup" in result
        assert "**/Backup/**" in result
        assert "--ignore-case" in result


class TestCliLimit:
    def test_zero_and_positive(self):
        assert parse_cli_limit("0") == 0
        assert parse_cli_limit("200") == 200

    def test_rejects_negative(self):
        with pytest.raises(argparse.ArgumentTypeError, match=">= 0"):
            parse_cli_limit("-1")
