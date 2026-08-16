"""Tests for drive detection."""

import os
from unittest.mock import patch

from library_sync.mount import (
    _MACOS_VOLUME_PATHS,
    VOLUME_NAME,
    VOLUME_NAME_ALT,
    VOLUME_NAMES,
    _find_windows_volume,
    _iter_logical_drive_letters,
    _wmic_drive_letter_for_music_volume,
    drive_is_mounted,
    find_drive,
)


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
            with patch("library_sync.mount.sys") as mock_sys:
                mock_sys.platform = "linux"
                result = find_drive()
                assert result is None

    def test_stale_env_falls_through_to_windows_volume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(tmp_path / "not-mounted"))
        found = tmp_path / "HuntingSzn"
        found.mkdir()
        monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
        monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: found)
        monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
        assert find_drive() == found

    def test_stale_env_falls_through_to_macos_volume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(tmp_path / "not-mounted"))
        vol = tmp_path / "HuntingSzn"
        vol.mkdir()
        monkeypatch.setattr("library_sync.mount.sys.platform", "darwin")
        monkeypatch.setattr("library_sync.mount._MACOS_VOLUME_PATHS", [vol])
        assert find_drive() == vol

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

    def test_explicit_path_wins_over_env(self, tmp_path):
        env_drive = tmp_path / "env_drive"
        explicit = tmp_path / "explicit"
        env_drive.mkdir()
        explicit.mkdir()

        with patch.dict(os.environ, {"MUSIC_DRIVE_ROOT": str(env_drive)}):
            result = find_drive(explicit=explicit)
            assert result == explicit

    def test_returns_none_when_unmounted(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
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


def test_volume_name_alt():
    assert VOLUME_NAME_ALT == "HuntingSzn"


def test_volume_names_tuple():
    assert VOLUME_NAMES == ("Will Hunter Music", "HuntingSzn")


def test_macos_volume_paths_include_alias():
    assert {str(path) for path in _MACOS_VOLUME_PATHS} == {
        "/Volumes/Will Hunter Music",
        "/Volumes/HuntingSzn",
    }


class TestWmicVolumeParse:
    def test_will_hunter_music(self):
        assert _wmic_drive_letter_for_music_volume("D:         Will Hunter Music") == "D:"

    def test_huntingszn_alias(self):
        assert _wmic_drive_letter_for_music_volume("E:          HuntingSzn") == "E:"

    def test_other_volume(self):
        assert _wmic_drive_letter_for_music_volume("C:         Windows") is None

    def test_header_line(self):
        assert _wmic_drive_letter_for_music_volume("Name  VolumeName") is None


def test_iter_logical_drive_letters_uses_bitmask():
    assert list(_iter_logical_drive_letters(0)) == []
    assert list(_iter_logical_drive_letters(0b0100)) == ["C"]
    assert list(_iter_logical_drive_letters(0b1100)) == ["C", "D"]


def test_windows_volume_falls_back_to_ctypes_when_wmic_missing(tmp_path, monkeypatch):
    fake = tmp_path / "HuntingSzn"
    fake.mkdir()

    def boom(*_a, **_k):
        raise FileNotFoundError("wmic")

    monkeypatch.setattr("library_sync.mount.subprocess.run", boom)
    monkeypatch.setattr("library_sync.mount._find_windows_volume_ctypes", lambda: fake)
    assert _find_windows_volume() == fake


def test_ctypes_volume_scan_sets_argtypes_and_uses_logical_drive_mask():
    import inspect

    from library_sync.mount import _find_windows_volume_ctypes

    src = inspect.getsource(_find_windows_volume_ctypes)
    assert "GetLogicalDrives" in src
    assert "GetVolumeInformationW.argtypes" in src
    assert "_iter_logical_drive_letters" in src
    assert "ascii_uppercase" not in src or "GetLogicalDrives" in src


class TestMacOSVolumeDetection:
    def test_detects_primary_volume(self, tmp_path):
        """Test that primary volume name is detected on macOS."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
            with patch("library_sync.mount.sys") as mock_sys:
                mock_sys.platform = "darwin"
                with patch("library_sync.mount._MACOS_VOLUME_PATHS") as mock_paths:
                    mock_vol = tmp_path / "Will Hunter Music"
                    mock_vol.mkdir()
                    mock_paths.__iter__ = lambda self: iter([mock_vol])
                    result = find_drive()
                    assert result == mock_vol

    def test_detects_alt_volume(self, tmp_path):
        """Test that alternate volume name (HuntingSzn) is detected on macOS."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MUSIC_DRIVE_ROOT", None)
            with patch("library_sync.mount.sys") as mock_sys:
                mock_sys.platform = "darwin"
                with patch("library_sync.mount._MACOS_VOLUME_PATHS") as mock_paths:
                    mock_vol_alt = tmp_path / "HuntingSzn"
                    mock_vol_alt.mkdir()
                    mock_paths.__iter__ = lambda self: iter([
                        tmp_path / "nonexistent",
                        mock_vol_alt,
                    ])
                    result = find_drive()
                    assert result == mock_vol_alt
