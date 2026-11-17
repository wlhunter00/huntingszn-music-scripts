# Stem splitting pipeline

**Status:** Implemented in `packages/stem_split/`. Canonical CLI is `stem-split` / `stem-verify`.

## Purpose

Batch-process songs into 24-bit / 44.1 kHz WAV stems for Ableton:

- Vocal ensemble: BS-Roformer Viperx 1297 + Kimberley Mel-Band Roformer, averaged.
- Demucs `htdemucs_ft` drums / bass / other on the **original mix**.
- Optional, default-off vocal cleanup: crowd-strip the mix before vocals, dry the wet vocal stem, extract a lead-only vocal.

Demucs vocals are discarded. Wet ensemble vocals stay as `<title>_vocals.wav` even when dry/lead extras are written.

## Inputs / outputs

| | Path |
|--|------|
| Input | `Stem Splitting/songs-to-split/` (mp3/wav/flac/m4a/ogg/aac/wma) |
| Output | `Stem Splitting/stem-output/htdemucs_ft/<song_base>/` |

Per song:

| File | When |
|------|------|
| `{title}_vocals.wav` | Always. Wet ensemble vocals. Never overwritten by cleanup. |
| `{title}_no_vocals.wav` | Always. Wet ensemble instrumental. |
| `{title}_vocals_dry.wav` | `--dry-vocals` |
| `{title}_vocals_lead.wav` | `--karaoke` |
| `{title}_drums.wav` (+ `_drums_2..4` copies) | Always. Demucs on original mix. |
| `{title}_bass.wav`, `{title}_other.wav` | Always. Demucs on original mix. |
| `original_<file>` | Always. Input moved here after success. |

Title is parsed from `Artist - Title.ext` (first ` - ` split). Audio files are not committed; `*.wav` / `songs-to-split/` / `stem-output/` are gitignored.

## Dependencies

| Platform | Extra | Package |
|----------|-------|---------|
| Windows/Linux NVIDIA | `--extra gpu` | `audio-separator[gpu]>=0.48` + CUDA PyTorch |
| CPU | `--extra cpu` | `audio-separator>=0.48` |
| macOS Apple Silicon | `--extra mac` | `mlx-audio-separator[convert]>=0.1.7` |

```bash
uv sync --package stem-split --extra gpu    # Will's Windows NVIDIA box
uv sync --package stem-split --extra cpu
uv sync --package stem-split --extra mac
```

FFmpeg is required on macOS so mlx can copy inputs off `/Volumes`.

### mlx catalog gaps

mlx-audio-separator **0.1.7** (pinned extra) and **0.1.20** extra `models.json` both omit these audio-separator **0.48** filenames:

- `bs_roformer_instrumental_resurrection_gabox.ckpt`
- `bs_roformer_karaoke_anvuew.ckpt`
- `bs_roformer_karaoke_frazer_becruily.ckpt`
- `mel_band_roformer_instrumental_fullness_v4_gabox.ckpt`
- `mel_band_roformer_instrumental_fv8b_gabox.ckpt`
- `mel_band_roformer_vocals_fv7b_gabox.ckpt`

None of those are in the default ensemble, dry, karaoke, or crowd chains. If a Roformer cleanup model is missing at runtime, the pipeline falls through the chain (anvuew → less-aggressive anvuew → `UVR-DeEcho-DeReverb.pth`, then aufr33 denoise → Gabox denoise-debleed → `UVR-DeNoise.pth`).

Viperx 1297, Kim Mel, anvuew dereverb, aufr33 denoise, karaoke, crowd, and the A/B candidates below **are** in the mlx 0.1.7 extra list. UVR `.pth` fallbacks live in the UVR `download_checks.json` list that `list_supported_model_files` merges (not in extra `models.json`).

## CLI

```bash
uv run --package stem-split stem-split
uv run --package stem-split stem-split --dry-vocals --karaoke --crowd
uv run --package stem-split stem-split --vocal-models resurrection,kim-ft2-bleedless
uv run --package stem-split stem-split --list-vocal-models
uv run --package stem-split stem-verify
```

`--input` / `--output` default to `config.paths.STEM_INPUT` / `STEM_OUTPUT`. Makefile: `make stem-split`, `make stem-verify`, `make stem-split ARGS='--dry-vocals'`.

| Flag | Default | Effect |
|------|---------|--------|
| `--dry-vocals` | off | Dereverb then denoise **ensemble vocals only**. Writes `_vocals_dry.wav`. |
| `--karaoke` | off | Lead-only extraction **from ensemble vocals**. Writes `_vocals_lead.wav`. |
| `--crowd` | off | Crowd removal on the mix **before vocal extraction only**. Demucs still sees the original mix. |
| `--vocal-models A,B` | `viperx,kim` | Override the ensemble pair (alias or exact filename). At most two. |
| `--list-vocal-models` | | Print aliases and exit. |

`--dry-vocals` and `--karaoke` are independent: both read wet `_vocals.wav`. They are not chained (dry-lead is not produced).

### `--crowd` and Demucs

Crowd-cleaned audio is only the vocal-ensemble input. Drums / bass / other stay from `htdemucs_ft` on the original mix so the rhythm section does not inherit crowd-model artifacts or a missing-crowd spectrum. Reconstructing the full mix as vocals + no_vocals still uses the wet ensemble (crowd-shaped if `--crowd` was on).

## Model chain

Filenames verified against audio-separator **v0.48.0** `models.json` + `models-scores.json` / `list_supported_model_files` (UVR list merged). Keep-stems are mapped by `_(Token)_` name, never by file order or `target_stem`.

### Default vocal ensemble

1. `model_bs_roformer_ep_317_sdr_12.9755.ckpt` (Viperx 1297; UVR list, **not** in extra `models.json`)
2. `vocals_mel_band_roformer.ckpt` (Kim Mel; extra `models.json`)

Outputs averaged. One `--vocal-models` entry skips averaging. `BS-Roformer-SW.ckpt` is 6-stem: vocals stem is kept; instrumental is mix-minus-vocals (6-stem `Other` is not instrumental).

### `--dry-vocals`

1. Dereverb (keep cleaned, never residual):
   - `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt` — keep `noreverb` (YAML `target_instrument: noreverb`)
   - fallback `dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt` — same tokens
   - fallback `UVR-DeEcho-DeReverb.pth` — keep `No Reverb` (not `Reverb`)
2. Denoise the dereverbed vocal (keep cleaned):
   - `denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt` — keep `dry` (not `other`)
   - alt `mel_band_roformer_denoise_debleed_gabox.ckpt` — keep `Instrumental` (YAML target; `Vocals` is noise/bleed)
   - fallback `UVR-DeNoise.pth` — keep `No Noise`. Catalog `target_stem` is `noise` (the residual); we ignore that.

### `--karaoke`

1. `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt` — keep `Vocals`
2. `mel_band_roformer_karaoke_gabox.ckpt`
3. `mel_band_roformer_karaoke_becruily.ckpt`

### `--crowd`

`mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt` — keep `other` (YAML `target_instrument: crowd` is the residual).

## `stem-verify`

Reconstruction (check 6) is **wet** `_vocals.wav` + `_no_vocals.wav` vs original. Dry and lead files, if present, get 24-bit / 44.1 kHz and duration (±100 ms) checks only — not RMS reconstruction, not the 1 MB size floor.

`clean_partial_state` deletes the eight stems, `_vocals_dry.wav`, `_vocals_lead.wav`, `_mix_nocrowd.wav`, `_vocals_dereverb.wav`, per-model ensemble intermediates, and any leftover `_(Token)_` separator WAVs (including residuals).

## Vocal-model audit (sourced scores only)

Default ensemble is **not** swapped. Best in-catalog single-model SDR is close, but there is no sourced score for a new pair on Will's library, and 124-band BS-Roformer is not downloadable through audio-separator.

MVSEP leaderboard: https://mvsep.com/quality_checker/multisong_leaderboard?sort=vocals

audio-separator 0.48 extra catalog: https://github.com/karaokenerds/python-audio-separator/blob/v0.48.0/audio_separator/models.json

audio-separator scores (MUSDB-style medians, **not** MVSEP): https://github.com/karaokenerds/python-audio-separator/blob/v0.48.0/audio_separator/models-scores.json

| Role | Catalog filename | In 0.48 extra `models.json` | MVSEP vocals SDR | Source | Catalog median vocals SDR |
|------|------------------|-----------------------------|------------------|--------|---------------------------|
| Default ensemble | Viperx 1297 + Kim Mel (average) | Viperx: UVR list only; Kim: yes | **11.0692** | [entry 6782](https://www.mvsep.com/quality_checker/entry/6782) Kimberley Mel-Roformer + Viperx 1297 | n/a (pair) |
| Default BS leg | `model_bs_roformer_ep_317_sdr_12.9755.ckpt` | no (UVR / scores list) | 10.9195 (overlap 8) | [entry 6831](https://mvsep.com/quality_checker/entry/6831) names this checkpoint | 11.7742 ([models-scores.json](https://github.com/karaokenerds/python-audio-separator/blob/v0.48.0/audio_separator/models-scores.json)) |
| Default Mel leg | `vocals_mel_band_roformer.ckpt` | yes | ~11.08 (Kim 1101 / overlap 8) | [entry 7417](https://mvsep.com/quality_checker/multisong_leaderboard?algo_name_filter=kim) MelBand Roformer Kim 1101 overlap 8 | 12.5967 (same scores file; MUSDB tracks) |
| Not in catalog | BS Roformer 124 bands | **no** — no 124-band filename in `models.json` or `models-scores.json` | **12.3339** | [entry 10197](https://mvsep.com/quality_checker/entry/10197) | no sourced score in catalog |
| A/B BS | `bs_roformer_vocals_revive_v3e_unwa.ckpt` | yes | 10.9849 | [entry 8337](https://www.mvsep.com/quality_checker/entry/8337) BS-Roformer Revive3e | no sourced score |
| A/B BS | `bs_roformer_vocals_resurrection_unwa.ckpt` | yes | 11.3363 | [entry 8683](https://www.mvsep.com/quality_checker/entry/8683) BS-Roformer Resurrection | no sourced score |
| A/B 6-stem | `BS-Roformer-SW.ckpt` | yes | 11.3019 | [entry 8374](https://www.mvsep.com/quality_checker/entry/8374) BS Roformer SW (6 stems); also [mvsep algorithms/77](https://mvsep.com/algorithms/77) | no sourced score |
| A/B Mel | `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt` | yes | 11.0519 | [entry 7827](https://mvsep.com/quality_checker/multisong_leaderboard?algo_name_filter=kim) Kim melband/unwa_ft2_bleedless | no sourced vocal SDR (catalog has runtime only) |
| A/B Mel | `mel_band_roformer_kim_ft3_unwa.ckpt` | yes | **no sourced score** | Closest MVSEP row is [entry 10597](https://mvsep.com/quality_checker/multisong_leaderboard?algo_name_filter=kim) `mbr_kimft3_prev_unwa.ckpt` (11.0544) — **different filename** | no sourced score |

**Recommendation:** keep `viperx,kim`. Resurrection 11.3363 is a stronger *single* MVSEP vocal SDR than the 11.0692 pair, but fullness/bleedless tradeoffs differ and there is no sourced score for resurrection+Kim (or resurrection+bleedless) as an average. 124-band is the MVSEP #1 downloadable-model-class result (~12.33) and cannot be pulled through audio-separator 0.48. A/B on 3–5 real vocals before any default change.

`--vocal-models` aliases: `viperx`, `kim`, `revive-v3e`, `resurrection`, `sw`, `kim-ft2-bleedless`, `kim-ft3`.

## Runtime notes

### Windows NVIDIA

```bash
uv sync --package stem-split --extra gpu
```

Workspace `pyproject.toml` points Windows torch at the `pytorch-cu130` index. No `--use_cuda` flag; GPU comes from `audio-separator[gpu]`. First run downloads checkpoints into the separator model cache (not git).

### macOS mlx

```bash
uv sync --package stem-split --extra mac
```

Separator I/O is copied through `~/Library/Caches/stem-splitting-scratch` so mlx-audio-io is not asked to write `/Volumes`. Same CLI flags. If a Roformer cleanup checkpoint is missing, UVR `.pth` fallbacks run on the VR path.

### Tests

Unit tests mock the separator CLI. They do not download weights or commit audio. `make test-stem-split`.
