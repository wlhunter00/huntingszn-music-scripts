"""Verifier: reconstruction stays on wet vocals; dry/lead get format+duration only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from _audio import FRAMES, SR, write_wav
from stem_split.verify import (
    check_durations,
    check_files_exist,
    check_format_24bit_44k,
    check_vocals_plus_no_vocals_reconstructs,
)


def _stem_dir(tmp_path: Path, *, with_optional: bool = False, dry_is_16bit: bool = False) -> Path:
    dest = tmp_path / "Artist - Title"
    dest.mkdir(parents=True)
    title = "Title"
    mix = np.full((FRAMES, 2), 0.5, dtype=np.float32)
    v = np.full((FRAMES, 2), 0.3, dtype=np.float32)
    nv = np.full((FRAMES, 2), 0.2, dtype=np.float32)
    sf.write(dest / "original_Artist - Title.wav", mix, SR, subtype="PCM_24")
    for sfx, audio in (
        ("_vocals.wav", v),
        ("_no_vocals.wav", nv),
        ("_drums.wav", nv * 0.4),
        ("_drums_2.wav", nv * 0.4),
        ("_drums_3.wav", nv * 0.4),
        ("_drums_4.wav", nv * 0.4),
        ("_bass.wav", nv * 0.3),
        ("_other.wav", nv * 0.3),
    ):
        sf.write(dest / f"{title}{sfx}", audio, SR, subtype="PCM_24")
    if with_optional:
        dry_subtype = "PCM_16" if dry_is_16bit else "PCM_24"
        sf.write(dest / f"{title}_vocals_dry.wav", v * 0.9, SR, subtype=dry_subtype)
        sf.write(dest / f"{title}_vocals_lead.wav", v * 0.8, SR, subtype="PCM_24")
    return dest


def test_required_stems_pass_without_optional(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path)
    ok, detail = check_files_exist(dest, "Title")
    assert ok, detail
    assert "Optional" not in detail


def test_optional_not_required_but_flagged_when_present(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path, with_optional=True)
    ok, detail = check_files_exist(dest, "Title")
    assert ok, detail
    assert "vocals_dry" in detail
    assert "vocals_lead" in detail


def test_leftover_dry_intermediate_fails(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path)
    write_wav(dest / "Title_vocals_dereverb.wav")
    write_wav(dest / "Title_mix_nocrowd.wav")
    ok, detail = check_files_exist(dest, "Title")
    assert not ok
    assert "vocals_dereverb" in detail
    assert "mix_nocrowd" in detail


def test_separator_residual_leftover_fails(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path)
    write_wav(dest / "mix_(Reverb)_UVR-DeEcho-DeReverb.wav")
    ok, detail = check_files_exist(dest, "Title")
    assert not ok
    assert "Reverb" in detail


def test_archived_source_with_token_in_name_is_not_leftover(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path)
    write_wav(dest / "original_Artist - Track_(Reverb)_Remix.wav")
    ok, detail = check_files_exist(dest, "Title")
    assert ok, detail


def test_format_checks_dry_and_lead(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path, with_optional=True)
    ok, detail = check_format_24bit_44k(dest, "Title")
    assert ok, detail
    dest16 = _stem_dir(tmp_path / "bad", with_optional=True, dry_is_16bit=True)
    ok, detail = check_format_24bit_44k(dest16, "Title")
    assert not ok
    assert "vocals_dry" in detail
    assert "PCM_16" in detail


def test_duration_checks_dry_and_lead(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path, with_optional=True)
    original = dest / "original_Artist - Title.wav"
    ok, detail = check_durations(dest, "Title", original)
    assert ok, detail
    # Stretch dry so duration check fails for the optional file only.
    long = np.full((FRAMES * 20, 2), 0.1, dtype=np.float32)
    sf.write(dest / "Title_vocals_dry.wav", long, SR, subtype="PCM_24")
    ok, detail = check_durations(dest, "Title", original)
    assert not ok
    assert "vocals_dry" in detail


def test_reconstruction_uses_wet_not_dry(tmp_path: Path) -> None:
    dest = _stem_dir(tmp_path, with_optional=True)
    # Corrupt dry so a mistaken reconstruction against dry would fail.
    zeros = np.zeros((FRAMES, 2), dtype=np.float32)
    sf.write(dest / "Title_vocals_dry.wav", zeros, SR, subtype="PCM_24")
    original = dest / "original_Artist - Title.wav"
    ok, detail = check_vocals_plus_no_vocals_reconstructs(dest, "Title", original)
    assert ok, detail
