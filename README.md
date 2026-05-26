# HuntingSzn Music Scripts

Private monorepo for DJ library tools, stem splitting, downloads, and harmonic matching.

**GitHub:** https://github.com/wlhunter00/huntingszn-music-scripts

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloaders
- [ffprobe](https://ffmpeg.org/) for key catalog step
- Stem splitting on macOS: `mlx-audio-separator` (installed via `uv sync --package stem-split --extra mac`)
- Stem splitting on Windows/Linux: `audio-separator[gpu]` (via `uv sync --package stem-split --extra gpu`)

## Setup

```bash
cd "/Volumes/Will Hunter Music/Scripts"   # or G:\Scripts on Windows
cp .env.example .env    # fill GETSONGBPM_API_KEY, Spotify creds, etc.
make sync
make help
```

Set `MUSIC_DRIVE_ROOT` in `.env` if the volume mounts elsewhere (e.g. `G:` on Windows).

## Packages

| Package | Command | Description |
|---------|---------|-------------|
| `mashup_pop_finder` | `make mashup-recon` / `mashup-match` | Mashup/pop key + BPM matcher |
| `stem_split` | `make stem-split` | Vocal ensemble + Demucs stems |
| `library_tools` | `make pn-cleanup`, `platinum-metadata`, `library-dedupe` | Library maintenance |
| `music-downloads` | `make sc-dl URL=…`, `make yt-dl URL=…` | SoundCloud (MP3 320) / YouTube |
| `music-catalogs` | `make sample-inventory`, `vst-index`, … | Sample/plugin CSV scanners |
| `soundcloud_repost` | `uv run --package soundcloud-repost sc-unrepost` | Selenium unrepost tool |
| `gpt_trainer` | (placeholder) | Recreate from [docs/prds/gpt-trainer.md](docs/prds/gpt-trainer.md) |

## Layout

```
Scripts/
├── config/paths.py      # MUSIC_DRIVE_ROOT paths
├── packages/            # uv workspace members
├── data/                # gitignored outputs (catalogs, key correction)
├── docs/prds/           # specs for lost scripts
└── Makefile
```

Stem **data** stays in `Stem Splitting/` on the music drive — pipeline code lives only in `packages/stem_split/`.

## Docs

- [INVENTORY.md](INVENTORY.md)
- [docs/prds/](docs/prds/)
