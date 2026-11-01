"""Audio feature extraction for cue point prediction.

Extracts per-phrase features aligned to the Serato beatgrid:
- RMS energy (overall and low-band)
- Onset density
- Spectral flux
- Drop candidates scored by energy transitions
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


@dataclass
class PhraseFeatures:
    """Features for a single 16-beat half-phrase."""
    beat_start: int
    beat_end: int
    rms_db: float
    low_db: float  # 20-150 Hz
    high_db: float  # > 4kHz
    onset_rate: float
    spectral_flux: float
    delta_rms: float = 0.0
    delta_low: float = 0.0
    is_drop_candidate: bool = False
    drop_score: float = 0.0


@dataclass
class TrackFeatures:
    """Complete feature set for a track."""
    path: Path
    bpm: float
    first_beat_s: float
    total_beats: int
    duration_s: float
    phrases: list[PhraseFeatures] = field(default_factory=list)
    drop_candidates: list[int] = field(default_factory=list)
    grid_check_passed: bool = True
    grid_check_error_ms: float = 0.0
    
    @property
    def file_hash(self) -> str:
        """SHA256 of file for caching."""
        return hashlib.sha256(self.path.read_bytes()[:1024*1024]).hexdigest()[:16]


def load_audio(path: Path, sr: int = 22050) -> tuple[np.ndarray, int]:
    """Load audio file at target sample rate, mono."""
    import librosa
    y, actual_sr = librosa.load(path, sr=sr, mono=True)
    return y, actual_sr


def extract_features(
    path: Path,
    bpm: float,
    first_beat_s: float,
    *,
    phrase_beats: int = 16,
    sr: int = 22050,
) -> TrackFeatures:
    """Extract phrase-level features from audio aligned to beatgrid.
    
    Args:
        path: Audio file path
        bpm: BPM from Serato beatgrid
        first_beat_s: First beat position in seconds
        phrase_beats: Beats per phrase (16 for half-phrase analysis)
        sr: Sample rate for analysis
    
    Returns:
        TrackFeatures with per-phrase data
    """
    import librosa
    
    y, _ = load_audio(path, sr=sr)
    duration_s = len(y) / sr
    
    beat_duration_s = 60.0 / bpm
    total_beats = int((duration_s - first_beat_s) / beat_duration_s)
    
    result = TrackFeatures(
        path=path,
        bpm=bpm,
        first_beat_s=first_beat_s,
        total_beats=total_beats,
        duration_s=duration_s,
    )
    
    y_low = _bandpass(y, sr, 20, 150)
    y_high = _highpass(y, sr, 4000)
    
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    hop_length = 512
    onset_sr = sr / hop_length
    
    S = np.abs(librosa.stft(y))
    flux = np.sqrt(np.sum(np.diff(S, axis=1)**2, axis=0))
    
    n_phrases = total_beats // phrase_beats
    prev_rms = None
    prev_low = None
    
    for i in range(n_phrases):
        beat_start = i * phrase_beats
        beat_end = (i + 1) * phrase_beats
        
        start_s = first_beat_s + beat_start * beat_duration_s
        end_s = first_beat_s + beat_end * beat_duration_s
        
        start_sample = int(start_s * sr)
        end_sample = int(end_s * sr)
        
        if end_sample > len(y):
            break
        
        segment = y[start_sample:end_sample]
        segment_low = y_low[start_sample:end_sample]
        segment_high = y_high[start_sample:end_sample]
        
        rms = np.sqrt(np.mean(segment**2))
        rms_db = 20 * np.log10(max(rms, 1e-10))
        
        rms_low = np.sqrt(np.mean(segment_low**2))
        low_db = 20 * np.log10(max(rms_low, 1e-10))
        
        rms_high = np.sqrt(np.mean(segment_high**2))
        high_db = 20 * np.log10(max(rms_high, 1e-10))
        
        onset_start = int(start_s * onset_sr)
        onset_end = int(end_s * onset_sr)
        if onset_end > len(onset_env):
            onset_end = len(onset_env)
        onset_segment = onset_env[onset_start:onset_end]
        onset_rate = np.mean(onset_segment) if len(onset_segment) > 0 else 0.0
        
        flux_sr = sr / hop_length
        flux_start = int(start_s * flux_sr)
        flux_end = int(end_s * flux_sr)
        if flux_end > len(flux):
            flux_end = len(flux)
        flux_segment = flux[flux_start:flux_end]
        spectral_flux = np.mean(flux_segment) if len(flux_segment) > 0 else 0.0
        
        delta_rms = rms_db - prev_rms if prev_rms is not None else 0.0
        delta_low = low_db - prev_low if prev_low is not None else 0.0
        
        phrase = PhraseFeatures(
            beat_start=beat_start,
            beat_end=beat_end,
            rms_db=float(rms_db),
            low_db=float(low_db),
            high_db=float(high_db),
            onset_rate=float(onset_rate),
            spectral_flux=float(spectral_flux),
            delta_rms=float(delta_rms),
            delta_low=float(delta_low),
        )
        result.phrases.append(phrase)
        
        prev_rms = rms_db
        prev_low = low_db
    
    _identify_drop_candidates(result)
    
    return result


def _bandpass(y: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    """Apply bandpass filter."""
    from scipy.signal import butter, filtfilt
    
    nyq = sr / 2
    low_norm = low / nyq
    high_norm = high / nyq
    
    low_norm = max(0.001, min(0.999, low_norm))
    high_norm = max(0.001, min(0.999, high_norm))
    
    if low_norm >= high_norm:
        return y
    
    b, a = butter(4, [low_norm, high_norm], btype='band')
    return filtfilt(b, a, y)


def _highpass(y: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    """Apply highpass filter."""
    from scipy.signal import butter, filtfilt
    
    nyq = sr / 2
    norm = cutoff / nyq
    norm = max(0.001, min(0.999, norm))
    
    b, a = butter(4, norm, btype='high')
    return filtfilt(b, a, y)


def _identify_drop_candidates(features: TrackFeatures) -> None:
    """Identify potential drop points based on energy transitions."""
    if len(features.phrases) < 4:
        return
    
    scores: list[tuple[int, float]] = []
    
    rms_values = [p.rms_db for p in features.phrases]
    if not rms_values:
        return
    
    rms_median = float(np.median(rms_values))
    
    for i, phrase in enumerate(features.phrases):
        if phrase.beat_start % 32 != 0:
            continue
        
        combined_delta = phrase.delta_rms + phrase.delta_low * 0.5
        
        if i > 0:
            prev = features.phrases[i - 1]
            if prev.rms_db < phrase.rms_db:
                combined_delta += (phrase.rms_db - prev.rms_db) * 0.5
        
        if phrase.rms_db > rms_median:
            combined_delta += 1.0
        
        if combined_delta > 1.0:
            scores.append((phrase.beat_start, combined_delta))
            phrase.is_drop_candidate = True
            phrase.drop_score = combined_delta
    
    if not scores:
        for i, phrase in enumerate(features.phrases):
            if phrase.beat_start % 32 == 0:
                score = phrase.rms_db - rms_median + phrase.delta_rms
                scores.append((phrase.beat_start, score))
                phrase.is_drop_candidate = True
                phrase.drop_score = score
    
    scores.sort(key=lambda x: -x[1])
    features.drop_candidates = [beat for beat, _ in scores[:10]]


def check_grid_alignment(
    path: Path,
    bpm: float,
    first_beat_s: float,
    *,
    sr: int = 22050,
    tolerance_ms: float = 30.0,
) -> tuple[bool, float]:
    """Check if beatgrid aligns with audio onsets.
    
    Returns:
        (passed, median_error_ms)
    """
    import librosa
    
    y, _ = load_audio(path, sr=sr)
    
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    
    beat_duration_s = 60.0 / bpm
    duration_s = len(y) / sr
    n_beats = int((duration_s - first_beat_s) / beat_duration_s)
    
    beat_times = [first_beat_s + i * beat_duration_s for i in range(n_beats)]
    
    errors = []
    for bt in beat_times[::4]:
        if len(onset_times) == 0:
            break
        diffs = np.abs(onset_times - bt)
        min_diff = np.min(diffs)
        errors.append(min_diff * 1000)
    
    if not errors:
        return True, 0.0
    
    median_error = float(np.median(errors))
    passed = median_error <= tolerance_ms
    
    return passed, median_error


def format_phrase_table(features: TrackFeatures) -> str:
    """Format phrase features as a compact text table for LLM."""
    lines = []
    lines.append(f"BPM: {features.bpm:.1f}, Total beats: {features.total_beats}")
    lines.append("")
    lines.append("beat | rms_db | low_db | Δrms  | Δlow  | drop")
    lines.append("-----|--------|--------|-------|-------|-----")
    
    for phrase in features.phrases:
        if phrase.beat_start % 32 == 0:
            drop_mark = f"{phrase.drop_score:.1f}" if phrase.is_drop_candidate else ""
            lines.append(
                f"{phrase.beat_start:4d} | {phrase.rms_db:6.1f} | {phrase.low_db:6.1f} | "
                f"{phrase.delta_rms:+5.1f} | {phrase.delta_low:+5.1f} | {drop_mark}"
            )
    
    lines.append("")
    lines.append(f"Drop candidates (by score): {features.drop_candidates[:5]}")
    
    return "\n".join(lines)
