"""Tests for drive detection."""

import os
from unittest.mock import patch

from library_sync.mount import VOLUME_NAME, drive_is_mounted, find_drive


class TestFindDrive:
    def test_env_override(self, tmp_path):
        fake_drive = tmp_path / "fake_drive"
        fake_drive.mkdir()

        with patch.dict(os.environ, {"MUSIC_DRIVE_ROOT": str(fake_drive)}):
            result = find_drive()
            assert result == fake_drive

    def test_env_override_nonexistent(self, tmp_path):
        fake_drive = tmp_path / "nonexistent"

        with patch.dict(os.environ, {"MUSIC_DRIVE_ROOT": str(fake_drive)}):
            result = find_drive()
            assert result is None

    def test_explicit_path(self, tmp_path):
        fake_drive = tmp_path / "explicit"
        fake_drive.mkdir()

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
            result = find_drive(explicit=fake_drive)
            assert result == fake_drive

    def test_explicit_nonexistent(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
            result = find_drive(explicit=tmp_path / "nonexistent")
            assert result is None

    def test_returns_none_when_unmounted(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
            with patch("library_sync.mount._MACOS_VOLUME_PATH") as mock_path:
                mock_path.exists.return_value = False
                with patch("library_sync.mount.sys") as mock_sys:
                    mock_sys.platform = "linux"
                    result = find_drive()
                    assert result is None


class TestDriveIsMounted:
    def test_mounted(self, tmp_path):
        fake_drive = tmp_path / "mounted"
        fake_drive.mkdir()

        with patch.dict(os.environ, {"MUSIC_DRIVE_ROOT": str(fake_drive)}):
            assert drive_is_mounted() is True

    def test_not_mounted(self, tmp_path):
        with patch.dict(os.environ, {"MUSIC_DRIVE_ROOT": str(tmp_path / "gone")}):
            assert drive_is_mounted() is False


def test_volume_name():
    assert VOLUME_NAME == "Will Hunter Music"
