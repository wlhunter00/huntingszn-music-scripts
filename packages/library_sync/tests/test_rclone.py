"""Tests for rclone/B2 operations."""

import os
from pathlib import Path
from unittest.mock import patch

from library_sync.rclone import (
    PUBLISH_EXCLUDES,
    RcloneConfig,
    publish_drive,
    publish_sqlite,
    publish_template,
    pull_projects,
)


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

    def test_pull_projects_dry_run_no_subprocess(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        with patch("library_sync.rclone.subprocess") as mock_subprocess:
            cmd = pull_projects(drive_root, config, dry_run=True)
            mock_subprocess.run.assert_not_called()

        assert cmd is not None
        assert "Music Production Agent" in cmd or "projects" in cmd.lower()
        assert " copy " in f" {cmd} " or cmd.startswith("rclone copy")
        assert "sync" not in cmd


class TestPublishMode:
    def test_default_is_copy_not_sync(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config)
        assert any("rclone copy" in c for c in commands)
        assert not any("rclone sync" in c for c in commands)

    def test_allow_delete_uses_sync(self, tmp_path):
        drive_root = tmp_path / "drive"
        drive_root.mkdir()
        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)
        commands = publish_drive(drive_root, config, allow_delete=True)
        assert any("rclone sync" in c for c in commands)

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
                assert "boom" in str(exc)


class TestUnconfiguredB2:
    def test_shows_planned_commands(self, tmp_path, capsys):
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        config = RcloneConfig(remote=None, bucket=None, mashup_template_path=None)

        publish_drive(drive_root, config, dry_run=True)
        captured = capsys.readouterr()

        assert "no B2 configured" in captured.out.lower() or "planned" in captured.out.lower()


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
