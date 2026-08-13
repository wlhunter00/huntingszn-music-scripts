# Scripts inventory

Last updated: 2026-05-25 (restored from E:\Music Backup\Scripts + Stem Splitting sync)

Repo: https://github.com/wlhunter00/huntingszn-music-scripts

## Present in `packages/`

| Package | Status | Makefile / CLI |
|---------|--------|----------------|
| `mashup_pop_finder` | Complete (from paid-social-content-agent) | `make mashup-recon`, `mashup-match` |
| `stem_split` | Restored (macOS scratch-dir fix; drive scripts retired) | `make stem-split`, `stem-verify` |
| `library_tools` | Restored from backup (metadata, pn, dedupe, key step1) | `make pn-cleanup`, `platinum-metadata`, `library-dedupe`, … |
| `library_sync` | v1 — index HDD, SQLite catalog, B2 stubs, key/BPM query | `make library-index`, `library-publish`, `library-pull`, `library-query` |
| `downloads` | Recreated | `make sc-dl`, `yt-dl` |
| `catalogs` | Restored (sample inventory + VST/Minimal/Rift) | `make sample-inventory`, `vst-index`, `minimal-catalog`, `rift-catalog` |
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

- Recreate GPT trainer and key correction steps 2–5 from PRDs
