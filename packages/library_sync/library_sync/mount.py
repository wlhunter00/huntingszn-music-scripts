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


def _find_windows_volume() -> Path | None:
    """Find a Windows drive with the expected volume label."""
    try:
        result = subprocess.run(
            ["wmic", "logicaldisk", "get", "name,volumename"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                drive_letter = parts[0]
                volume_name = " ".join(parts[1:])
                if volume_name in VOLUME_NAMES:
                    return Path(drive_letter + os.sep)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _find_windows_scripts_parent() -> Path | None:
    """Check if we're running from within the music drive's Scripts folder."""
    scripts_root = Path(__file__).resolve()
    for parent in scripts_root.parents:
        if parent.name == "Scripts" and parent.parent.drive:
            candidate = parent.parent
            if (candidate / "DJ Music").is_dir() or (candidate / "Platnium Notes").is_dir():
                return candidate
    return None


def find_drive(explicit: Path | None = None) -> Path | None:
    """Find the music drive.

    Args:
        explicit: If provided, use this path directly (for MUSIC_DRIVE_ROOT override)

    Returns:
        Path to the drive root, or None if not found/mounted
    """
    env_override = os.environ.get("MUSIC_DRIVE_ROOT")
    if env_override:
        p = Path(env_override)
        if p.drive and str(p) in {p.drive, p.drive + os.sep}:
            p = Path(p.drive + os.sep)
        if p.exists():
            return p
        return None

    if explicit is not None:
        return explicit if explicit.exists() else None

    if sys.platform == "darwin":
        for vol_path in _MACOS_VOLUME_PATHS:
            if vol_path.exists():
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
