"""Audio feature extraction for cue point prediction.

Rich code-based analysis: kick density, multi-scale contrast, novelty,
vocal activity (demucs), build signals, snare-roll detection, pre-drop gap.
Features computed per beat and summarized per 8/16/32 beats.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DEMUCS_CACHE_DIR = Path("/tmp/demucs_cache")


@dataclass
class BeatFeatures:
    """Features for a single beat."""
    beat: int
    rms_db: float = 0.0
    low_db: float = 0.0  # <150 Hz (kick band)
    high_db: float = 0.0  # >4 kHz
    kick_onset: float = 0.0  # Low-band onset strength
    onset_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_flatness: float = 0.0
    spectral_rolloff: float = 0.0
    snare_band_onset: float = 0.0  # 1-5 kHz onset for snare-roll
    vocal_rms: float = 0.0  # From demucs vocal stem
    contrast_score: float = 0.0  # Multi-scale before/after
    novelty_score: float = 0.0  # Self-similarity novelty


@dataclass
class PhraseFeatures:
    """Features aggregated for a phrase (8, 16, or 32 beats)."""
    beat_start: int
    beat_end: int
    phrase_size: int  # 8, 16, or 32
    rms_db: float = 0.0
    low_db: float = 0.0
    high_db: float = 0.0
    kick_density: float = 0.0  # Mean kick onset per beat
    onset_rate: float = 0.0
    delta_rms: float = 0.0
    delta_low: float = 0.0
    delta_kick: float = 0.0  # Kick density change
    vocal_activity: float = 0.0
    build_score: float = 0.0  # Slope of centroid/highband/flatness
    snare_roll: float = 0.0  # Snare-band onset acceleration
    contrast_score: float = 0.0  # Multi-scale contrast
    novelty_score: float = 0.0  # Self-similarity novelty
    pre_drop_gap: float = 0.0  # Min RMS in last 1-2 beats vs phrase mean
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
    beat_features: list[BeatFeatures] = field(default_factory=list)
    phrases_8: list[PhraseFeatures] = field(default_factory=list)
    phrases_16: list[PhraseFeatures] = field(default_factory=list)
    phrases_32: list[PhraseFeatures] = field(default_factory=list)
    drop_candidates: list[int] = field(default_factory=list)
    has_vocal_stem: bool = False

    @property
    def file_hash(self) -> str:
        """SHA256 of file for caching."""
        return hashlib.sha256(self.path.read_bytes()[:1024 * 1024]).hexdigest()[:16]

    @property
    def bpm_band(self) -> str:
        """BPM-based genre proxy."""
        if self.bpm < 80:
            return "bass (<80)"
        elif self.bpm < 100:
            return "dnb (80-100)"
        elif self.bpm < 115:
            return "midtempo (100-115)"
        else:
            return "house (115+)"

    @property
    def phrases(self) -> list[PhraseFeatures]:
        """Alias for phrases_16 for backward compatibility."""
        return self.phrases_16


def load_audio(path: Path, sr: int = 22050) -> tuple[np.ndarray, int]:
    """Load audio file at target sample rate, mono."""
    import librosa
    y, actual_sr = librosa.load(path, sr=sr, mono=True)
    return y, actual_sr


def _bandpass(y: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    """Apply bandpass filter using SOS form for numerical stability."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2
    low_n = max(0.001, min(0.999, low / nyq))
    high_n = max(0.001, min(0.999, high / nyq))
    if low_n >= high_n:
        return y
    sos = butter(4, [low_n, high_n], btype='band', output='sos')
    return sosfiltfilt(sos, y)


def _highpass(y: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    """Apply highpass filter using SOS form."""
    from scipy.signal import butter, sosfiltfilt
    nyq = sr / 2
    norm = max(0.001, min(0.999, cutoff / nyq))
    sos = butter(4, norm, btype='high', output='sos')
    return sosfiltfilt(sos, y)


def _get_vocal_stem(audio_path: Path, sr: int = 22050) -> np.ndarray | None:
    """Get vocal stem using demucs with caching."""
    import librosa

    DEMUCS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    file_hash = hashlib.sha256(audio_path.read_bytes()[:1024 * 1024]).hexdigest()[:16]
    cache_path = DEMUCS_CACHE_DIR / f"{file_hash}_vocals.npy"

    if cache_path.exists():
        return np.load(cache_path)

    try:
        out_dir = DEMUCS_CACHE_DIR / file_hash
        out_dir.mkdir(exist_ok=True)

        result = subprocess.run(
            ["demucs", "--two-stems=vocals", "-o", str(out_dir), str(audio_path)],
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            return None

        vocal_candidates = list(out_dir.rglob("vocals.wav")) + list(out_dir.rglob("vocals.mp3"))
        if not vocal_candidates:
            return None

        vocal_path = vocal_candidates[0]
        y_vocals, _ = librosa.load(vocal_path, sr=sr, mono=True)
        np.save(cache_path, y_vocals)

        return y_vocals
    except Exception:
        return None


def _compute_contrast_score(
    feature_array: np.ndarray,
    beat_idx: int,
    windows: tuple[int, ...] = (2, 4, 8, 16),
) -> float:
    """Compute multi-scale before/after contrast (Mixed In Key patent style).

    For each window w, compute mean(after w) - mean(before w), z-score, and sum.
    """
    n = len(feature_array)
    if n < 4:
        return 0.0

    std = np.std(feature_array)
    if std < 1e-10:
        return 0.0

    total_contrast = 0.0
    for w in windows:
        if beat_idx < w or beat_idx + w >= n:
            continue
        before = np.mean(feature_array[beat_idx - w : beat_idx])
        after = np.mean(feature_array[beat_idx : beat_idx + w])
        diff = after - before
        z = diff / std
        total_contrast += z

    return float(total_contrast)


def _compute_novelty_curve(
    y: np.ndarray,
    sr: int,
    bpm: float,
    first_beat_s: float,
    total_beats: int,
    kernel_sizes: tuple[int, ...] = (16, 32),
) -> np.ndarray:
    """Compute self-similarity novelty using MFCC/chroma recurrence."""
    import librosa

    hop_length = 512
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop_length)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    combined = np.vstack([mfcc, chroma])

    R = librosa.segment.recurrence_matrix(combined, mode='affinity', sym=True)

    novelty = np.zeros(total_beats)
    beat_duration_s = 60.0 / bpm
    frame_rate = sr / hop_length

    for beat in range(total_beats):
        beat_time = first_beat_s + beat * beat_duration_s
        frame = int(beat_time * frame_rate)
        if frame >= R.shape[0]:
            continue

        for k_size in kernel_sizes:
            half_k = k_size // 2
            if frame < half_k or frame + half_k >= R.shape[0]:
                continue

            tl = R[frame - half_k : frame, frame - half_k : frame]
            br = R[frame : frame + half_k, frame : frame + half_k]
            tr = R[frame - half_k : frame, frame : frame + half_k]
            bl = R[frame : frame + half_k, frame - half_k : frame]

            diag = (np.mean(tl) + np.mean(br)) / 2
            off_diag = (np.mean(tr) + np.mean(bl)) / 2
            novelty[beat] += max(0, diag - off_diag)

    if np.max(novelty) > 0:
        novelty = novelty / np.max(novelty)

    return novelty


def extract_features(
    path: Path,
    bpm: float,
    first_beat_s: float,
    *,
    sr: int = 22050,
    use_demucs: bool = True,
) -> TrackFeatures:
    """Extract comprehensive per-beat and per-phrase features.

    Args:
        path: Audio file path
        bpm: BPM from Serato beatgrid
        first_beat_s: First beat position in seconds
        sr: Sample rate for analysis
        use_demucs: Whether to extract vocal stem (slow but accurate)

    Returns:
        TrackFeatures with beat-level and phrase-level data
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
    y_snare = _bandpass(y, sr, 1000, 5000)

    y_vocals = None
    if use_demucs:
        y_vocals = _get_vocal_stem(path, sr=sr)
        result.has_vocal_stem = y_vocals is not None

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_low = librosa.onset.onset_strength(y=y_low, sr=sr)
    onset_snare = librosa.onset.onset_strength(y=y_snare, sr=sr)
    hop_length = 512
    onset_sr = sr / hop_length

    S = np.abs(librosa.stft(y, hop_length=hop_length))
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    rolloff = librosa.feature.spectral_rolloff(S=S, sr=sr)[0]

    novelty_curve = _compute_novelty_curve(y, sr, bpm, first_beat_s, total_beats)

    beat_rms = np.zeros(total_beats)
    beat_low = np.zeros(total_beats)
    beat_high = np.zeros(total_beats)
    beat_kick = np.zeros(total_beats)
    beat_onset = np.zeros(total_beats)
    beat_centroid = np.zeros(total_beats)
    beat_flatness = np.zeros(total_beats)
    beat_rolloff = np.zeros(total_beats)
    beat_snare = np.zeros(total_beats)
    beat_vocal = np.zeros(total_beats)

    for beat in range(total_beats):
        start_s = first_beat_s + beat * beat_duration_s
        end_s = start_s + beat_duration_s
        start_samp = int(start_s * sr)
        end_samp = int(end_s * sr)

        if end_samp > len(y):
            break

        seg = y[start_samp:end_samp]
        seg_low = y_low[start_samp:end_samp]
        seg_high = y_high[start_samp:end_samp]

        beat_rms[beat] = 20 * np.log10(max(np.sqrt(np.mean(seg**2)), 1e-10))
        beat_low[beat] = 20 * np.log10(max(np.sqrt(np.mean(seg_low**2)), 1e-10))
        beat_high[beat] = 20 * np.log10(max(np.sqrt(np.mean(seg_high**2)), 1e-10))

        onset_start = int(start_s * onset_sr)
        onset_end = int(end_s * onset_sr)
        if onset_end <= len(onset_env):
            beat_onset[beat] = np.mean(onset_env[onset_start:onset_end])
            beat_kick[beat] = np.mean(onset_low[onset_start:onset_end])
            beat_snare[beat] = np.mean(onset_snare[onset_start:onset_end])

        frame_start = int(start_s * sr / hop_length)
        frame_end = int(end_s * sr / hop_length)
        if frame_end <= len(centroid):
            beat_centroid[beat] = np.mean(centroid[frame_start:frame_end])
            beat_flatness[beat] = np.mean(flatness[frame_start:frame_end])
            beat_rolloff[beat] = np.mean(rolloff[frame_start:frame_end])

        if y_vocals is not None and end_samp <= len(y_vocals):
            seg_vocal = y_vocals[start_samp:end_samp]
            beat_vocal[beat] = 20 * np.log10(max(np.sqrt(np.mean(seg_vocal**2)), 1e-10))

    contrast_scores = np.zeros(total_beats)
    for beat in range(total_beats):
        contrast_scores[beat] = _compute_contrast_score(beat_low, beat)

    for beat in range(total_beats):
        bf = BeatFeatures(
            beat=beat,
            rms_db=float(beat_rms[beat]),
            low_db=float(beat_low[beat]),
            high_db=float(beat_high[beat]),
            kick_onset=float(beat_kick[beat]),
            onset_rate=float(beat_onset[beat]),
            spectral_centroid=float(beat_centroid[beat]),
            spectral_flatness=float(beat_flatness[beat]),
            spectral_rolloff=float(beat_rolloff[beat]),
            snare_band_onset=float(beat_snare[beat]),
            vocal_rms=float(beat_vocal[beat]) if y_vocals is not None else 0.0,
            contrast_score=float(contrast_scores[beat]),
            novelty_score=float(novelty_curve[beat]),
        )
        result.beat_features.append(bf)

    for phrase_size in (8, 16, 32):
        phrases = _aggregate_phrases(result.beat_features, phrase_size, total_beats)
        if phrase_size == 8:
            result.phrases_8 = phrases
        elif phrase_size == 16:
            result.phrases_16 = phrases
        else:
            result.phrases_32 = phrases

    _identify_drop_candidates(result)

    return result


def _aggregate_phrases(
    beat_features: list[BeatFeatures],
    phrase_size: int,
    total_beats: int,
) -> list[PhraseFeatures]:
    """Aggregate beat features into phrase-level features."""
    phrases = []
    n_phrases = total_beats // phrase_size
    prev_low = None
    prev_rms = None
    prev_kick = None

    for i in range(n_phrases):
        start = i * phrase_size
        end = start + phrase_size
        if end > len(beat_features):
            break

        beats = beat_features[start:end]

        rms_db = np.mean([b.rms_db for b in beats])
        low_db = np.mean([b.low_db for b in beats])
        high_db = np.mean([b.high_db for b in beats])
        kick_density = np.mean([b.kick_onset for b in beats])
        onset_rate = np.mean([b.onset_rate for b in beats])
        vocal_activity = np.mean([b.vocal_rms for b in beats])
        contrast_score = np.max([b.contrast_score for b in beats])
        novelty_score = np.max([b.novelty_score for b in beats])

        centroid_vals = [b.spectral_centroid for b in beats]
        high_vals = [b.high_db for b in beats]
        flatness_vals = [b.spectral_flatness for b in beats]
        snare_vals = [b.snare_band_onset for b in beats]

        build_score = 0.0
        if len(beats) >= 4:
            half = len(beats) // 2
            centroid_slope = np.mean(centroid_vals[half:]) - np.mean(centroid_vals[:half])
            high_slope = np.mean(high_vals[half:]) - np.mean(high_vals[:half])
            flatness_slope = np.mean(flatness_vals[half:]) - np.mean(flatness_vals[:half])
            build_score = centroid_slope / 1000 + high_slope * 0.1 + flatness_slope * 10

        snare_roll = 0.0
        if len(snare_vals) >= 4:
            snare_accel = np.diff(snare_vals)
            snare_roll = float(np.mean(snare_accel[-4:])) if len(snare_accel) >= 4 else 0.0

        pre_drop_gap = 0.0
        if len(beats) >= 2:
            last_2_rms = np.mean([b.rms_db for b in beats[-2:]])
            phrase_mean_rms = rms_db
            pre_drop_gap = phrase_mean_rms - last_2_rms

        delta_rms = rms_db - prev_rms if prev_rms is not None else 0.0
        delta_low = low_db - prev_low if prev_low is not None else 0.0
        delta_kick = kick_density - prev_kick if prev_kick is not None else 0.0

        phrase = PhraseFeatures(
            beat_start=start,
            beat_end=end,
            phrase_size=phrase_size,
            rms_db=float(rms_db),
            low_db=float(low_db),
            high_db=float(high_db),
            kick_density=float(kick_density),
            onset_rate=float(onset_rate),
            delta_rms=float(delta_rms),
            delta_low=float(delta_low),
            delta_kick=float(delta_kick),
            vocal_activity=float(vocal_activity),
            build_score=float(build_score),
            snare_roll=float(snare_roll),
            contrast_score=float(contrast_score),
            novelty_score=float(novelty_score),
            pre_drop_gap=float(pre_drop_gap),
        )
        phrases.append(phrase)

        prev_rms = rms_db
        prev_low = low_db
        prev_kick = kick_density

    return phrases


def _identify_drop_candidates(features: TrackFeatures) -> None:
    """Identify drop candidates using multi-feature scoring."""
    phrases = features.phrases_32
    if len(phrases) < 2:
        return

    for phrase in phrases:
        score = 0.0
        score += phrase.delta_low * 0.4
        score += phrase.delta_kick * 2.0
        score += phrase.contrast_score * 0.3
        score += phrase.novelty_score * 2.0

        if phrase.pre_drop_gap > 3.0:
            score += 1.0

        if score > 2.0:
            phrase.is_drop_candidate = True
            phrase.drop_score = score

    candidates = [(p.beat_start, p.drop_score) for p in phrases if p.is_drop_candidate]
    candidates.sort(key=lambda x: -x[1])
    features.drop_candidates = [beat for beat, _ in candidates[:10]]

    if not features.drop_candidates and phrases:
        best = max(phrases, key=lambda p: p.delta_low + p.delta_kick)
        best.is_drop_candidate = True
        best.drop_score = best.delta_low + best.delta_kick
        features.drop_candidates = [best.beat_start]


def format_phrase_table(features: TrackFeatures, show_32_only: bool = False) -> str:
    """Format phrase features as a rich text table for LLM.

    Shows 16-beat phrases with 32-beat boundary markers and all key features.
    """
    lines = []
    lines.append(f"BPM: {features.bpm:.1f} ({features.bpm_band})")
    lines.append(f"Total beats: {features.total_beats}, Duration: {features.duration_s:.1f}s")
    if features.has_vocal_stem:
        lines.append("Vocal stem: available")
    lines.append("")

    header = (
        "beat |32?| rms  | low  |Δlow |kick |Δkick|vocal|build|snare|contr|novel| gap |drop"
    )
    sep = "-----|---|------|------|-----|-----|-----|-----|-----|-----|-----|-----|-----|----"
    lines.append(header)
    lines.append(sep)

    for p in features.phrases_16:
        if show_32_only and p.beat_start % 32 != 0:
            continue

        is_32 = "▶" if p.beat_start % 32 == 0 else ""
        drop = f"{p.drop_score:.1f}" if p.is_drop_candidate else ""

        def fmt(v: float, thresh: float = 0.1) -> str:
            return f"{v:5.1f}" if abs(v) > thresh else "     "

        lines.append(
            f"{p.beat_start:4d} | {is_32:1s} |{p.rms_db:5.1f} |{p.low_db:5.1f} |"
            f"{fmt(p.delta_low)}|{fmt(p.kick_density)}|{fmt(p.delta_kick)}|"
            f"{fmt(p.vocal_activity)}|{fmt(p.build_score)}|{fmt(p.snare_roll)}|"
            f"{fmt(p.contrast_score)}|{fmt(p.novelty_score)}|{fmt(p.pre_drop_gap)}|{drop:4s}"
        )

    lines.append("")
    lines.append(f"Drop candidates: {features.drop_candidates[:5]}")

    return "\n".join(lines)


def check_grid_alignment(
    path: Path,
    bpm: float,
    first_beat_s: float,
    *,
    sr: int = 22050,
    tolerance_ms: float = 30.0,
) -> tuple[bool, float]:
    """Check if beatgrid aligns with audio onsets."""
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
        errors.append(float(np.min(diffs) * 1000))

    if not errors:
        return True, 0.0

    median_error = float(np.median(errors))
    return median_error <= tolerance_ms, median_error
