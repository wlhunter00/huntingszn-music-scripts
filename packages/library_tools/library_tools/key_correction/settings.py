"""Key correction settings from environment."""

from __future__ import annotations

import os

from config.paths import DJ_SPOTIFY, KEY_CORRECTION_OUTPUT

LIBRARY_PATH = DJ_SPOTIFY
OUTPUT_DIR = KEY_CORRECTION_OUTPUT

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

AUDIO_EXTENSIONS = (".mp3", ".flac")
