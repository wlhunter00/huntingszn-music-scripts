"""Tiny WAV helpers for tests. Generated files stay in tmp; never commit audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
FRAMES = 441  # 10 ms


def write_wav(path: Path, value: float = 0.1, frames: int = FRAMES, sr: int = SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.full((frames, 2), value, dtype=np.float32)
    sf.write(path, audio, sr, subtype="PCM_24")
    return path


def write_separator_stem(
    directory: Path,
    input_stem: str,
    token: str,
    model_filename: str,
    value: float = 0.1,
) -> Path:
    model_id = Path(model_filename).stem
    path = directory / f"{input_stem}_({token})_{model_id}.wav"
    return write_wav(path, value=value)


def rms(path: Path) -> float:
    audio, _ = sf.read(path, dtype="float32")
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
