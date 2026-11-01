"""Shared test fixtures for auto_cue tests."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest
import numpy as np


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_mp3(temp_dir: Path) -> Path:
    """Generate a minimal valid MP3 file with silence."""
    path = temp_dir / "test.mp3"
    _create_silent_mp3(path, duration_s=10.0)
    return path


@pytest.fixture
def sample_flac(temp_dir: Path) -> Path:
    """Generate a minimal valid FLAC file with silence."""
    path = temp_dir / "test.flac"
    _create_silent_flac(path, duration_s=10.0)
    return path


@pytest.fixture
def sample_m4a(temp_dir: Path) -> Path:
    """Generate a minimal valid M4A file with silence."""
    path = temp_dir / "test.m4a"
    _create_silent_m4a(path, duration_s=10.0)
    return path


def _create_silent_mp3(path: Path, duration_s: float = 10.0, sr: int = 44100) -> None:
    """Create a silent MP3 file using soundfile + ffmpeg fallback."""
    import soundfile as sf
    
    wav_path = path.with_suffix(".wav")
    samples = int(sr * duration_s)
    silence = np.zeros(samples, dtype=np.float32)
    sf.write(wav_path, silence, sr)
    
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "9", str(path)],
            capture_output=True,
            timeout=30,
        )
        wav_path.unlink()
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    except FileNotFoundError:
        import shutil
        shutil.move(wav_path, path)


def _create_silent_flac(path: Path, duration_s: float = 10.0, sr: int = 44100) -> None:
    """Create a silent FLAC file."""
    import soundfile as sf
    
    samples = int(sr * duration_s)
    silence = np.zeros(samples, dtype=np.float32)
    sf.write(path, silence, sr, format="FLAC")


def _create_silent_m4a(path: Path, duration_s: float = 10.0, sr: int = 44100) -> None:
    """Create a silent M4A/AAC file."""
    import soundfile as sf
    
    wav_path = path.with_suffix(".wav")
    samples = int(sr * duration_s)
    silence = np.zeros(samples, dtype=np.float32)
    sf.write(wav_path, silence, sr)
    
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "aac", "-b:a", "64k", str(path)],
            capture_output=True,
            timeout=30,
        )
        wav_path.unlink()
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    except FileNotFoundError:
        import shutil
        shutil.move(wav_path, path)


@pytest.fixture
def qa_songs_dir() -> Path | None:
    """Return path to QA songs if available."""
    qa_path = Path("/workspace/test-data/qa-songs")
    if qa_path.is_dir() and any(qa_path.glob("*.mp3")):
        return qa_path
    return None


@pytest.fixture
def gold_cues_csv() -> Path | None:
    """Return path to gold cues CSV if available."""
    csv_path = Path("/workspace/data/cues.csv")
    if csv_path.is_file():
        return csv_path
    return None
