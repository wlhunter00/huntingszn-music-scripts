"""Shared fixtures for stem_split tests. No real separator or model downloads."""

from __future__ import annotations

from pathlib import Path

import pytest
from _audio import write_wav


@pytest.fixture
def tmp_song(tmp_path: Path) -> Path:
    return write_wav(tmp_path / "Artist - Title.wav", value=0.4)
