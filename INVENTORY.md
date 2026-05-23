# Scripts inventory

Last updated: 2026-05-23

Repo root: `/Volumes/Will Hunter Music/Scripts`

## Status legend

| Status | Meaning |
|--------|---------|
| **present** | On disk in this repo or linked path |
| **lost** | Removed during sidebar move; recreate from `docs/prds/` |
| **external** | Code/data on drive outside `Scripts/` until migrated |

---

## Present

| Path | Purpose | Dependencies | Default data paths |
|------|---------|--------------|-------------------|
| `music-script/` | Harmonic key + BPM matcher (`music-script` / `python -m music_script`) | httpx, click, rich, selectolax, python-dotenv | CWD; `recon-output/`, `matches.csv` |
| `../Stem Splitting/demucs-master.py` | Stem-split pipeline (vocals ensemble + Demucs) | audio-separator / mlx-audio-separator, soundfile | `songs-to-split/`, `stem-output/` (relative to Stem Splitting) |
| `../Stem Splitting/verify_stems.py` | Validate stem outputs | imports `demucs-master` | `stem-output/htdemucs_ft/` |

### music-script commands

```bash
cd music-script
pip install -e ".[dev]"
cp .env.example .env   # add GETSONGBPM_API_KEY
python -m music_script recon search --title "..." --artist "..."
python -m music_script match --title "..." --artist "..."
```

---

## Lost (recreate from PRD)

| Former path | PRD | Notes |
|-------------|-----|-------|
| `duplicate-script.py` | [docs/prds/duplicate-script.md](docs/prds/duplicate-script.md) | mutagen |
| `file-namer.py` | [docs/prds/file-namer.md](docs/prds/file-namer.md) | mutagen |
| `song-metadata-extractor.py` | [docs/prds/song-metadata-extractor.md](docs/prds/song-metadata-extractor.md) | mutagen; ~19k lines |
| `pn-script.py` | [docs/prds/pn-script.md](docs/prds/pn-script.md) | stdlib only |
| `soundcloud_dl.py` | [docs/prds/soundcloud-dl.md](docs/prds/soundcloud-dl.md) | yt-dlp, ffmpeg |
| `yt_audio_dl.py` | [docs/prds/yt-audio-dl.md](docs/prds/yt-audio-dl.md) | yt-dlp, ffmpeg |
| `sample_inventory.py` | [docs/prds/sample-inventory.md](docs/prds/sample-inventory.md) | stdlib |
| `minimal_plugin_catalog.py` | [docs/prds/minimal-plugin-catalog.md](docs/prds/minimal-plugin-catalog.md) | stdlib |
| `rift_preset_catalog.py` | [docs/prds/rift-preset-catalog.md](docs/prds/rift-preset-catalog.md) | stdlib |
| `vst_indexer.py` | [docs/prds/vst-indexer.md](docs/prds/vst-indexer.md) | stdlib |
| `key_correction/` | [docs/prds/key-correction.md](docs/prds/key-correction.md) | mutagen, spotipy, essentia, pandas |
| `GPT trainer/` | [docs/prds/gpt-trainer.md](docs/prds/gpt-trainer.md) | whisper, yt-dlp, tweepy, sklearn, … |
| `soundcloud_repost/` | [docs/prds/soundcloud-repost.md](docs/prds/soundcloud-repost.md) | selenium, webdriver-manager |

---

## Not in git (artifacts that existed before loss)

- `sample_inventory_2025-04-20.csv`, `sample_inventory_2025-04-21.csv`
- `minimal_plugins.csv`, `vst_plugins.csv`
- GPT trainer: `cookies.txt`, transcript trees, `creator_weights.json`, `repeated_content_flags.json`
- `key_correction/.venv/`, `output/`, `.cache/`
- `Sevek - Bad Girl.m4a` (stray test file in Scripts root)

---

## Planned layout (phases 3+)

See [plan](file:///Users/williamhunter/.cursor/plans/music_scripts_monorepo_61734315.plan.md): `packages/`, `config/paths.py`, root `Makefile`, uv workspace.
