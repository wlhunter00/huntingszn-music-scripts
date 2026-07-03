"""Drive paths — override with MUSIC_DRIVE_ROOT in .env or the environment."""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: …/Scripts/config/paths.py -> …/Scripts
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent


def _normalize_drive_root(raw: str) -> Path:
    """Normalize drive roots like ``G:`` to ``G:\\`` on Windows."""
    path = Path(raw).expanduser()
    if path.drive and str(path) in {path.drive, path.drive + os.sep}:
        return Path(path.drive + os.sep)
    return path


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_SCRIPTS_ROOT / ".env")
    except ImportError:
        pass


_load_env()

_drive_override = os.environ.get("MUSIC_DRIVE_ROOT")
DRIVE_ROOT = (
    _normalize_drive_root(_drive_override)
    if _drive_override
    else _normalize_drive_root(str(_SCRIPTS_ROOT.parent))
)

SCRIPTS_ROOT = DRIVE_ROOT / "Scripts"
PLATINUM_NOTES = DRIVE_ROOT / "Platnium Notes"
DJ_SPOTIFY = DRIVE_ROOT / "DJ Music" / "Spotify"
DJ_SOUNDCLOUD_NUKE = DRIVE_ROOT / "DJ Music" / "Soundcloud" / "1- need to nuke"
DOWNLOADS = DRIVE_ROOT / "Downloads"

STEM_DIR = DRIVE_ROOT / "Stem Splitting"
STEM_INPUT = STEM_DIR / "songs-to-split"
STEM_OUTPUT = STEM_DIR / "stem-output"
STEM_OUTPUT_MODEL = STEM_OUTPUT / "htdemucs_ft"

KEY_CORRECTION_OUTPUT = SCRIPTS_ROOT / "data" / "key_correction" / "output"
CATALOG_OUTPUT_DIR = SCRIPTS_ROOT / "data" / "catalogs"

DEFAULT_SAMPLE_ROOTS = (
    DRIVE_ROOT / "Producing Sounds",
    DRIVE_ROOT / "Ableton",
    STEM_DIR,
    DRIVE_ROOT / "Instruments",
    DRIVE_ROOT / "serum presets",
)
