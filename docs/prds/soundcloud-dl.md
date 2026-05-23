# PRD: soundcloud_dl

**Status:** Lost — recreate.

## Purpose

Download SoundCloud tracks at best quality as MP3 320kbps via `yt-dlp`; embed title, artist, artwork. Support Go+ via OAuth token.

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Output | `../Downloads/YYYY-MM-DD/` relative to script | `paths.DOWNLOADS / today` |
| Args | URL(s), `--auth-token`, `--output-dir` | Same |

## Dependencies

- `yt-dlp` (CLI subprocess)
- `ffmpeg` (for transcode/embed)

## Behavior

- `check_preview_only()` — detect 30s preview via `--dump-json`.
- Download with metadata embed.
- Docstring listed HuntingSzn-style usage examples.

## Recreation notes

- **~5 KB**.
- Share implementation with `yt_audio_dl` in `packages/downloads/`.
- Makefile: `make sc-dl URL=...`.
