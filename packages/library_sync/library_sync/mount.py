"""Drive detection for the portable music drive.

Volume names: "Will Hunter Music" or "HuntingSzn"
- macOS: /Volumes/Will Hunter Music or /Volumes/HuntingSzn
- Windows: scan volumes for label, or accept Scripts-parent drive (G:/H:/E:)
- Linux: MUSIC_DRIVE_ROOT env only
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

VOLUME_NAME = "Will Hunter Music"
VOLUME_NAME_ALT = "HuntingSzn"
VOLUME_NAMES = (VOLUME_NAME, VOLUME_NAME_ALT)

_MACOS_VOLUME_PATHS = [Path("/Volumes") / name for name in VOLUME_NAMES]


def _wmic_drive_letter_for_music_volume(line: str) -> str | None:
    """Return drive letter (e.g. ``D:``) if a WMIC logicaldisk line is a music volume."""
    parts = line.strip().split()
    if len(parts) < 2:
        return None
    drive_letter = parts[0]
    volume_name = " ".join(parts[1:])
    if volume_name in VOLUME_NAMES:
        return drive_letter
    return None


def _iter_logical_drive_letters(mask: int):
    """Yield drive letters whose bit is set in GetLogicalDrives()."""
    import string

    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            yield letter


def _find_windows_volume_ctypes() -> Path | None:
    """Scan mounted volumes via GetLogicalDrives + GetVolumeInformationW.

    wmic is missing on some Windows 11 installs; Path.exists() on A:..Z: can hang
    on empty floppy/card readers, so only letters present in the bitmask are used.
    """
    try:
        import ctypes
    except ImportError:
        return None
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return None

    kernel32.GetLogicalDrives.restype = ctypes.c_uint32
    kernel32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumeInformationW.restype = ctypes.c_int
    buf = ctypes.create_unicode_buffer(1024)
    try:
        mask = int(kernel32.GetLogicalDrives())
    except OSError:
        return None
    for letter in _iter_logical_drive_letters(mask):
        root_s = letter + ":\\"
        try:
            ok = kernel32.GetVolumeInformationW(root_s, buf, 1024, None, None, None, None, 0)
        except OSError:
            continue
        if ok and buf.value in VOLUME_NAMES:
            return Path(root_s)
    return None


def _find_windows_volume() -> Path | None:
    """Find a Windows drive with the expected volume label."""
    try:
        result = subprocess.run(
            ["wmic", "logicaldisk", "get", "name,volumename"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines()[1:]:
                drive_letter = _wmic_drive_letter_for_music_volume(line)
                if drive_letter:
                    return Path(drive_letter + os.sep)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return _find_windows_volume_ctypes()


def _find_windows_scripts_parent() -> Path | None:
    """Check if we're running from within the music drive's Scripts folder."""
    scripts_root = Path(__file__).resolve()
    for parent in scripts_root.parents:
        if parent.name == "Scripts" and parent.parent.drive:
            candidate = parent.parent
            if (candidate / "DJ Music").is_dir() or (candidate / "Platnium Notes").is_dir():
                return candidate
    return None


def _has_music_layout(path: Path) -> bool:
    """True if ``path`` looks like the portable music drive, not merely exists."""
    try:
        return (
            (path / "DJ Music").is_dir()
            or (path / "Platnium Notes").is_dir()
            or (path / "Scripts" / "pyproject.toml").is_file()
        )
    except OSError:
        return False


def _is_bare_drive_root(path: Path) -> bool:
    """True for ``H:`` / ``H:\\`` / ``H:/``, not ``H:\\DJ Music``."""
    if not path.drive:
        return False
    return str(path).rstrip("\\/") == path.drive


def _windows_letter_is_music_volume(letter: str) -> bool | None:
    """True/False if this letter's volume label is known; None if APIs are unavailable.

    False includes "letter not in GetLogicalDrives bitmask" so callers can skip
    ``Path.exists()`` on empty readers / stale letters.
    """
    letter = letter[:1].upper()
    if not letter.isalpha():
        return None
    try:
        import ctypes
    except ImportError:
        return None
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return None
    try:
        kernel32.GetLogicalDrives.restype = ctypes.c_uint32
        mask = int(kernel32.GetLogicalDrives())
    except OSError:
        return None
    bit = ord(letter) - ord("A")
    if not mask & (1 << bit):
        return False
    kernel32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumeInformationW.restype = ctypes.c_int
    buf = ctypes.create_unicode_buffer(1024)
    root_s = letter + ":\\"
    try:
        ok = kernel32.GetVolumeInformationW(root_s, buf, 1024, None, None, None, None, 0)
    except OSError:
        return False
    return bool(ok) and buf.value in VOLUME_NAMES


def _windows_env_override_ok(path: Path) -> bool:
    """Whether MUSIC_DRIVE_ROOT should be used on Windows.

    ``Path.exists()`` is not enough. Windows remounts HuntingSzn as ``E:``
    *because* ``H:`` is already taken; a pinned ``MUSIC_DRIVE_ROOT=H:`` would
    then publish the wrong volume (or idle on a non-music drive). Bare letters
    must match the music volume label. Do not ``exists()`` / ``is_dir()`` a
    rejected bare letter (empty card readers can hang). A music-labeled letter
    still rejects a subdirectory override (``H:\\DJ Music``) so watch publishes
    the volume root, not a folder as the bucket root.
    """
    if path.drive:
        result = _windows_letter_is_music_volume(path.drive[0])
        if result is True:
            if _is_bare_drive_root(path):
                return True
            return _has_music_layout(path)
        if result is False:
            if _is_bare_drive_root(path):
                return False
            return _has_music_layout(path)
    if _is_bare_drive_root(path):
        return False
    return _has_music_layout(path)


def _macos_disambiguated_name(name: str) -> bool:
    """True for ``HuntingSzn`` / ``Will Hunter Music`` or macOS ``Name 1``."""
    if name in VOLUME_NAMES:
        return True
    for vol in VOLUME_NAMES:
        extra = name[len(vol) :]
        if name.startswith(vol) and extra[:1] == " " and extra[1:].isdigit():
            return True
    return False


def _macos_volume_ok(path: Path) -> bool:
    """Reject a stale ``/Volumes/HuntingSzn`` directory that is not a mount."""
    try:
        if not path.exists():
            return False
    except OSError:
        return False
    try:
        if path.is_mount():
            return True
    except OSError:
        pass
    return _has_music_layout(path)


def _macos_override_ok(path: Path) -> bool:
    """Honor MUSIC_DRIVE_ROOT on macOS only for a music volume or layout copy."""
    if not _macos_volume_ok(path):
        return False
    return _macos_disambiguated_name(path.name) or _has_music_layout(path)


def _iter_macos_volume_paths():
    """Exact ``/Volumes`` names, then Finder's ``HuntingSzn 1`` when taken."""
    yield from _MACOS_VOLUME_PATHS
    volumes = Path("/Volumes")
    try:
        entries = list(volumes.iterdir())
    except OSError:
        return
    seen = {str(path) for path in _MACOS_VOLUME_PATHS}
    for entry in entries:
        if str(entry) in seen:
            continue
        if _macos_disambiguated_name(entry.name):
            yield entry


def find_drive(explicit: Path | None = None) -> Path | None:
    """Find the music drive.

    Args:
        explicit: If provided, use this path and ignore MUSIC_DRIVE_ROOT

    Returns:
        Path to the drive root, or None if not found/mounted. A stale
        MUSIC_DRIVE_ROOT that is not mounted, or a Windows letter that exists
        but is not HuntingSzn / Will Hunter Music, falls through to volume-name
        scan. ``--root`` / ``explicit`` still wins without a volume check.
    """
    if explicit is not None:
        return explicit if explicit.exists() else None

    # Honor MUSIC_DRIVE_ROOT when it still points at the music drive. A stale
    # letter (H: missing) or a wrong live letter (H: taken, stick is E:) must
    # not hide volume-name discovery — that is why the stick remounted as E:.
    env_override = os.environ.get("MUSIC_DRIVE_ROOT")
    if env_override:
        p = Path(env_override)
        if _is_bare_drive_root(p):
            p = Path(p.drive + os.sep)
        if sys.platform == "win32":
            if _windows_env_override_ok(p):
                return p
        elif sys.platform == "darwin":
            if _macos_override_ok(p):
                return p
        elif p.exists():
            return p
        # Stale or wrong override. The login stub falls through to volume-name
        # scan; watch must too or it publishes the wrong drive / idles forever.

    if sys.platform == "darwin":
        for vol_path in _iter_macos_volume_paths():
            if _macos_volume_ok(vol_path):
                return vol_path
        return None

    if sys.platform == "win32":
        found = _find_windows_volume()
        if found:
            return found
        return _find_windows_scripts_parent()

    return None


def drive_is_mounted() -> bool:
    """Check if the music drive is currently mounted/accessible."""
    return find_drive() is not None
