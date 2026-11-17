"""Catalog of audio-separator 0.48 model filenames and keep-stem token maps.

Filenames were checked against audio-separator v0.48.0:

- extra Roformer list: ``audio_separator/models.json``
- UVR + Demucs + scores: ``audio_separator/models-scores.json``
- ``Separator.list_supported_model_files`` merges UVR ``download_checks.json``
  with ``models.json`` (Viperx 1297, Demucs yaml, UVR VR .pth live in the UVR
  list, not in the extra Roformer JSON)

YAML ``training.instruments`` / ``target_instrument`` (model-configs release)
is the source of keep vs residual stem names. Keep tokens are matched by name,
never by file order or ``target_stem`` (UVR-DeNoise and the crowd model both
label the residual as the target).

Sources:
- https://github.com/karaokenerds/python-audio-separator/blob/v0.48.0/audio_separator/models.json
- https://github.com/karaokenerds/python-audio-separator/blob/v0.48.0/audio_separator/models-scores.json
- https://github.com/karaokenerds/python-audio-separator/releases/tag/model-configs
"""

from __future__ import annotations

from dataclasses import dataclass

# Default vocal ensemble (unchanged). Viperx 1297 is in models-scores / UVR list,
# not in the extra 0.48 models.json Roformer block.
VOCAL_BS_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
VOCAL_MEL_MODEL = "vocals_mel_band_roformer.ckpt"
DEMUCS_MODEL = "htdemucs_ft.yaml"

# --dry-vocals: dereverb then denoise, keep the cleaned stem only.
DEREVERB_MODELS = (
    "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt",
    "dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt",
    "UVR-DeEcho-DeReverb.pth",
)
# anvuew YAML instruments: noreverb, reverb (keep noreverb).
# UVR-DeEcho-DeReverb writes _(No Reverb)_ / _(Reverb)_.
DEREVERB_KEEP_TOKENS = ("noreverb", "No Reverb", "dry")

DENOISE_MODELS = (
    "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt",
    "mel_band_roformer_denoise_debleed_gabox.ckpt",
    "UVR-DeNoise.pth",
)
# aufr33 YAML: dry / other (keep dry). Gabox YAML: Instrumental / Vocals with
# target Instrumental (keep Instrumental — Vocals is the noise/bleed residual).
# UVR-DeNoise writes _(Noise)_ / _(No Noise)_ and models-scores target_stem is
# "noise" (the residual) — keep "No Noise" only.
DENOISE_KEEP_TOKENS = ("dry", "No Noise", "Instrumental")

# --karaoke: lead vocal from the ensemble vocal stem.
KARAOKE_MODELS = (
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
    "mel_band_roformer_karaoke_gabox.ckpt",
    "mel_band_roformer_karaoke_becruily.ckpt",
)
KARAOKE_KEEP_TOKENS = ("Vocals", "Lead Vocals", "lead_only")

# --crowd: crowd removal on the mix before vocal extraction. Crowd YAML
# instruments: crowd / other, target_instrument crowd (the residual). Keep other.
CROWD_MODELS = ("mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt",)
CROWD_KEEP_TOKENS = ("other", "No Crowd", "Instrumental")

# Tokens that are never the keep stem for cleanup models. Used by tests and by
# leftover cleanup so a residual cannot be mistaken for the cleaned file.
RESIDUAL_STEM_TOKENS = frozenset(
    {
        "reverb",
        "noise",
        "crowd",
        "echo",
        "no dry",
    }
)

VOCAL_KEEP_TOKENS = ("Vocals",)
INSTRUMENTAL_KEEP_TOKENS = ("Instrumental", "Other")

# A/B aliases for --vocal-models. Values are exact catalog filenames.
VOCAL_MODEL_ALIASES = {
    "viperx": VOCAL_BS_MODEL,
    "viperx-1297": VOCAL_BS_MODEL,
    "kim": VOCAL_MEL_MODEL,
    "kim-mel": VOCAL_MEL_MODEL,
    "revive-v3e": "bs_roformer_vocals_revive_v3e_unwa.ckpt",
    "resurrection": "bs_roformer_vocals_resurrection_unwa.ckpt",
    "sw": "BS-Roformer-SW.ckpt",
    "kim-ft2-bleedless": "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
    "kim-ft3": "mel_band_roformer_kim_ft3_unwa.ckpt",
}

# 6-stem; Vocals is usable as an ensemble leg, instrumental is mix-minus-vocals.
SIX_STEM_VOCAL_MODELS = frozenset({"BS-Roformer-SW.ckpt"})

# mlx-audio-separator 0.1.7 / 0.1.20 extra models.json is missing these 0.48
# filenames. None are in the default dry/karaoke/crowd/ensemble chains.
MLX_MISSING_FROM_AUDIO_SEPARATOR_048 = (
    "bs_roformer_instrumental_resurrection_gabox.ckpt",
    "bs_roformer_karaoke_anvuew.ckpt",
    "bs_roformer_karaoke_frazer_becruily.ckpt",
    "mel_band_roformer_instrumental_fullness_v4_gabox.ckpt",
    "mel_band_roformer_instrumental_fv8b_gabox.ckpt",
    "mel_band_roformer_vocals_fv7b_gabox.ckpt",
)


@dataclass(frozen=True)
class VocalCandidate:
    alias: str
    filename: str
    role: str
    notes: str


VOCAL_CANDIDATES = (
    VocalCandidate(
        "viperx", VOCAL_BS_MODEL, "default BS leg", "UVR list; not in extra models.json"
    ),
    VocalCandidate("kim", VOCAL_MEL_MODEL, "default Mel leg", "in extra models.json"),
    VocalCandidate(
        "revive-v3e",
        "bs_roformer_vocals_revive_v3e_unwa.ckpt",
        "BS alternative",
        "in extra models.json",
    ),
    VocalCandidate(
        "resurrection",
        "bs_roformer_vocals_resurrection_unwa.ckpt",
        "BS alternative",
        "in extra models.json",
    ),
    VocalCandidate(
        "sw",
        "BS-Roformer-SW.ckpt",
        "6-stem (vocals A/B only)",
        "in extra models.json; no_vocals via mix-minus-vocals",
    ),
    VocalCandidate(
        "kim-ft2-bleedless",
        "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt",
        "Mel alternative",
        "in extra models.json",
    ),
    VocalCandidate(
        "kim-ft3",
        "mel_band_roformer_kim_ft3_unwa.ckpt",
        "Mel alternative",
        "in extra models.json",
    ),
)


def normalize_stem_token(token: str) -> str:
    """Lowercase stem token; keep spaces so 'No Reverb' != 'noreverb'."""
    return token.strip().lower()


def resolve_vocal_models(spec: str | None) -> tuple[str, ...]:
    """Parse ``--vocal-models a,b`` into catalog filenames.

    Each item is an alias from ``VOCAL_MODEL_ALIASES`` or an exact filename
    (must contain a ``.``). Default ensemble when spec is None or empty.
    """
    if spec is None or not spec.strip():
        return (VOCAL_BS_MODEL, VOCAL_MEL_MODEL)

    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise ValueError("--vocal-models parsed to an empty list")
    if len(parts) > 2:
        raise ValueError("--vocal-models accepts at most two models (the ensemble pair)")

    resolved: list[str] = []
    for part in parts:
        key = part.lower()
        if key in VOCAL_MODEL_ALIASES:
            resolved.append(VOCAL_MODEL_ALIASES[key])
            continue
        if "." in part:
            resolved.append(part)
            continue
        known = ", ".join(sorted(VOCAL_MODEL_ALIASES))
        raise ValueError(f"Unknown vocal model {part!r}. Use a filename or one of: {known}")
    return tuple(resolved)


def keep_tokens_for_vocal_model(filename: str, *, vocals: bool) -> tuple[str, ...]:
    if vocals:
        return VOCAL_KEEP_TOKENS
    return INSTRUMENTAL_KEEP_TOKENS
