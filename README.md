# HuntingSzn Music Scripts

Private monorepo for DJ library tools, stem splitting, downloads, and harmonic matching.

**GitHub:** https://github.com/wlhunter00/huntingszn-music-scripts

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloaders
- [ffprobe](https://ffmpeg.org/) for key catalog step
- Stem splitting on macOS: `mlx-audio-separator` (installed via `uv sync --package stem-split --extra mac`)

## Setup

```bash
cd "/Volumes/Will Hunter Music/Scripts"
cp .env.example .env    # fill GETSONGBPM_API_KEY, Spotify creds, etc.
make sync
make help
```

Set `MUSIC_DRIVE_ROOT` in `.env` if the volume mounts elsewhere.

## Packages

| Package | Command | Description |
|---------|---------|-------------|
| `music_script` | `make music-recon` / `music-match` | Key + BPM harmonic matcher |
| `stem_split` | `make stem-split` | Vocal ensemble + Demucs stems |
| `library_tools` | `make pn-cleanup`, `platinum-metadata`, … | Library maintenance |
| `music-downloads` | `make sc-dl URL=…`, `make yt-dl URL=…` | SoundCloud (MP3 320) / YouTube (best source audio; add `ARGS='--mp3'` for MP3) |
| `music-catalogs` | `make sample-inventory` | Sample/project CSV scan |
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

Stem **data** stays in `/Volumes/Will Hunter Music/Stem Splitting/` — see that folder’s README.

## Docs

- [INVENTORY.md](INVENTORY.md)
- [docs/prds/](docs/prds/)
