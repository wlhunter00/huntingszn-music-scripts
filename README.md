# HuntingSzn Music Scripts

Private monorepo for DJ library tools, stem splitting, downloads, and harmonic matching.

**GitHub:** https://github.com/wlhunter00/huntingszn-music-scripts

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp) for downloaders
- [ffprobe](https://ffmpeg.org/) for key catalog step
- Stem splitting on macOS: `mlx-audio-separator` (installed via `uv sync --package stem-split --extra mac`)
- Stem splitting on Windows/Linux with NVIDIA GPU: `audio-separator[gpu]` + CUDA PyTorch (via `uv sync --package stem-split --extra gpu`)
- Stem splitting on CPU (no GPU): `audio-separator` (via `uv sync --package stem-split --extra cpu`)

## Setup

```bash
cd "/Volumes/Will Hunter Music/Scripts"   # or G:\Scripts on Windows
cp .env.example .env    # fill GETSONGBPM_API_KEY, Spotify creds, etc.
make sync
make help
```

Drive paths are inferred from the repo location (`H:\Scripts` → `H:\`). Set `MUSIC_DRIVE_ROOT` in `.env` only if Scripts is not on the music drive root.

## Commands

Run everything from the repo root. Install once:

```bash
uv sync --all-packages
```

Most scripts default to paths in `config/paths.py` (Platinum Notes, Stem Splitting, DJ Spotify, etc.). Override with CLI flags where noted.

### `library-tools` — library maintenance

**All-in-one Platinum Notes prep** (recommended — runs rename → filename fix → metadata in order):

```bash
uv run --package library-tools pn-pipeline --dry-run
uv run --package library-tools pn-pipeline
```

Optional: add `--flip-style` only if you want retail artists stripped from flip filenames (off by default).

| Script | `uv` command |
|--------|----------------|
| Full prep pipeline | `uv run --package library-tools pn-pipeline --dry-run` |
| Strip `_pn` from filenames | `uv run --package library-tools pn-rename --dry-run` |
| Write ID3 tags from filenames | `uv run --package library-tools library-metadata --dry-run` |
| Remove duplicate files | `uv run --package library-tools library-dedupe --dry-run` |
| Normalize flip filenames | `uv run --package library-tools pn-filename --dry-run` |
| Catalog current key tags (step 1) | `uv run --package library-tools key-correct-catalog` |
| Convert `.wav` → `.mp3` | `uv run --package library-tools wav2mp3 -b 320k song.wav` |
| Remove Serato hot cues | `uv run --package library-tools serato-clear-cues --dry-run` |

Common flags: `--root PATH` (pn-pipeline, pn-rename, library-metadata, serato-clear-cues), `--force` (pn-pipeline), `--flip-style` (optional; pn-pipeline / pn-filename only), `--library PATH` (library-dedupe, key-correct-catalog), `-o` / `--overwrite` (wav2mp3).

**Serato cue clearing** — strips hot cues only (loops/beatgrid stay). Close Serato DJ first; MP3/AIFF only (`serato-tools` limitation):

```bash
uv run --package library-tools serato-clear-cues --root "H:\DJ Music\Soundcloud\1- need to nuke" --dry-run
uv run --package library-tools serato-clear-cues --root "H:\DJ Music\Soundcloud\1- need to nuke"
```

### `stem-split` — vocal + Demucs stems

```bash
uv run --package stem-split stem-split
uv run --package stem-split stem-verify
```

Defaults: input `Stem Splitting/songs-to-split`, output `Stem Splitting/stem-output`. Override with `--input` / `--output`. On macOS sync with `--extra mac`; on Windows/Linux with NVIDIA GPU use `--extra gpu`; for CPU-only use `--extra cpu`.

### `mashup-pop-finder` — mashup/pop matcher

```bash
uv run --package mashup-pop-finder mashup-pop-finder recon search --title "Song" --artist "Artist"
uv run --package mashup-pop-finder mashup-pop-finder match --title "Song" --artist "Artist"
```

Optional: `--base-key`, `--base-bpm`, `--pages`, `--limit`, `--debug`. Requires `GETSONGBPM_API_KEY` in `.env` for match.

### `music-downloads` — SoundCloud / YouTube

```bash
uv run --package music-downloads sc-dl "https://soundcloud.com/..."
uv run --package music-downloads yt-dl "https://youtube.com/watch?v=..."
```

Optional: `--output-dir`. SoundCloud auth via `SOUNDCLOUD_AUTH_TOKEN` in `.env`.

### `music-catalogs` — sample & plugin scanners

```bash
uv run --package music-catalogs sample-inventory
uv run --package music-catalogs vst-index
uv run --package music-catalogs minimal-catalog
uv run --package music-catalogs rift-catalog
```

Each accepts output/path overrides — run with `--help` for defaults.

### `soundcloud-repost` — remove reposts

```bash
uv run --package soundcloud-repost sc-unrepost
```

Optional: `--profile-url`. Opens Chrome via Selenium.

### `library-sync` — music inventory layer

Index portable HDD library, sync to B2, query by Camelot key and BPM:

```bash
# Check if drive is mounted (supports "Will Hunter Music" or "HuntingSzn" volumes)
uv run --package library-sync library-sync detect

# Index all catalogs: tracks, stems, Ableton projects
uv run --package library-sync library-sync index --dry-run
uv run --package library-sync library-sync index

# Query tracks (for Music Production Agent)
uv run --package library-sync library-sync query --camelot 8A --bpm 140
uv run --package library-sync library-sync query --q "halo" --json

# Query stem folders
uv run --package library-sync library-sync query-stems --q "as it was" --model htdemucs_ft

# Query Ableton projects
uv run --package library-sync library-sync query-projects --q "mashup" --kind template

# Publish FULL drive to B2 (copy --update; never deletes remote unless --allow-delete)
uv run --package library-sync library-sync publish --dry-run
uv run --package library-sync library-sync publish --allow-delete --dry-run

# Copy projects from B2 to Ableton/Music Production Agent (does not delete local work)
uv run --package library-sync library-sync pull --dry-run

# Show status (counts for tracks, stems, Ableton projects)
uv run --package library-sync library-sync status
```

**Catalogs indexed:**
- **Tracks** (`DJ Music/` + `Platnium Notes/`) — searchable via `query` with Camelot/BPM
- **Stems** (`Stem Splitting/stem-output/{model}/{song}/`) — searchable via `query-stems`
- **Ableton projects** (`Ableton/**/*.als`, skips Backup) — searchable via `query-projects`

**Full-drive mirror vs catalog-only:**
- **Index** catalogs tracks, stems, and Ableton projects into SQLite
- **Publish** copies the ENTIRE drive to B2 bucket root (DJ Music, Ableton, Stem Splitting, etc.). Does not delete remote files unless you pass `--allow-delete` (rclone sync).
- Excludes system files: `$RECYCLE.BIN`, `.Spotlight-V100`, `.Trashes`, `.DS_Store`, `._*`, `.git`, `.venv`, `__pycache__`

**Harmonic mixing rules (tracks only):**
- Camelot: matches ±1 on wheel plus relative major/minor (e.g., 8A matches 7A, 8A, 9A, 8B)
- BPM: matches ±6 of target, plus ±6 of half-time (0.5×) and double-time (2×)

**B2 layout:**
- Bucket root mirrors drive folders (DJ Music, Ableton, Stem Splitting, Set Recording, etc.)
- `metadata/library.sqlite` — track catalog for queries
- `templates/mashup/` — from `Ableton/HuntingSzn Mashup Template Project`
- `projects/<slug>/` — pulled to `Ableton/Music Production Agent/<slug>/`

### Tests & lint

```bash
uv sync --package mashup-pop-finder --extra dev
uv run --package mashup-pop-finder pytest packages/mashup_pop_finder/tests

uv sync --package library-tools --extra dev
uv run --package library-tools pytest packages/library_tools/tests

uv run ruff check packages config
```

### Makefile shortcuts

`make help` lists equivalent targets (`make pn-pipeline`, `make pn-cleanup`, `make stem-split`, `make mashup-match TITLE=… ARTIST=…`, etc.) if you prefer `make` over typing `uv run`.

## Packages

| Package | Description |
|---------|-------------|
| `mashup_pop_finder` | Mashup/pop key + BPM matcher |
| `stem_split` | Vocal ensemble + Demucs stems |
| `library_tools` | Metadata, duplicates, Platinum Notes cleanup, key correction |
| `library_sync` | Music inventory: index HDD, sync B2, query by key/BPM |
| `music-downloads` | SoundCloud (MP3 320) / YouTube |
| `music-catalogs` | Sample/plugin CSV scanners |
| `soundcloud_repost` | Selenium unrepost tool |
| `gpt_trainer` | (placeholder) — [docs/prds/gpt-trainer.md](docs/prds/gpt-trainer.md) |

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
