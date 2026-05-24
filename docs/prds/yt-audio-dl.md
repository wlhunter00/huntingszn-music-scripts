# PRD: yt_audio_dl

**Status:** Implemented in `packages/downloads/downloads/youtube.py`.

## Purpose

Download YouTube audio at the **best available source quality** (AAC/Opus/etc. via `bestaudio/best`, minimal re-encoding) with thumbnail + metadata via `yt-dlp`. Optional MP3 320 for DJ stacks that require MP3.

## Inputs / outputs

| | Default | Notes |
|--|---------|--------|
| Output | `paths.DOWNLOADS / YYYY-MM-DD/` | Override with `--output-dir` |
| Args | URL(s), `--output-dir`, `--mp3`, `--playlist` | `--no-playlist` is default unless `--playlist` |

## Dependencies

- `yt-dlp`, `ffmpeg`

## Behavior

- Default: `-f bestaudio/best -x --audio-format best --embed-thumbnail --add-metadata`
- `--mp3`: legacy `-x --audio-format mp3 --audio-quality 320K`
- Multi-URL argparse loop.

## Notes

YouTube is lossy; “highest quality” means the best offered stream, not lossless.
