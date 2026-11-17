"""Keep-stem mapping is by token name, never file order or mtime."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from _audio import rms, write_separator_stem, write_wav
from stem_split.models import (
    CROWD_KEEP_TOKENS,
    DENOISE_KEEP_TOKENS,
    DEREVERB_KEEP_TOKENS,
    KARAOKE_KEEP_TOKENS,
)
from stem_split.pipeline import (
    _convert_separator_output_to_24bit,
    extract_stem_token,
)


class TestExtractStemToken:
    def test_standard_pattern(self) -> None:
        assert extract_stem_token("mix_(No Reverb)_UVR-DeEcho-DeReverb.wav") == "No Reverb"

    def test_noreverb_token(self) -> None:
        assert extract_stem_token("mix_(noreverb)_anvuew.wav") == "noreverb"

    def test_no_token(self) -> None:
        assert extract_stem_token("Title_vocals.wav") is None

    def test_vr_suffixless_pattern(self) -> None:
        assert extract_stem_token("mix_(No Reverb).wav") == "No Reverb"
        assert extract_stem_token("mix_(Reverb).wav") == "Reverb"
        assert extract_stem_token("mix_(No Noise).flac") == "No Noise"


class TestKeepStemMapping:
    def test_dereverb_picks_no_reverb_when_reverb_is_newer(self, tmp_path: Path) -> None:
        write_separator_stem(tmp_path, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9)
        time.sleep(0.02)
        write_separator_stem(tmp_path, "mix", "No Reverb", "UVR-DeEcho-DeReverb.pth", value=0.1)
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DEREVERB_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.1, abs=0.01)
        leftover = list(tmp_path.glob("*_(*)_*.wav"))
        tokens = {extract_stem_token(p.name) for p in leftover}
        assert "No Reverb" not in tokens
        assert "Reverb" in tokens

    def test_dereverb_picks_no_reverb_when_reverb_is_listed_first(self, tmp_path: Path) -> None:
        write_separator_stem(tmp_path, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9)
        write_separator_stem(tmp_path, "mix", "No Reverb", "UVR-DeEcho-DeReverb.pth", value=0.1)
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DEREVERB_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.1, abs=0.01)

    def test_anvuew_noreverb_not_reverb(self, tmp_path: Path) -> None:
        write_separator_stem(
            tmp_path, "mix", "reverb", "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt", 0.8
        )
        write_separator_stem(
            tmp_path, "mix", "noreverb", "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt", 0.2
        )
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DEREVERB_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.2, abs=0.01)

    def test_uvr_denoise_picks_no_noise_not_noise(self, tmp_path: Path) -> None:
        # models-scores target_stem is "noise" (residual). We still keep No Noise.
        write_separator_stem(tmp_path, "mix", "Noise", "UVR-DeNoise.pth", value=0.9)
        time.sleep(0.02)
        write_separator_stem(tmp_path, "mix", "No Noise", "UVR-DeNoise.pth", value=0.15)
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DENOISE_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.15, abs=0.01)

    def test_aufr33_denoise_picks_dry_not_other(self, tmp_path: Path) -> None:
        write_separator_stem(
            tmp_path, "mix", "other", "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt", 0.7
        )
        write_separator_stem(
            tmp_path, "mix", "dry", "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt", 0.25
        )
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DENOISE_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.25, abs=0.01)

    def test_gabox_denoise_picks_instrumental_not_vocals(self, tmp_path: Path) -> None:
        write_separator_stem(
            tmp_path, "mix", "Vocals", "mel_band_roformer_denoise_debleed_gabox.ckpt", 0.9
        )
        write_separator_stem(
            tmp_path, "mix", "Instrumental", "mel_band_roformer_denoise_debleed_gabox.ckpt", 0.3
        )
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DENOISE_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.3, abs=0.01)

    def test_crowd_picks_other_not_crowd(self, tmp_path: Path) -> None:
        write_separator_stem(
            tmp_path, "mix", "crowd", "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt", 0.9
        )
        write_separator_stem(
            tmp_path, "mix", "other", "mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt", 0.35
        )
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, CROWD_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.35, abs=0.01)

    def test_karaoke_picks_vocals_not_instrumental(self, tmp_path: Path) -> None:
        write_separator_stem(
            tmp_path, "vocals", "Instrumental",
            "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt", 0.8,
        )
        write_separator_stem(
            tmp_path, "vocals", "Vocals",
            "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt", 0.4,
        )
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, KARAOKE_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.4, abs=0.01)

    def test_duplicate_keep_token_raises(self, tmp_path: Path) -> None:
        write_wav(tmp_path / "a_(dry)_one.wav", value=0.1)
        write_wav(tmp_path / "b_(dry)_two.wav", value=0.2)
        with pytest.raises(FileExistsError, match="Multiple separator outputs"):
            _convert_separator_output_to_24bit(tmp_path, DENOISE_KEEP_TOKENS, tmp_path / "keep.wav")

    def test_missing_keep_stem_raises(self, tmp_path: Path) -> None:
        write_separator_stem(tmp_path, "mix", "Reverb", "UVR-DeEcho-DeReverb.pth", value=0.9)
        with pytest.raises(FileNotFoundError, match="keep-tokens"):
            _convert_separator_output_to_24bit(
                tmp_path, DEREVERB_KEEP_TOKENS, tmp_path / "keep.wav"
            )

    def test_vr_suffixless_no_reverb_keep(self, tmp_path: Path) -> None:
        write_wav(tmp_path / "mix_(Reverb).wav", value=0.9)
        write_wav(tmp_path / "mix_(No Reverb).wav", value=0.1)
        dest = tmp_path / "keep.wav"
        _convert_separator_output_to_24bit(tmp_path, DEREVERB_KEEP_TOKENS, dest)
        assert rms(dest) == pytest.approx(0.1, abs=0.01)
        leftover = {p.name for p in tmp_path.glob("mix_(*).wav")}
        assert "mix_(No Reverb).wav" not in leftover
        assert "mix_(Reverb).wav" in leftover
