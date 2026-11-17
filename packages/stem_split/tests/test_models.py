"""Catalog filenames, aliases, and keep-token maps."""

from __future__ import annotations

import pytest
from stem_split.models import (
    CROWD_KEEP_TOKENS,
    CROWD_MODELS,
    DENOISE_KEEP_TOKENS,
    DENOISE_MODELS,
    DEREVERB_KEEP_TOKENS,
    DEREVERB_MODELS,
    KARAOKE_KEEP_TOKENS,
    KARAOKE_MODELS,
    MLX_MISSING_FROM_AUDIO_SEPARATOR_048,
    RESIDUAL_STEM_TOKENS,
    VOCAL_BS_MODEL,
    VOCAL_MEL_MODEL,
    normalize_stem_token,
    resolve_vocal_models,
)

# Frozen snapshot of audio-separator 0.48 filenames this package actually invokes.
# Sourced from v0.48.0 models.json + models-scores.json (UVR list).
CATALOG_048 = {
    VOCAL_BS_MODEL,
    VOCAL_MEL_MODEL,
    *DEREVERB_MODELS,
    *DENOISE_MODELS,
    *KARAOKE_MODELS,
    *CROWD_MODELS,
    "bs_roformer_vocals_revive_v3e_unwa.ckpt",
    "bs_roformer_vocals_resurrection_unwa.ckpt",
    "BS-Roformer-SW.ckpt",
    "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
    "mel_band_roformer_kim_ft3_unwa.ckpt",
    "htdemucs_ft.yaml",
}


class TestResolveVocalModels:
    def test_default_pair(self) -> None:
        assert resolve_vocal_models(None) == (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)
        assert resolve_vocal_models("") == (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)

    def test_aliases(self) -> None:
        assert resolve_vocal_models("resurrection,kim-ft2-bleedless") == (
            "bs_roformer_vocals_resurrection_unwa.ckpt",
            "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
        )

    def test_raw_filenames(self) -> None:
        got = resolve_vocal_models(f"{VOCAL_BS_MODEL},{VOCAL_MEL_MODEL}")
        assert got == (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)

    def test_single_model(self) -> None:
        assert resolve_vocal_models("kim") == (VOCAL_MEL_MODEL,)

    def test_rejects_three(self) -> None:
        with pytest.raises(ValueError, match="at most two"):
            resolve_vocal_models("viperx,kim,sw")

    def test_unknown_alias(self) -> None:
        with pytest.raises(ValueError, match="Unknown vocal model"):
            resolve_vocal_models("not-a-model")


class TestKeepTokensNeverResidual:
    def test_dereverb_excludes_reverb(self) -> None:
        keep = {normalize_stem_token(t) for t in DEREVERB_KEEP_TOKENS}
        assert "reverb" not in keep
        assert "noreverb" in keep
        assert "no reverb" in keep

    def test_denoise_excludes_noise_and_other(self) -> None:
        keep = {normalize_stem_token(t) for t in DENOISE_KEEP_TOKENS}
        assert "noise" not in keep
        assert "other" not in keep  # aufr33 residual
        assert "dry" in keep
        assert "no noise" in keep

    def test_crowd_excludes_crowd(self) -> None:
        keep = {normalize_stem_token(t) for t in CROWD_KEEP_TOKENS}
        assert "crowd" not in keep
        assert "other" in keep

    def test_karaoke_keep_is_vocals(self) -> None:
        keep = {normalize_stem_token(t) for t in KARAOKE_KEEP_TOKENS}
        assert "vocals" in keep
        assert "instrumental" not in keep

    def test_residual_set_covers_cleanup(self) -> None:
        assert "reverb" in RESIDUAL_STEM_TOKENS
        assert "noise" in RESIDUAL_STEM_TOKENS
        assert "crowd" in RESIDUAL_STEM_TOKENS


class TestCatalogFilenames:
    def test_no_invented_uvr_names(self) -> None:
        # Spec fallbacks match the catalog, not a guessed UVR-DeEcho-DeReverb vs De-Reverb.
        assert "UVR-DeEcho-DeReverb.pth" in DEREVERB_MODELS
        assert "UVR-DeNoise.pth" in DENOISE_MODELS
        assert "UVR-De-Reverb-aufr33-jarredou.pth" not in DEREVERB_MODELS

    def test_snapshot_covers_invoked_files(self) -> None:
        assert VOCAL_BS_MODEL in CATALOG_048
        assert "UVR-DeEcho-DeReverb.pth" in CATALOG_048
        assert "htdemucs_ft.yaml" in CATALOG_048

    def test_mlx_gap_list_is_explicit(self) -> None:
        for name in MLX_MISSING_FROM_AUDIO_SEPARATOR_048:
            assert name.endswith(".ckpt")
        for name in (*DEREVERB_MODELS, *DENOISE_MODELS, *KARAOKE_MODELS, *CROWD_MODELS):
            assert name not in MLX_MISSING_FROM_AUDIO_SEPARATOR_048
