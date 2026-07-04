"""Smoke-test verifier for demucs-master.py output.

Runs the 9 checks from the plan against the most recently processed song.
Each check prints PASS / FAIL with a brief diagnostic; final summary at end.

Usage:
    python verify_stems.py [<song_stems_dir>] [--input <original_input_path>]

If <song_stems_dir> is omitted, picks the most recently modified subfolder
of `stem-output/htdemucs_ft/`. If --input is omitted, looks for the
`original_*` file inside the stems folder.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from stem_split._bootstrap import ensure_config_importable

ensure_config_importable()

from config.paths import STEM_OUTPUT_MODEL
from stem_split.pipeline import parse_song_title

OUTPUT_ROOT = STEM_OUTPUT_MODEL


def db(linear):
    return 20.0 * np.log10(max(linear, 1e-12))


def rms(audio):
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def find_latest_song_dir():
    if not OUTPUT_ROOT.exists():
        return None
    subdirs = [p for p in OUTPUT_ROOT.iterdir() if p.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda p: p.stat().st_mtime)


def find_original(song_dir: Path):
    matches = list(song_dir.glob("original_*"))
    return matches[0] if matches else None


def check_files_exist(song_dir: Path, title: str):
    expected = [
        f"{title}_vocals.wav", f"{title}_no_vocals.wav",
        f"{title}_drums.wav", f"{title}_drums_2.wav",
        f"{title}_drums_3.wav", f"{title}_drums_4.wav",
        f"{title}_bass.wav", f"{title}_other.wav",
    ]
    missing = [f for f in expected if not (song_dir / f).exists()]
    intermediates_present = []
    for pat in (
        f"{title}_vocals_bs.wav", f"{title}_no_vocals_bs.wav",
        f"{title}_vocals_mel.wav", f"{title}_no_vocals_mel.wav",
    ):
        if (song_dir / pat).exists():
            intermediates_present.append(pat)
    intermediates_present += [p.name for p in song_dir.glob("*_(Vocals)_*.wav")]
    intermediates_present += [p.name for p in song_dir.glob("*_(Instrumental)_*.wav")]
    intermediates_present += [p.name for p in song_dir.glob("*_(Drums)_*.wav")]
    intermediates_present += [p.name for p in song_dir.glob("*_(Bass)_*.wav")]
    intermediates_present += [p.name for p in song_dir.glob("*_(Other)_*.wav")]

    if missing:
        return False, f"Missing files: {missing}"
    if intermediates_present:
        return False, f"Leftover intermediates: {intermediates_present}"
    return True, "All 8 stems present, no intermediates."


def check_format_24bit_44k(song_dir: Path, title: str):
    expected = [
        f"{title}_vocals.wav", f"{title}_no_vocals.wav",
        f"{title}_drums.wav", f"{title}_drums_2.wav",
        f"{title}_drums_3.wav", f"{title}_drums_4.wav",
        f"{title}_bass.wav", f"{title}_other.wav",
    ]
    bad = []
    for f in expected:
        path = song_dir / f
        if not path.exists():
            bad.append(f"{f}: missing")
            continue
        info = sf.info(path)
        if info.subtype != "PCM_24":
            bad.append(f"{f}: subtype={info.subtype}")
        if info.samplerate != 44100:
            bad.append(f"{f}: sr={info.samplerate}")
    if bad:
        return False, "; ".join(bad)
    return True, "All 8 stems are 24-bit PCM @ 44.1 kHz."


def check_file_sizes(song_dir: Path, title: str):
    expected = [
        f"{title}_vocals.wav", f"{title}_no_vocals.wav",
        f"{title}_drums.wav", f"{title}_drums_2.wav",
        f"{title}_drums_3.wav", f"{title}_drums_4.wav",
        f"{title}_bass.wav", f"{title}_other.wav",
    ]
    too_small = []
    for f in expected:
        path = song_dir / f
        if not path.exists():
            too_small.append(f"{f}: missing")
            continue
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb < 1.0:
            too_small.append(f"{f}: {size_mb:.2f} MB")
    if too_small:
        return False, "; ".join(too_small)
    return True, "All 8 stems > 1 MB."


def check_durations(song_dir: Path, title: str, original: Path):
    info_orig = sf.info(original)
    expected = [
        f"{title}_vocals.wav", f"{title}_no_vocals.wav",
        f"{title}_drums.wav", f"{title}_drums_2.wav",
        f"{title}_drums_3.wav", f"{title}_drums_4.wav",
        f"{title}_bass.wav", f"{title}_other.wav",
    ]
    bad = []
    for f in expected:
        path = song_dir / f
        if not path.exists():
            bad.append(f"{f}: missing")
            continue
        info = sf.info(path)
        diff_ms = abs(info.duration - info_orig.duration) * 1000
        if diff_ms > 100:
            bad.append(f"{f}: {info.duration:.3f}s vs orig {info_orig.duration:.3f}s (diff {diff_ms:.0f} ms)")
    if bad:
        return False, "; ".join(bad)
    return True, f"All 8 stems within 100 ms of input duration ({info_orig.duration:.2f}s)."


def check_original_moved(song_dir: Path, original_input_path: Path):
    if original_input_path is not None and original_input_path.exists():
        return False, f"Original still in songs-to-split: {original_input_path}"
    moved = list(song_dir.glob("original_*"))
    if not moved:
        return False, f"No original_* file found in {song_dir}"
    return True, f"Original moved as {moved[0].name}."


def _read_mono(path: Path):
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if audio.shape[1] > 1:
        audio = audio.mean(axis=1)
    else:
        audio = audio[:, 0]
    return audio, sr


def check_vocals_plus_no_vocals_reconstructs(song_dir: Path, title: str, original: Path):
    """Compare RMS power of (vocals+no_vocals) against the original.

    RMS is a global power statistic that does not require samples to be aligned
    or even at the same sample rate, so we compare each signal's RMS in its
    own native sample rate. The original may be 48 kHz while stems are 44.1 kHz
    after explicit resampling in the pipeline; that's expected.
    """
    v, sr_v = _read_mono(song_dir / f"{title}_vocals.wav")
    nv, sr_nv = _read_mono(song_dir / f"{title}_no_vocals.wav")
    orig, sr_o = _read_mono(original)
    if sr_v != sr_nv:
        return False, f"Stem SR mismatch: vocals={sr_v}, no_vocals={sr_nv}"
    n = min(len(v), len(nv))
    sum_signal = v[:n] + nv[:n]
    rms_diff_db = abs(db(rms(sum_signal)) - db(rms(orig)))
    if rms_diff_db > 5.0:
        return False, (
            f"RMS diff vocals+no_vocals vs original: {rms_diff_db:.2f} dB (>5.0); "
            f"sr_stems={sr_v}, sr_orig={sr_o}"
        )
    return True, (
        f"vocals+no_vocals RMS within {rms_diff_db:.2f} dB of original "
        f"(sr_stems={sr_v}, sr_orig={sr_o})."
    )


def check_demucs_stems_vs_no_vocals(song_dir: Path, title: str, original: Path):
    d, sr = _read_mono(song_dir / f"{title}_drums.wav")
    b, _ = _read_mono(song_dir / f"{title}_bass.wav")
    o, _ = _read_mono(song_dir / f"{title}_other.wav")
    nv, _ = _read_mono(song_dir / f"{title}_no_vocals.wav")
    orig, _ = _read_mono(original)
    n = min(len(d), len(b), len(o), len(nv), len(orig))
    sum_dbo = d[:n] + b[:n] + o[:n]
    diff_vs_nv = abs(db(rms(sum_dbo)) - db(rms(nv[:n])))
    diff_vs_orig = abs(db(rms(sum_dbo)) - db(rms(orig[:n])))
    closest = min(diff_vs_nv, diff_vs_orig)
    if closest > 15.0:
        return False, f"drums+bass+other RMS diff: vs no_vocals={diff_vs_nv:.2f} dB, vs orig={diff_vs_orig:.2f} dB (both >15)"
    if closest > 8.0:
        return True, f"WITHIN-LOOSE-TOLERANCE: drums+bass+other vs no_vocals={diff_vs_nv:.2f} dB, vs orig={diff_vs_orig:.2f} dB (closest>{8.0:.0f} dB but <15 dB; acceptable per plan)"
    return True, f"drums+bass+other within {closest:.2f} dB RMS of nearest reference (vs no_vocals={diff_vs_nv:.2f}, vs orig={diff_vs_orig:.2f})"


def _sha256(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_drum_copies_identical(song_dir: Path, title: str):
    base = _sha256(song_dir / f"{title}_drums.wav")
    bad = []
    for i in (2, 3, 4):
        h = _sha256(song_dir / f"{title}_drums_{i}.wav")
        if h != base:
            bad.append(f"drums_{i} hash differs")
    if bad:
        return False, "; ".join(bad)
    return True, f"drums_2/3/4 are byte-identical to drums.wav (sha256={base[:16]}...)."


def check_parse_song_title():
    cases = [
        ("Artist - Title.mp3", "Title"),
        ("A, B - Some - Song.mp3", "Some - Song"),
        ("NoSeparator.mp3", "NoSeparator"),
    ]
    bad = []
    for inp, expected in cases:
        got = parse_song_title(inp)
        if got != expected:
            bad.append(f"{inp!r} -> {got!r} (expected {expected!r})")
    if bad:
        return False, "; ".join(bad)
    return True, f"All {len(cases)} parse_song_title cases pass."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song_dir", nargs="?", default=None)
    ap.add_argument("--input", default=None,
                    help="Path to original input file (defaults to None; use this to verify it was moved)")
    args = ap.parse_args()

    song_dir = Path(args.song_dir) if args.song_dir else find_latest_song_dir()
    if song_dir is None or not song_dir.exists():
        print("ERROR: no song folder found")
        sys.exit(2)

    title = parse_song_title(song_dir.name + ".mp3")
    print(f"Verifying: {song_dir}")
    print(f"Parsed title: '{title}'")

    original = find_original(song_dir)
    if original is None:
        print("ERROR: no original_* file in stems folder")
        sys.exit(2)
    print(f"Original: {original.name}")
    print()

    original_input_path = Path(args.input) if args.input else None

    checks = [
        ("1. All 8 files exist, no intermediates",
         lambda: check_files_exist(song_dir, title)),
        ("2. 24-bit PCM @ 44.1 kHz",
         lambda: check_format_24bit_44k(song_dir, title)),
        ("3. File sizes > 1 MB",
         lambda: check_file_sizes(song_dir, title)),
        ("4. Durations match input within 100 ms",
         lambda: check_durations(song_dir, title, original)),
        ("5. Original moved into stems folder",
         lambda: check_original_moved(song_dir, original_input_path)),
        ("6. vocals+no_vocals RMS within 5 dB of original",
         lambda: check_vocals_plus_no_vocals_reconstructs(song_dir, title, original)),
        ("7. drums+bass+other RMS within 8 dB (or 15 dB loose)",
         lambda: check_demucs_stems_vs_no_vocals(song_dir, title, original)),
        ("8. drums_2/3/4 byte-identical to drums",
         lambda: check_drum_copies_identical(song_dir, title)),
        ("9. parse_song_title unit cases",
         lambda: check_parse_song_title),
    ]
    checks[-1] = ("9. parse_song_title unit cases", check_parse_song_title)

    pass_count = 0
    fail_count = 0
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"EXCEPTION: {e!r}"
        status = "PASS" if ok else "FAIL"
        if ok:
            pass_count += 1
        else:
            fail_count += 1
        print(f"  [{status}] {name}: {detail}")

    print()
    print(f"Summary: {pass_count} passed, {fail_count} failed")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
