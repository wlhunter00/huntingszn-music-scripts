"""Stem-splitting pipeline.

Per song, produces 24-bit WAV stems in the existing folder layout
``stem-output/htdemucs_ft/<song_base>/``:

    <title>_vocals.wav       (BS-Roformer + Mel-Band Roformer ensemble, averaged)
    <title>_no_vocals.wav    (same ensemble, instrumental side)
    <title>_vocals_dry.wav   (optional; --dry-vocals on the wet vocal stem)
    <title>_vocals_lead.wav  (optional; --karaoke lead-only from the wet vocal stem)
    <title>_drums.wav        (Demucs htdemucs_ft on the original mix)
    <title>_drums_2.wav      (byte-identical copy for Ableton)
    <title>_drums_3.wav      (byte-identical copy)
    <title>_drums_4.wav      (byte-identical copy)
    <title>_bass.wav         (Demucs htdemucs_ft on the original mix)
    <title>_other.wav        (Demucs htdemucs_ft on the original mix)
    original_<song>.<ext>    (input file moved in after success)

``<title>`` is parsed from the input filename via parse_song_title().
For "Artist - Title.mp3" it is "Title"; for filenames with no separator
it is the whole stem.

Architecture: parallel decomposition. The vocal ensemble and Demucs both
operate on the original input mix unless ``--crowd`` rewrites only the
vocal-extraction input. Demucs's own vocals output is discarded (the
ensemble's vocals are the keepers). This keeps Demucs on in-distribution
input (full mix with vocals) and avoids inheriting Roformer artifacts.

``--crowd`` never changes the Demucs input. That is intentional: drums /
bass / other stay consistent with the original mix even when crowd is
stripped for the vocal pass.

Tooling per platform (auto-selected):
    Windows / Linux:  audio-separator           (CUDA via [gpu] extra, CPU via [cpu] extra)
    macOS:            mlx-audio-separator       (MLX-native, Apple Silicon via [mac] extra)

Install extras:
    uv sync --package stem-split --extra gpu   # NVIDIA GPU with CUDA
    uv sync --package stem-split --extra cpu   # CPU-only (no NVIDIA required)
    uv sync --package stem-split --extra mac   # macOS Apple Silicon

Verified audio-separator CLI flags (from
https://github.com/nomadkaraoke/python-audio-separator README; mlx-audio-separator
ports the same surface):

    -m, --model_filename       e.g. -m htdemucs_ft.yaml
    --output_dir               directory to write outputs
    --output_format            WAV (default is FLAC)
    --sample_rate              44100
    --demucs_shifts            inference-time augmentation count (default 2)
    --demucs_overlap           chunk overlap fraction (default 0.25)
    --demucs_segment_size      chunk size; 7 keeps within model memory limits

Notes:
- There is no ``--use_cuda`` flag. GPU is auto-detected from the installed
  extras (``[gpu]`` vs ``[cpu]``).
- There is no CLI flag to set output bit depth; audio-separator writes WAV
  at its default depth. Each stem is read and re-written here as 24-bit
  PCM_24 with soundfile.
- Default output filename pattern is ``<input_stem>_(<Stem>)_<model_id>.wav``
  (older VR models emit ``<input_stem>_(<Stem>).wav``). ``<Stem>`` is
  model-specific (Vocals / Instrumental / No Reverb / dry / other / …). We
  match the trailing ``_(<Stem>)`` token to locate each output, then convert
  and rename to our final ``<title>_<stem>.wav``. Keep-stems are chosen by
  token name, never by file order. Archived sources (``original_<input>``)
  are not separator outputs: they lack a trailing ``_(Stem)_<model>`` /
  ``_(Stem)`` suffix, so cleanup will not unlink them even when the title
  contains ``_(Reverb)_`` or the input itself was named ``original_...``.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from stem_split.models import (
    CROWD_KEEP_TOKENS,
    CROWD_MODELS,
    DEMUCS_MODEL,
    DENOISE_KEEP_TOKENS,
    DENOISE_MODELS,
    DEREVERB_KEEP_TOKENS,
    DEREVERB_MODELS,
    INSTRUMENTAL_KEEP_TOKENS,
    KARAOKE_KEEP_TOKENS,
    KARAOKE_MODELS,
    SIX_STEM_VOCAL_MODELS,
    VOCAL_BS_MODEL,
    VOCAL_KEEP_TOKENS,
    VOCAL_MEL_MODEL,
    normalize_stem_token,
    resolve_vocal_models,
)

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma")
OUTPUT_MODEL_SUBDIR = "htdemucs_ft"

INTERMEDIATE_SUFFIXES = (
    "_vocals_bs.wav",
    "_no_vocals_bs.wav",
    "_vocals_mel.wav",
    "_no_vocals_mel.wav",
    "_mix_nocrowd.wav",
    "_vocals_dereverb.wav",
)
FINAL_SUFFIXES = (
    "_vocals.wav",
    "_no_vocals.wav",
    "_vocals_dry.wav",
    "_vocals_lead.wav",
    "_drums.wav",
    "_drums_2.wav",
    "_drums_3.wav",
    "_drums_4.wav",
    "_bass.wav",
    "_other.wav",
)
# All parenthesised separator tokens we may emit, including residuals, so a
# failed run cannot leave _(Reverb)_ / _(Noise)_ / _(Crowd)_ files behind.
SEPARATOR_LEFTOVER_TOKENS = frozenset(
    {
        "vocals",
        "instrumental",
        "drums",
        "bass",
        "other",
        "noreverb",
        "reverb",
        "no reverb",
        "dry",
        "crowd",
        "no crowd",
        "noise",
        "no noise",
        "echo",
        "no echo",
        "guitar",
        "piano",
        "lead vocals",
        "backing vocals",
        "lead_only",
        "backing_only",
        "no dry",
    }
)


@dataclass(frozen=True)
class StemSplitOptions:
    """Opt-in vocal cleanup / model-override flags. All default OFF / default ensemble."""

    dry_vocals: bool = False
    karaoke: bool = False
    crowd: bool = False
    vocal_models: tuple[str, ...] | None = None


def _separator_cmd() -> list[str]:
    """Return argv prefix for the platform audio-separator CLI.

    Invoke via ``sys.executable`` instead of the console-script shim. uv's
    Windows trampolines can fail with "failed to canonicalize script path"
    when spawned from ``subprocess``.
    """
    import importlib.metadata as metadata

    name = "mlx-audio-separator" if platform.system() == "Darwin" else "audio-separator"
    for ep in metadata.entry_points(group="console_scripts"):
        if ep.name == name:
            module, _, func = ep.value.partition(":")
            launcher = (
                f"import sys; sys.argv[0]={name!r}; "
                f"from {module} import {func}; {func}()"
            )
            return [sys.executable, "-c", launcher]
    return [name]


@contextmanager
def _separator_export_dir(_song_stems_dir: Path):
    """Scratch directory for audio-separator / mlx-audio-separator ``--output_dir``.

    Always isolated from ``song_stems_dir`` so archived ``original_<input>``
    files cannot be mistaken for separator dumps. Keep-stems are converted
    out with soundfile; the scratch dir is deleted afterwards.

    On macOS the scratch root is ``~/Library/Caches/stem-splitting-scratch``
    because mlx-audio-io can fail with ``OSStatus 'dta?'`` when writing WAVs
    to external or network volumes (e.g. under ``/Volumes/``).
    """
    if platform.system() == "Darwin":
        scratch_root = Path.home() / "Library" / "Caches" / "stem-splitting-scratch"
        scratch_root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="sep-", dir=scratch_root))
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="stem-sep-"))
    try:
        yield work_dir
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@contextmanager
def _separator_input(input_path: str | Path):
    """Local copy of the mix for mlx-audio-io, which cannot load files on /Volumes."""
    src = Path(input_path)
    if platform.system() != "Darwin":
        yield str(src)
        return

    scratch_root = Path.home() / "Library" / "Caches" / "stem-splitting-scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="in-", dir=scratch_root))
    dest = work_dir / f"{src.stem}.wav"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-ar",
                "44100",
                "-ac",
                "2",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        yield str(dest)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _sanitize_for_filesystem(name: str) -> str:
    """Strip trailing whitespace/dots/dashes and replace path-illegal chars.

    Windows refuses directory or file names ending in space or dot. The
    characters <>:"/\\|?* are also illegal on Windows. We replace those with
    underscores and strip trailing whitespace/dots so paths are always
    creatable on every platform. Trailing dashes are also stripped so titles
    parsed from filenames like "Artist - Reload - .mp3" come out as "Reload"
    rather than "Reload -".
    """
    illegal = '<>:"/\\|?*'
    cleaned = "".join("_" if c in illegal else c for c in name)
    return cleaned.rstrip(" .-")


def parse_song_title(input_filename: str) -> str:
    """Extract the song title from an "Artist - Title.ext" filename.

    Splits on the first " - " separator and returns everything after.
    If no separator is present, returns the whole filename stem.
    Leading/trailing whitespace is stripped so titles like "Reload - "
    (from "Artist - Reload - .mp3") become "Reload".
    """
    stem = os.path.splitext(os.path.basename(input_filename))[0]
    title = stem.split(" - ", 1)[1] if " - " in stem else stem
    return _sanitize_for_filesystem(title.strip())


def _is_separator_token_suffix(rest: str) -> bool:
    """True if ``rest`` is empty (VR suffixless) or ``_<model>`` with no whitespace."""
    if rest == "":
        return True
    if not rest.startswith("_"):
        return False
    model = rest[1:]
    return bool(model) and not any(ch.isspace() for ch in model)


def extract_stem_token(filename: str) -> str | None:
    """Return the trailing separator stem token, or None.

    Accepts ``<input>_(Stem)_<model>.wav`` and the older VR form
    ``<input>_(Stem).wav``. ``<model>`` must not contain whitespace, so a
    title like ``Club _(Reverb)_ Mix.wav`` is not a separator output. When
    the input stem itself contains ``_(...)``, the last valid token wins —
    including outputs from an input named ``original_...``.
    """
    name = Path(filename).name
    lower = name.lower()
    ext = next((e for e in (".wav", ".flac") if lower.endswith(e)), None)
    if ext is None:
        return None
    body = name[: -len(ext)]
    search_end = len(body)
    while True:
        close = body.rfind(")", 0, search_end)
        if close == -1:
            return None
        lo = body.rfind("_(", 0, close)
        if lo == -1:
            return None
        token = body[lo + 2 : close]
        rest = body[close + 1 :]
        if token and _is_separator_token_suffix(rest):
            return token
        search_end = lo


def is_archived_source(path: Path | str) -> bool:
    """True for ``original_<input>`` files moved into the stems folder after success.

    Used only by cleanup of ``song_stems_dir``. Separator dumps (including
    those from an input named ``original_...``) live in the scratch export
    dir and are not matched here.
    """
    return Path(path).name.startswith("original_")


def _iter_separator_wavs(separator_dir: Path):
    seen: set[Path] = set()
    for pattern in ("*_(*)_*.wav", "*_(*).wav"):
        for f in Path(separator_dir).glob(pattern):
            if f in seen or extract_stem_token(f.name) is None:
                continue
            seen.add(f)
            yield f


def _delete_separator_wavs(separator_dir: Path) -> None:
    """Remove leftover separator outputs (residuals and unmatched stems)."""
    for f in list(_iter_separator_wavs(separator_dir)):
        if f.exists():
            f.unlink()


def clean_partial_state(song_stems_dir: Path, title: str) -> None:
    """Remove leftover intermediates and partial stems from prior failed runs.

    Idempotent: safe to call before each song and inside failure handlers.
    Never unlinks archived ``original_<input>`` sources, even when the
    original filename itself ends in ``_(Vocals)`` or ``_(Reverb)_Remix``.
    """
    song_stems_dir = Path(song_stems_dir)
    if not song_stems_dir.exists():
        return

    for suffix in INTERMEDIATE_SUFFIXES + FINAL_SUFFIXES:
        f = song_stems_dir / f"{title}{suffix}"
        if f.exists():
            f.unlink()

    for f in _iter_separator_wavs(song_stems_dir):
        if is_archived_source(f):
            continue
        token = extract_stem_token(f.name)
        if token is not None and normalize_stem_token(token) in SEPARATOR_LEFTOVER_TOKENS:
            f.unlink()


def _convert_separator_output_to_24bit(
    separator_dir: Path, stem_tokens, target_path: Path
) -> None:
    """Locate an audio-separator output matching any ``_(<token>)_`` in
    ``stem_tokens`` (case-insensitive) under ``separator_dir``, read it, write
    24-bit PCM_24 WAV at ``target_path``, then delete the source. Raises
    FileNotFoundError if no match.

    Tokens are tried in listed order. If several files share the same token,
    raise rather than picking by mtime or directory order — cleanup models
    emit residual and keep stems whose names must be mapped explicitly.
    """
    if isinstance(stem_tokens, str):
        stem_tokens = (stem_tokens,)
    separator_dir = Path(separator_dir)
    preferred = [normalize_stem_token(t) for t in stem_tokens]

    by_token: dict[str, list[Path]] = {}
    for f in _iter_separator_wavs(separator_dir):
        token = extract_stem_token(f.name)
        if token is None:
            continue
        key = normalize_stem_token(token)
        if key in preferred:
            by_token.setdefault(key, []).append(f)

    src = None
    for key in preferred:
        matches = by_token.get(key, [])
        if not matches:
            continue
        if len(matches) > 1:
            names = sorted(p.name for p in matches)
            raise FileExistsError(
                f"Multiple separator outputs for keep-token {key!r} in "
                f"{separator_dir}: {names}. Refusing to guess by file order."
            )
        src = matches[0]
        break

    if src is None:
        raise FileNotFoundError(
            f"No separator output matching keep-tokens {list(stem_tokens)} found in {separator_dir}"
        )

    audio, sr = sf.read(src, dtype="float32")
    sf.write(target_path, audio, sr, subtype="PCM_24")
    src.unlink()


def _run_separator(
    cmd_tool: Sequence[str],
    input_path: str,
    model: str,
    sep_dir: Path,
    extra_args: Sequence[str] = (),
) -> None:
    """Invoke the platform separator CLI. Tests monkeypatch this."""
    subprocess.run(
        [
            *cmd_tool,
            input_path,
            "-m",
            model,
            "--output_dir",
            str(sep_dir),
            "--output_format",
            "WAV",
            "--sample_rate",
            "44100",
            *extra_args,
        ],
        check=True,
    )


def _run_separator_with_fallbacks(
    input_path: str,
    song_stems_dir: Path,
    model_chain: Sequence[str],
    keep_tokens: Sequence[str],
    dest: Path,
    label: str,
    extra_args: Sequence[str] = (),
) -> str:
    """Try models in order until one writes a keep-stem. Return the winner."""
    errors: list[str] = []
    cmd_tool = _separator_cmd()
    for model in model_chain:
        print(f"  [{label}] trying {model}...")
        with _separator_export_dir(song_stems_dir) as sep_dir:
            try:
                _run_separator(cmd_tool, input_path, model, sep_dir, extra_args)
                _convert_separator_output_to_24bit(sep_dir, keep_tokens, dest)
                _delete_separator_wavs(sep_dir)
                print(f"  [{label}] using {model}")
                return model
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                FileExistsError,
                OSError,
            ) as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
                _delete_separator_wavs(sep_dir)
                print(f"  [{label}] {model} unavailable or missing keep-stem; trying next")
    raise RuntimeError(f"{label} failed for all models {list(model_chain)}: {errors}")


def _as_2d(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio[:, np.newaxis]
    return audio


def _lowpass_fir(cutoff_hz: float, sr: int, numtaps: int = 255) -> np.ndarray:
    """Hamming-windowed sinc low-pass. ``numtaps`` is forced odd."""
    if numtaps % 2 == 0:
        numtaps += 1
    nyq = sr / 2.0
    fc = min(max(cutoff_hz, 1.0), nyq * 0.99) / sr
    n = np.arange(numtaps, dtype=np.float64)
    m = (numtaps - 1) / 2.0
    h = np.sinc(2.0 * fc * (n - m))
    h *= np.hamming(numtaps)
    s = float(h.sum())
    if s != 0.0:
        h /= s
    return h


def _filter_channel(samples: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    return np.convolve(samples, kernel, mode="same")


def _resample_audio(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Band-limited resample. Output length is round(n * sr_to / sr_from).

    Downsampling low-passes below the destination Nyquist before interpolation
    so ultrasonics (e.g. 30 kHz on a 96 kHz mix) are not folded into the
    instrumental as audible aliases.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if sr_from == sr_to:
        return audio.astype(np.float32)
    if sr_from <= 0 or sr_to <= 0:
        raise ValueError(f"Invalid sample rates: mix={sr_from}, target={sr_to}")
    n_src = audio.shape[0]
    if sr_from > sr_to and n_src > 8:
        taps = 255 if n_src >= 255 else (n_src if n_src % 2 else n_src - 1)
        kernel = _lowpass_fir(0.45 * sr_to, sr_from, numtaps=max(taps, 3))
        if audio.ndim == 1:
            audio = _filter_channel(audio, kernel)
        else:
            audio = np.stack(
                [_filter_channel(audio[:, c], kernel) for c in range(audio.shape[1])],
                axis=1,
            )
    n_dst = max(1, int(round(n_src * sr_to / sr_from)))
    t_src = np.linspace(0.0, 1.0, n_src, endpoint=False)
    t_dst = np.linspace(0.0, 1.0, n_dst, endpoint=False)
    if audio.ndim == 1:
        return np.interp(t_dst, t_src, audio).astype(np.float32)
    channels = [np.interp(t_dst, t_src, audio[:, c]) for c in range(audio.shape[1])]
    return np.stack(channels, axis=1).astype(np.float32)


def _align_channels(mix: np.ndarray, vocals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mix = _as_2d(mix)
    vocals = _as_2d(vocals)
    if mix.shape[1] == vocals.shape[1]:
        return mix, vocals
    if mix.shape[1] == 1:
        return np.repeat(mix, vocals.shape[1], axis=1), vocals
    if vocals.shape[1] == 1:
        return mix, np.repeat(vocals, mix.shape[1], axis=1)
    nch = min(mix.shape[1], vocals.shape[1])
    return mix[:, :nch], vocals[:, :nch]


def _mix_minus_vocals(mix_path: str | Path, vocals_path: Path, dest: Path) -> None:
    """Build an instrumental by subtracting vocals from the mix (6-stem models).

    Separator vocals are 44.1 kHz; the mix on Windows/Linux may still be
    48 kHz or 96 kHz. Band-limit and resample the mix to the vocals, then
    write 24-bit at the vocal sample rate.
    """
    mix, sr_m = sf.read(mix_path, dtype="float32")
    vocals, sr_v = sf.read(vocals_path, dtype="float32")
    mix = _resample_audio(_as_2d(mix), sr_m, sr_v)
    vocals = _as_2d(vocals)
    mix, vocals = _align_channels(mix, vocals)
    n = min(mix.shape[0], vocals.shape[0])
    sf.write(dest, mix[:n] - vocals[:n], sr_v, subtype="PCM_24")


def run_vocal_ensemble(
    input_path: str,
    song_stems_dir: Path,
    title: str,
    vocal_models: Sequence[str] | None = None,
) -> None:
    """Run the vocal model pair on the (possibly crowd-cleaned) mix and average.

    Writes <title>_vocals.wav and <title>_no_vocals.wav as 24-bit PCM_24,
    then deletes the per-model intermediates. One model skips averaging.
    """
    song_stems_dir = Path(song_stems_dir)
    models = tuple(vocal_models) if vocal_models else (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)
    if not models:
        raise ValueError("vocal ensemble requires at least one model")
    cmd_tool = _separator_cmd()

    vocals_parts: list[Path] = []
    instrumental_parts: list[Path] = []

    with _separator_export_dir(song_stems_dir) as sep_dir:
        base_args = ()
        for i, model in enumerate(models):
            tag = "bs" if i == 0 else "mel" if i == 1 else f"m{i}"
            print(f"  [vocals] pass {i + 1}/{len(models)}: {model}")
            _run_separator(cmd_tool, input_path, model, sep_dir, base_args)
            v_path = song_stems_dir / f"{title}_vocals_{tag}.wav"
            i_path = song_stems_dir / f"{title}_no_vocals_{tag}.wav"
            _convert_separator_output_to_24bit(sep_dir, VOCAL_KEEP_TOKENS, v_path)
            if model in SIX_STEM_VOCAL_MODELS:
                # 6-stem "Other" is not instrumental. Prefer mix-minus-vocals.
                try:
                    _convert_separator_output_to_24bit(sep_dir, ("Instrumental",), i_path)
                except FileNotFoundError:
                    print(f"  [vocals] {model} has no instrumental stem; mix-minus-vocals")
                    _mix_minus_vocals(input_path, v_path, i_path)
            else:
                _convert_separator_output_to_24bit(sep_dir, INSTRUMENTAL_KEEP_TOKENS, i_path)
            _delete_separator_wavs(sep_dir)
            vocals_parts.append(v_path)
            instrumental_parts.append(i_path)

    if len(models) > 1:
        print("  [vocals] Averaging ensemble outputs...")
    else:
        print("  [vocals] Writing single-model outputs...")
    _average_wavs(vocals_parts, song_stems_dir / f"{title}_vocals.wav")
    _average_wavs(instrumental_parts, song_stems_dir / f"{title}_no_vocals.wav")
    for part in vocals_parts + instrumental_parts:
        if part.exists():
            part.unlink()


def _average_wavs(paths: Sequence[Path], dest: Path) -> None:
    if len(paths) == 1:
        shutil.copy(paths[0], dest)
        return
    arrays = []
    sr0 = None
    for p in paths:
        audio, sr = sf.read(p, dtype="float32")
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            raise ValueError(f"Sample rate mismatch in ensemble: {sr} vs {sr0} ({p})")
        arrays.append(audio)
    n = min(a.shape[0] for a in arrays)
    stacked = sum(a[:n] for a in arrays) / len(arrays)
    sf.write(dest, stacked, sr0, subtype="PCM_24")


def run_crowd_removal(input_path: str, song_stems_dir: Path, dest: Path) -> None:
    """Strip crowd from the mix. Keep the remaining stem, never the crowd residual."""
    print("  [crowd] removing crowd from mix (Demucs still uses the original mix)...")
    with _separator_input(input_path) as local_input:
        _run_separator_with_fallbacks(
            local_input,
            song_stems_dir,
            CROWD_MODELS,
            CROWD_KEEP_TOKENS,
            dest,
            "crowd",
        )


def run_dry_vocals(vocals_path: Path, song_stems_dir: Path, title: str) -> None:
    """Dereverb then denoise the wet vocal stem. Writes <title>_vocals_dry.wav."""
    song_stems_dir = Path(song_stems_dir)
    dest = song_stems_dir / f"{title}_vocals_dry.wav"
    dereverb_tmp = song_stems_dir / f"{title}_vocals_dereverb.wav"
    print("  [dry-vocals] dereverb then denoise on ensemble vocals...")
    with _separator_input(vocals_path) as local_v:
        _run_separator_with_fallbacks(
            local_v,
            song_stems_dir,
            DEREVERB_MODELS,
            DEREVERB_KEEP_TOKENS,
            dereverb_tmp,
            "dry-dereverb",
        )
    try:
        with _separator_input(dereverb_tmp) as local_d:
            _run_separator_with_fallbacks(
                local_d,
                song_stems_dir,
                DENOISE_MODELS,
                DENOISE_KEEP_TOKENS,
                dest,
                "dry-denoise",
            )
    finally:
        if dereverb_tmp.exists():
            dereverb_tmp.unlink()


def run_karaoke(vocals_path: Path, song_stems_dir: Path, title: str) -> None:
    """Lead-vocal-only extraction from the wet ensemble vocal stem."""
    dest = Path(song_stems_dir) / f"{title}_vocals_lead.wav"
    print("  [karaoke] lead-vocal extraction on ensemble vocals...")
    with _separator_input(vocals_path) as local_v:
        _run_separator_with_fallbacks(
            local_v,
            song_stems_dir,
            KARAOKE_MODELS,
            KARAOKE_KEEP_TOKENS,
            dest,
            "karaoke",
        )


def run_htdemucs(input_path: str, song_stems_dir: Path, title: str) -> None:
    """Run Demucs htdemucs_ft on the original mix; produce 24-bit drums/bass/other.

    Discards Demucs's vocals output (the Roformer ensemble's vocals are kept).
    """
    song_stems_dir = Path(song_stems_dir)
    cmd_tool = _separator_cmd()

    with _separator_export_dir(song_stems_dir) as sep_dir:
        print("  [stems] htdemucs_ft pass on original mix...")
        _run_separator(
            cmd_tool,
            input_path,
            DEMUCS_MODEL,
            sep_dir,
            extra_args=(
                "--demucs_shifts",
                "2",
                "--demucs_overlap",
                "0.25",
                "--demucs_segment_size",
                "7",
            ),
        )

        _convert_separator_output_to_24bit(
            sep_dir, ("Drums",), song_stems_dir / f"{title}_drums.wav"
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Bass",), song_stems_dir / f"{title}_bass.wav"
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Other",), song_stems_dir / f"{title}_other.wav"
        )
        _delete_separator_wavs(sep_dir)


def process_audio_folder(
    input_folder: str,
    output_folder: str,
    options: StemSplitOptions | None = None,
) -> None:
    options = options or StemSplitOptions()
    vocal_models = options.vocal_models or resolve_vocal_models(None)

    audio_files = [
        f
        for f in os.listdir(input_folder)
        if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS) and not f.startswith("._")
    ]

    if not audio_files:
        print("No audio files found in input folder!")
        return

    for audio_file in audio_files:
        input_path = os.path.join(input_folder, audio_file)
        file_base = _sanitize_for_filesystem(os.path.splitext(audio_file)[0])
        title = parse_song_title(audio_file)
        song_stems_dir = Path(output_folder) / OUTPUT_MODEL_SUBDIR / file_base

        print(f"\nProcessing: {audio_file}  (title='{title}')")
        os.makedirs(song_stems_dir, exist_ok=True)

        try:
            clean_partial_state(song_stems_dir, title)

            with _separator_input(input_path) as local_mix:
                vocal_input = local_mix
                nocrowd_path = song_stems_dir / f"{title}_mix_nocrowd.wav"
                if options.crowd:
                    run_crowd_removal(local_mix, song_stems_dir, nocrowd_path)
                    vocal_input = str(nocrowd_path)

                with _separator_input(vocal_input) as local_vocal:
                    run_vocal_ensemble(
                        local_vocal, song_stems_dir, title, vocal_models=vocal_models
                    )

                wet_vocals = song_stems_dir / f"{title}_vocals.wav"
                if options.dry_vocals:
                    run_dry_vocals(wet_vocals, song_stems_dir, title)
                if options.karaoke:
                    run_karaoke(wet_vocals, song_stems_dir, title)

                run_htdemucs(local_mix, song_stems_dir, title)

            if nocrowd_path.exists():
                nocrowd_path.unlink()

            drums_path = song_stems_dir / f"{title}_drums.wav"
            for i in range(2, 5):
                shutil.copy(drums_path, song_stems_dir / f"{title}_drums_{i}.wav")

            original_destination = song_stems_dir / f"original_{audio_file}"
            shutil.move(input_path, original_destination)
            print(f"Successfully processed: {audio_file}")

        except Exception as exc:
            print(f"Warning: processing failed for {audio_file}: {exc}")
            print("  Cleaning partial state; original file left in songs-to-split/ for retry.")
            try:
                clean_partial_state(song_stems_dir, title)
            except Exception as cleanup_exc:
                print(f"  Cleanup also failed: {cleanup_exc}")
            continue
