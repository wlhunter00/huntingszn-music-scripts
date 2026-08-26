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
| Remove Mixed In Key cue points | `uv run --package library-tools mik-clear-cues --dry-run FOLDER` |

Common flags: `--root PATH` (pn-pipeline, pn-rename, library-metadata, serato-clear-cues), `--force` (pn-pipeline), `--flip-style` (optional; pn-pipeline / pn-filename only), `--library PATH` (library-dedupe, key-correct-catalog), `-o` / `--overwrite` (wav2mp3). `mik-clear-cues` requires a folder path.

**Serato cue clearing** — strips hot cues only (loops/beatgrid stay). Close Serato DJ first; MP3/AIFF only (`serato-tools` limitation):

```bash
uv run --package library-tools serato-clear-cues --root "H:\DJ Music\Soundcloud\1- need to nuke" --dry-run
uv run --package library-tools serato-clear-cues --root "H:\DJ Music\Soundcloud\1- need to nuke"
```

**Mixed In Key cue clearing** — removes Platinum Notes/MIK phrase markers (`Energy 7` Serato hot cues + `CuePoints` GEOB) and comments like `9A - Energy 8`. Key tags, energy level, beatgrid, and loops stay. You must pass the folder; there is no default:

```bash
uv run --package library-tools mik-clear-cues --dry-run "/Volumes/HuntingSzn/Platnium Notes/make it bump"
uv run --package library-tools mik-clear-cues "/Volumes/HuntingSzn/Platnium Notes/make it bump"
```

### `serato-bpm-cleanup` — round fractional Serato BPMs

Serato analysis often writes 128.31 / 128.5. Default is **dry-run**. `--write` rounds to the nearest integer, keeps the first-beat grid offset on constant beatgrids, and **never** rewrites a track that has any Serato hot cues or loops. Close Serato DJ Pro first (`--write` refuses if it looks running). Backs up mutated tags and `_Serato_/database V2`.

```bash
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music"
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music" --csv bpm-report.csv
uv run --package serato-bpm-cleanup serato-bpm-cleanup \
  --library "H:\DJ Music" \
  --db "C:\Users\Will\Music\_Serato_\database V2" \
  --write
```

See [packages/serato_bpm_cleanup/README.md](packages/serato_bpm_cleanup/README.md) for what storage is rewritten (BeatGrid / Autotags / TBPM / database `tbpm`) vs left alone.

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

# Publish FULL drive to B2 (copy; --allow-delete syncs but keeps projects/metadata/templates)
uv run --package library-sync library-sync publish --dry-run
uv run --package library-sync library-sync publish --allow-delete --dry-run

# Copy allowlisted B2 agent prefixes + Ableton remap (does not pull DJ Music)
uv run --package library-sync library-sync pull --dry-run

# Auto-run pull -> index -> publish when the portable HDD is plugged in
uv run --package library-sync library-sync install-watch
uv run --package library-sync library-sync watch --once   # optional: one-shot from Scripts

# Show status (counts for tracks, stems, Ableton projects)
uv run --package library-sync library-sync status
```

**Catalogs indexed:**
- **Tracks** (`DJ Music/` + `Platnium Notes/`) — searchable via `query` with Camelot/BPM
- **Stems** (`Stem Splitting/stem-output/{model}/{song}/`) — searchable via `query-stems`
- **Ableton projects** (`Ableton/**/*.als`, skips Backup) — searchable via `query-projects`

**Full-drive mirror vs catalog-only:**
- **Index** catalogs tracks, stems, and Ableton projects into SQLite
- **Publish** copies the ENTIRE drive to B2 bucket root (DJ Music, Ableton, Stem Splitting, etc.). Does not delete remote files unless you pass `--allow-delete` (rclone sync). Sync still keeps B2-only prefixes: `projects/`, `metadata/`, `templates/`.
- **Pull** is allowlisted `rclone copy --update` only (never a whole-bucket copy, never deletes). Drive-primary trees (`DJ Music/`, `Platnium Notes/`, `Stem Splitting/`, `Set Recording/`, `Scripts/`, `Ableton/`) are **not** pull sources, so a local delete there is **not** resurrected from B2.
  1. Agent prefixes in `PULL_AGENT_PREFIXES` (currently `Thumbnails/`) → `{DRIVE}/Thumbnails/` 1:1 (`Releases/**/03-finals/`, root prompt txts).
  2. B2 `projects/<slug>/` → `{DRIVE}/Ableton/Music Production Agent/<slug>/` (sole writer of that job home).
- **watch** is the hands-off path: allowlisted pull → incremental index → publish (`rclone copy --update`). It never passes `--allow-delete` and never auto-deletes remotes.
- **Publish** excludes (not pull): system files, Ableton `Backup/`, secrets (`.env`, `cookies.txt`, `*.pem`), and `Scripts/data/library.sqlite` (catalog is uploaded separately to `metadata/library.sqlite`)

**Harmonic mixing rules (tracks only):**
- Camelot: matches ±1 on wheel plus relative major/minor (e.g., 8A matches 7A, 8A, 9A, 8B)
- BPM: matches ±6 of target, plus ±6 of half-time (0.5×) and double-time (2×)

**B2 layout:**
- Bucket root mirrors drive folders (DJ Music, Ableton, Stem Splitting, Set Recording, etc.)
- `metadata/library.sqlite` — track catalog for queries
- `templates/mashup/` — from `Ableton/HuntingSzn Mashup Template Project`
- `Thumbnails/` — agent drop zone, pulled 1:1 onto the drive
- `projects/<slug>/` — pulled to `Ableton/Music Production Agent/<slug>/` (not `{DRIVE}/projects/`)

### Drive-mount watcher (install once per PC)

`install-watch` writes a **local** login stub (Task Scheduler on Windows, launchd on macOS, systemd user on Linux). The stub cannot live only on the HDD: the computer has to see the volume appear. It discovers the drive by volume name (`HuntingSzn` or `Will Hunter Music`) — it does **not** hardcode `H:`.

When the drive is already plugged in at login (or right after install), the pipeline still runs once after a short debounce. A burst of mount events does not overlap runs. If the drive is unplugged, the stub idles (no crash, no B2 calls). Log: `{DRIVE}/Scripts/data/watch.log`.

**Windows (Wills-Gaming-Desktop)** — from the repo on the music drive (whatever letter it mounted as, currently often `H:\Scripts`):

```bat
uv sync --package library-sync
uv run --package library-sync library-sync install-watch
```

This creates a logon scheduled task named `HuntingSzn library-sync watch` plus `%LOCALAPPDATA%\library-sync\watch-stub.py`. Unplug/replug the drive; pull -> index -> publish happens automatically. `PYTHONUTF8=1` is set so the Windows console cannot crash on Unicode. Remove with:

```bat
uv run --package library-sync library-sync uninstall-watch
```

**macOS** — from `/Volumes/HuntingSzn/Scripts` or `/Volumes/Will Hunter Music/Scripts`:

```bash
uv sync --package library-sync
uv run --package library-sync library-sync install-watch
```

This writes `~/Library/LaunchAgents/com.huntingszn.library-sync.watch.plist` (RunAtLoad + KeepAlive) and `~/Library/Application Support/library-sync/watch-stub.py`. Same uninstall command as Windows.

Uses existing host rclone/B2 config (`B2_REMOTE=b2`, `B2_BUCKET=huntingszn-music`, `rclone.conf`). Does not write secrets or overwrite `rclone.conf`.

To run the job once by hand (drive must be mounted):

```bash
uv run --package library-sync library-sync watch --once
```

## Tests & lint

```bash
uv sync --package mashup-pop-finder --extra dev
uv run --package mashup-pop-finder pytest packages/mashup_pop_finder/tests

uv sync --package library-tools --extra dev
uv run --package library-tools pytest packages/library_tools/tests

uv sync --package library-sync --extra dev
uv run --package library-sync pytest packages/library_sync/tests

uv sync --package serato-bpm-cleanup --extra dev
uv run --package serato-bpm-cleanup pytest packages/serato_bpm_cleanup/tests

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
| `serato_bpm_cleanup` | Round fractional Serato BPMs (dry-run default; skip tracks with cues) |
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
