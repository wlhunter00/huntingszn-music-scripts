# PRD: Stem splitting pipeline

**Status:** Code still on drive at `../Stem Splitting/` — migrate into `packages/stem_split/`, do not rewrite from scratch.

## Purpose

Batch-process songs into 24-bit WAV stems for Ableton: vocal ensemble (BS-Roformer + Mel-Band Roformer averaged) plus Demucs `htdemucs_ft` drums/bass/other. Discards Demucs vocals in favor of ensemble vocals.

## Files (present)

| File | Role |
|------|------|
| `demucs-master.py` | Main pipeline |
| `verify_stems.py` | Post-run validation |
| `requirements.txt` | Platform-conditional separator deps |

## Inputs / outputs

| | Path (relative to Stem Splitting) |
|--|-----------------------------------|
| Input | `songs-to-split/*.mp3` (and wav/flac/m4a/ogg/aac/wma) |
| Output | `stem-output/htdemucs_ft/<song_base>/` |
| Per song | `{title}_vocals.wav`, `{title}_no_vocals.wav`, `{title}_drums.wav` (+ `_drums_2..4` copies), `{title}_bass.wav`, `{title}_other.wav`, `original_<file>` |

Title parsed from `Artist - Title.ext` (first ` - ` split).

## Dependencies

- macOS: `mlx-audio-separator`
- Windows/Linux: `audio-separator[gpu]`
- `soundfile` for 24-bit PCM output
- FFmpeg (via separator tooling)

## CLI (today)

```bash
cd "/Volumes/Will Hunter Music/Stem Splitting"
python demucs-master.py   # uses songs-to-split + stem-output
python verify_stems.py
```

## Recreation / migration notes

- Add `--input` / `--output` args defaulting to `config.paths.STEM_INPUT` / `STEM_OUTPUT`.
- Target Makefile target: `make stem-split`.
- Do not commit `stem-output/`, `songs-to-split/`, or `Source Files/`.
