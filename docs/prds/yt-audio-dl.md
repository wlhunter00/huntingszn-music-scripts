# PRD: yt_audio_dl

**Status:** Lost — recreate.

## Purpose

Download YouTube audio as MP3 320kbps with metadata via `yt-dlp`.

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Output | `../Downloads/YYYY-MM-DD/` | `paths.DOWNLOADS / today` |
| Args | URL(s), `--output-dir` | Same |

## Dependencies

- `yt-dlp`, `ffmpeg`

## Behavior

- `download_audio(url, output_dir)` — `-x`, audio extract, mp3 320.
- Multi-URL argparse loop.

## Recreation notes

- **~2.7 KB** — pair with `soundcloud_dl` in one module with `source` discriminator.
