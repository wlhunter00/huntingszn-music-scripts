# Scripts inventory

Last updated: 2026-05-23 (monorepo phases 3–8)

Repo: https://github.com/wlhunter00/huntingszn-music-scripts

## Present in `packages/`

| Package | Status | Makefile / CLI |
|---------|--------|----------------|
| `music_script` | Complete (from paid-social-content-agent) | `make music-recon`, `music-match` |
| `stem_split` | Migrated from Stem Splitting | `make stem-split`, `stem-verify` |
| `library_tools` | Recreated (metadata, pn, dedupe, key step1) | `make pn-cleanup`, `platinum-metadata`, … |
| `downloads` | Recreated | `make sc-dl`, `yt-dl` |
| `catalogs` | Recreated (`sample_inventory`) | `make sample-inventory` |
| `soundcloud_repost` | Recreated | `sc-unrepost` |
| `gpt_trainer` | Placeholder only | See PRD |

## Key correction steps 2–5

Not yet recreated. Step 1: `make key-correct-catalog`. Spec: [docs/prds/key-correction.md](docs/prds/key-correction.md).

## External data (not in git)

| Path | Purpose |
|------|---------|
| `../Stem Splitting/songs-to-split/` | Stem input |
| `../Stem Splitting/stem-output/` | Stem output |
| `../Platnium Notes/` | Platinum Notes library |
| `../DJ Music/Spotify/` | DJ library |
| `../Downloads/` | Downloader output |

## Planned

- Merge `Stem Splitting/demucs-master.py` shim or remove after confirming `make stem-split`
- Recreate GPT trainer and key correction steps 2–5 from PRDs
