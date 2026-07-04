"""Stem-splitting pipeline.

Per song, produces 24-bit WAV stems in the existing folder layout
`stem-output/htdemucs_ft/<song_base>/`:

    <title>_vocals.wav       (BS-Roformer + Mel-Band Roformer ensemble, averaged)
    <title>_no_vocals.wav    (same ensemble, instrumental side)
    <title>_drums.wav        (Demucs htdemucs_ft on the original mix)
    <title>_drums_2.wav      (byte-identical copy for Ableton)
    <title>_drums_3.wav      (byte-identical copy)
    <title>_drums_4.wav      (byte-identical copy)
    <title>_bass.wav         (Demucs htdemucs_ft on the original mix)
    <title>_other.wav        (Demucs htdemucs_ft on the original mix)
    original_<song>.<ext>    (input file moved in after success)

`<title>` is parsed from the input filename via parse_song_title().
For "Artist - Title.mp3" it is "Title"; for filenames with no separator
it is the whole stem.

Architecture: parallel decomposition. The vocal ensemble and Demucs both
operate on the original input mix. Demucs's own vocals output is discarded
(the ensemble's vocals are the keepers). This keeps Demucs on in-distribution
input (full mix with vocals) and avoids inheriting Roformer artifacts.

Tooling per platform (auto-selected):
    Windows / Linux:  audio-separator           (CUDA via [gpu] extras)
    macOS:            mlx-audio-separator       (MLX-native, Apple Silicon)

Verified audio-separator CLI flags (from
https://github.com/nomadkaraoke/python-audio-separator README, fetched
2026-04-19; mlx-audio-separator ports the same surface):

    -m, --model_filename       e.g. -m htdemucs_ft.yaml
    --output_dir               directory to write outputs
    --output_format            WAV (default is FLAC)
    --sample_rate              44100
    --demucs_shifts            inference-time augmentation count (default 2)
    --demucs_overlap           chunk overlap fraction (default 0.25)
    --demucs_segment_size      chunk size; 7 keeps within model memory limits

Notes:
- There is no `--use_cuda` flag. GPU is auto-detected from the installed
  extras (`[gpu]` vs `[cpu]`).
- There is no CLI flag to set output bit depth; audio-separator writes WAV
  at its default depth. Each stem is read and re-written here as 24-bit
  PCM_24 with soundfile.
- Default output filename pattern is `<input_stem>_(<Stem>)_<model_id>.wav`
  where `<Stem>` is one of Vocals / Instrumental / Drums / Bass / Other.
  We glob on the `_(<Stem>)_` token to locate each output, then convert and
  rename to our final `<title>_<stem>.wav`.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import soundfile as sf

VOCAL_BS_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
VOCAL_MEL_MODEL = "vocals_mel_band_roformer.ckpt"
DEMUCS_MODEL = "htdemucs_ft.yaml"

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma")
OUTPUT_MODEL_SUBDIR = "htdemucs_ft"


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
def _separator_export_dir(song_stems_dir: Path):
    """Directory for audio-separator / mlx-audio-separator ``--output_dir``.

    On macOS, mlx-audio-io can fail with ``OSStatus 'dta?'`` when writing WAVs
    to external or network volumes (e.g. under ``/Volumes/``). Use a local
    scratch folder there and copy stems into ``song_stems_dir`` via soundfile.

    Windows and Linux are unchanged: separator writes directly into
    ``song_stems_dir``.
    """
    song_stems_dir = Path(song_stems_dir)
    if platform.system() != "Darwin":
        yield song_stems_dir
        return

    scratch_root = Path.home() / "Library" / "Caches" / "stem-splitting-scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="sep-", dir=scratch_root))
    try:
        yield work_dir
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


def clean_partial_state(song_stems_dir: Path, title: str) -> None:
    """Remove leftover intermediates and partial stems from prior failed runs.

    Idempotent: safe to call before each song and inside failure handlers.
    Does NOT touch `original_*.<ext>` files (those mark successful runs).
    """
    song_stems_dir = Path(song_stems_dir)
    if not song_stems_dir.exists():
        return

    intermediate_suffixes = (
        "_vocals_bs.wav", "_no_vocals_bs.wav",
        "_vocals_mel.wav", "_no_vocals_mel.wav",
    )
    final_suffixes = (
        "_vocals.wav", "_no_vocals.wav",
        "_drums.wav", "_drums_2.wav", "_drums_3.wav", "_drums_4.wav",
        "_bass.wav", "_other.wav",
    )
    for suffix in intermediate_suffixes + final_suffixes:
        f = song_stems_dir / f"{title}{suffix}"
        if f.exists():
            f.unlink()

    leftover_tokens = {"vocals", "instrumental", "drums", "bass", "other"}
    for f in song_stems_dir.glob("*_(*)_*.wav"):
        name = f.name
        lo, hi = name.find("_("), name.find(")_")
        if lo != -1 and hi != -1 and name[lo + 2 : hi].lower() in leftover_tokens:
            f.unlink()


def _convert_separator_output_to_24bit(
    separator_dir: Path, stem_tokens, target_path: Path
) -> None:
    """Locate an audio-separator output matching any `_(<token>)_` in
    `stem_tokens` (case-insensitive) under ``separator_dir``, read it, write
    24-bit PCM_24 WAV at ``target_path``, then delete the source. Raises
    FileNotFoundError if no match.

    Different upstream models name the same stem differently. BS-Roformer
    writes `_(Vocals)_` / `_(Instrumental)_`, Mel-Band Roformer writes
    `_(vocals)_` / `_(other)_` (lowercase, and "other" for the instrumental
    side), Demucs writes `_(Drums)_` / `_(Bass)_` / `_(Other)_` / `_(Vocals)_`.
    Accepting a list of aliases here lets the caller stay declarative.
    """
    if isinstance(stem_tokens, str):
        stem_tokens = (stem_tokens,)
    separator_dir = Path(separator_dir)
    wanted = {t.lower() for t in stem_tokens}

    matches = []
    for f in separator_dir.glob("*_(*)_*.wav"):
        name = f.name
        lo = name.find("_(")
        hi = name.find(")_", lo + 2)
        if lo == -1 or hi == -1:
            continue
        token = name[lo + 2 : hi].lower()
        if token in wanted:
            matches.append(f)

    if not matches:
        raise FileNotFoundError(
            f"No separator output matching tokens {sorted(wanted)} found in {separator_dir}"
        )
    if len(matches) > 1:
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    src = matches[0]

    audio, sr = sf.read(src, dtype="float32")
    sf.write(target_path, audio, sr, subtype="PCM_24")
    src.unlink()


def run_vocal_ensemble(input_path: str, song_stems_dir: Path, title: str) -> None:
    """Run BS-Roformer + Mel-Band Roformer on the original mix and average outputs.

    Writes <title>_vocals.wav and <title>_no_vocals.wav as 24-bit PCM_24,
    then deletes the per-model intermediates.
    """
    song_stems_dir = Path(song_stems_dir)
    cmd_tool = _separator_cmd()

    with _separator_export_dir(song_stems_dir) as sep_dir:
        base_args = [
            "--output_dir", str(sep_dir),
            "--output_format", "WAV",
            "--sample_rate", "44100",
        ]

        print("  [vocals] BS-Roformer pass...")
        subprocess.run(
            [*cmd_tool, input_path, "-m", VOCAL_BS_MODEL, *base_args],
            check=True,
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Vocals",), song_stems_dir / f"{title}_vocals_bs.wav"
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Instrumental", "Other"), song_stems_dir / f"{title}_no_vocals_bs.wav"
        )

        print("  [vocals] Mel-Band Roformer pass...")
        subprocess.run(
            [*cmd_tool, input_path, "-m", VOCAL_MEL_MODEL, *base_args],
            check=True,
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Vocals",), song_stems_dir / f"{title}_vocals_mel.wav"
        )
        _convert_separator_output_to_24bit(
            sep_dir, ("Instrumental", "Other"), song_stems_dir / f"{title}_no_vocals_mel.wav"
        )

    print("  [vocals] Averaging ensemble outputs...")
    bs_v, sr_v = sf.read(song_stems_dir / f"{title}_vocals_bs.wav", dtype="float32")
    mel_v, sr_v_m = sf.read(song_stems_dir / f"{title}_vocals_mel.wav", dtype="float32")
    if sr_v != sr_v_m:
        raise ValueError(f"Sample rate mismatch between BS ({sr_v}) and Mel ({sr_v_m}) vocals")
    n = min(bs_v.shape[0], mel_v.shape[0])
    sf.write(
        song_stems_dir / f"{title}_vocals.wav",
        (bs_v[:n] + mel_v[:n]) / 2,
        sr_v,
        subtype="PCM_24",
    )

    bs_i, sr_i = sf.read(song_stems_dir / f"{title}_no_vocals_bs.wav", dtype="float32")
    mel_i, sr_i_m = sf.read(song_stems_dir / f"{title}_no_vocals_mel.wav", dtype="float32")
    if sr_i != sr_i_m:
        raise ValueError(f"Sample rate mismatch between BS ({sr_i}) and Mel ({sr_i_m}) no_vocals")
    n = min(bs_i.shape[0], mel_i.shape[0])
    sf.write(
        song_stems_dir / f"{title}_no_vocals.wav",
        (bs_i[:n] + mel_i[:n]) / 2,
        sr_i,
        subtype="PCM_24",
    )

    for intermediate in (
        f"{title}_vocals_bs.wav", f"{title}_no_vocals_bs.wav",
        f"{title}_vocals_mel.wav", f"{title}_no_vocals_mel.wav",
    ):
        (song_stems_dir / intermediate).unlink()


def run_htdemucs(input_path: str, song_stems_dir: Path, title: str) -> None:
    """Run Demucs htdemucs_ft on the original mix; produce 24-bit drums/bass/other.

    Discards Demucs's vocals output (the Roformer ensemble's vocals are kept).
    """
    song_stems_dir = Path(song_stems_dir)
    cmd_tool = _separator_cmd()

    with _separator_export_dir(song_stems_dir) as sep_dir:
        print("  [stems] htdemucs_ft pass on original mix...")
        subprocess.run(
            [
                *cmd_tool, input_path,
                "-m", DEMUCS_MODEL,
                "--output_dir", str(sep_dir),
                "--output_format", "WAV",
                "--sample_rate", "44100",
                "--demucs_shifts", "2",
                "--demucs_overlap", "0.25",
                "--demucs_segment_size", "7",
            ],
            check=True,
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

        for f in sep_dir.glob("*_(*)_*.wav"):
            name = f.name
            lo, hi = name.find("_("), name.find(")_")
            if lo != -1 and hi != -1 and name[lo + 2 : hi].lower() == "vocals":
                f.unlink()


def process_audio_folder(input_folder: str, output_folder: str) -> None:
    audio_files = [
        f for f in os.listdir(input_folder)
        if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
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

            run_vocal_ensemble(input_path, song_stems_dir, title)

            run_htdemucs(input_path, song_stems_dir, title)

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

