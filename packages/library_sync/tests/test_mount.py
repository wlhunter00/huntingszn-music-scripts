"""Tests for drive detection."""

import os
from pathlib import Path
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
        (fake_drive / "DJ Music").mkdir()

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

    def test_existing_wrong_windows_env_falls_through_to_volume(self, tmp_path, monkeypatch):
        """H: taken by another volume is why HuntingSzn remounts as E: — must not pin H:."""
        wrong = tmp_path / "OtherUSB"
        wrong.mkdir()
        found = tmp_path / "HuntingSzn"
        found.mkdir()
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(wrong))
        monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
        monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: found)
        monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
        assert find_drive() == found

    def test_windows_env_folder_copy_with_layout_is_used(self, tmp_path, monkeypatch):
        copy = tmp_path / "library-copy"
        (copy / "DJ Music").mkdir(parents=True)
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(copy))
        monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
        monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: None)
        monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
        assert find_drive() == copy

    def test_stale_env_falls_through_to_macos_volume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(tmp_path / "not-mounted"))
        vol = tmp_path / "HuntingSzn"
        vol.mkdir()
        (vol / "DJ Music").mkdir()
        monkeypatch.setattr("library_sync.mount.sys.platform", "darwin")
        monkeypatch.setattr("library_sync.mount._MACOS_VOLUME_PATHS", [vol])
        assert find_drive() == vol

    def test_existing_wrong_macos_env_falls_through_to_volume(self, tmp_path, monkeypatch):
        wrong = tmp_path / "MyBackup"
        wrong.mkdir()
        vol = tmp_path / "HuntingSzn"
        vol.mkdir()
        (vol / "DJ Music").mkdir()
        monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(wrong))
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

    def test_explicit_path_wins_over_env_even_without_music_layout(self, tmp_path):
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
        (fake_drive / "DJ Music").mkdir()

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


class _FakeWinPath:
    def __init__(self, text: str = "H:\\", drive: str = "H:") -> None:
        self.drive = drive
        self._text = text

    def __str__(self) -> str:
        return self._text

    def __truediv__(self, other):
        raise AssertionError("must not probe layout on a rejected bare letter")


def test_is_bare_drive_root_accepts_letter_with_either_slash():
    from library_sync.mount import _is_bare_drive_root

    assert _is_bare_drive_root(_FakeWinPath("H:", "H:")) is True
    assert _is_bare_drive_root(_FakeWinPath("H:\\", "H:")) is True
    assert _is_bare_drive_root(_FakeWinPath("H:/", "H:")) is True
    assert _is_bare_drive_root(_FakeWinPath("H:\\DJ Music", "H:")) is False


def test_windows_env_override_ok_rejects_occupied_bare_letter_without_stat(monkeypatch):
    from library_sync.mount import _windows_env_override_ok

    monkeypatch.setattr("library_sync.mount._windows_letter_is_music_volume", lambda letter: False)
    assert _windows_env_override_ok(_FakeWinPath()) is False


def test_windows_env_override_ok_accepts_music_volume_letter(monkeypatch):
    from library_sync.mount import _windows_env_override_ok

    monkeypatch.setattr("library_sync.mount._windows_letter_is_music_volume", lambda letter: True)
    assert _windows_env_override_ok(_FakeWinPath()) is True


def test_windows_env_override_ok_rejects_subfolder_on_music_letter_without_layout(monkeypatch):
    from library_sync.mount import _windows_env_override_ok

    class Sub(_FakeWinPath):
        def __init__(self) -> None:
            super().__init__("H:\\DJ Music", "H:")

        def __truediv__(self, other):
            class Missing:
                def __truediv__(self, _other):
                    return self

                def is_dir(self) -> bool:
                    return False

                def is_file(self) -> bool:
                    return False

            return Missing()

    monkeypatch.setattr("library_sync.mount._windows_letter_is_music_volume", lambda letter: True)
    assert _windows_env_override_ok(Sub()) is False


def test_find_drive_occupied_bare_letter_falls_through_without_layout_stat(tmp_path, monkeypatch):
    occupied = _FakeWinPath("H:\\", "H:")
    found = tmp_path / "HuntingSzn"
    found.mkdir()

    def fake_path(arg, *a, **k):
        text = str(arg)
        if text.replace("/", "\\").rstrip("\\") == "H:":
            return occupied
        return Path(arg, *a, **k)

    monkeypatch.setenv("MUSIC_DRIVE_ROOT", "H:\\")
    monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
    monkeypatch.setattr("library_sync.mount.Path", fake_path)
    monkeypatch.setattr("library_sync.mount._windows_letter_is_music_volume", lambda letter: False)
    monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: found)
    monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
    assert find_drive() == found


def test_find_drive_music_letter_override_skips_volume_scan(monkeypatch):
    pinned = _FakeWinPath("H:\\", "H:")

    def fake_path(arg, *a, **k):
        text = str(arg)
        if text.replace("/", "\\").rstrip("\\") == "H:":
            return pinned
        return Path(arg, *a, **k)

    monkeypatch.setenv("MUSIC_DRIVE_ROOT", "H:\\")
    monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
    monkeypatch.setattr("library_sync.mount.Path", fake_path)
    monkeypatch.setattr("library_sync.mount._windows_letter_is_music_volume", lambda letter: True)
    monkeypatch.setattr(
        "library_sync.mount._find_windows_volume",
        lambda: (_ for _ in ()).throw(AssertionError("volume scan must not run")),
    )
    assert find_drive() is pinned


def test_macos_disambiguated_name_accepts_finder_suffix():
    from library_sync.mount import _macos_disambiguated_name

    assert _macos_disambiguated_name("HuntingSzn") is True
    assert _macos_disambiguated_name("HuntingSzn 1") is True
    assert _macos_disambiguated_name("Will Hunter Music 2") is True
    assert _macos_disambiguated_name("HuntingSzn Backup") is False
    assert _macos_disambiguated_name("Macintosh HD") is False


def test_macos_stale_volume_dir_falls_through_to_numbered_name(tmp_path, monkeypatch):
    stale = tmp_path / "HuntingSzn"
    stale.mkdir()
    real = tmp_path / "HuntingSzn 1"
    (real / "DJ Music").mkdir(parents=True)
    monkeypatch.delenv("MUSIC_DRIVE_ROOT", raising=False)
    monkeypatch.setattr("library_sync.mount.sys.platform", "darwin")
    monkeypatch.setattr("library_sync.mount._MACOS_VOLUME_PATHS", [stale])
    monkeypatch.setattr(
        "library_sync.mount._iter_macos_volume_paths",
        lambda: iter([stale, real]),
    )
    assert find_drive() == real


def test_macos_env_stale_exact_name_falls_through(tmp_path, monkeypatch):
    stale = tmp_path / "HuntingSzn"
    stale.mkdir()
    real = tmp_path / "HuntingSzn 1"
    (real / "Scripts" / "pyproject.toml").parent.mkdir(parents=True)
    (real / "Scripts" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(stale))
    monkeypatch.setattr("library_sync.mount.sys.platform", "darwin")
    monkeypatch.setattr(
        "library_sync.mount._iter_macos_volume_paths",
        lambda: iter([stale, real]),
    )
    assert find_drive() == real


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
                    (mock_vol / "DJ Music").mkdir()
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
                    (mock_vol_alt / "DJ Music").mkdir()
                    mock_paths.__iter__ = lambda self: iter([
                        tmp_path / "nonexistent",
                        mock_vol_alt,
                    ])
                    result = find_drive()
                    assert result == mock_vol_alt
