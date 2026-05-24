"""Drive paths — override with MUSIC_DRIVE_ROOT in .env or the environment."""

from __future__ import annotations

import os
from pathlib import Path

DRIVE_ROOT = Path(os.environ.get("MUSIC_DRIVE_ROOT", "/Volumes/Will Hunter Music")).expanduser()

SCRIPTS_ROOT = DRIVE_ROOT / "Scripts"
PLATINUM_NOTES = DRIVE_ROOT / "Platnium Notes"
DJ_SPOTIFY = DRIVE_ROOT / "DJ Music" / "Spotify"
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
