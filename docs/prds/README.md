# Mini PRDs — script inventory

Most library and catalog scripts were **restored from backup** on 2026-05-25 (`E:\Music Backup\Scripts` → `packages/`). Stem splitting code is canonical in `packages/stem_split/` only.

| PRD | Status |
|-----|--------|
| [stem-split](stem-split.md) | **Restored** — synced from drive; legacy scripts removed |
| [soundcloud-dl](soundcloud-dl.md) | Restored in `packages/downloads` |
| [yt-audio-dl](yt-audio-dl.md) | Restored in `packages/downloads` |
| [pn-script](pn-script.md) | **Restored** — `library_tools.pn_rename` |
| [file-namer](file-namer.md) | **Restored** — merged into `library_tools.metadata` |
| [song-metadata-extractor](song-metadata-extractor.md) | **Restored** — `library_tools.metadata` |
| [duplicate-script](duplicate-script.md) | **Restored** — `library_tools.duplicate` |
| [key-correction](key-correction.md) | Step 1 only; steps 2–5 pending |
| [soundcloud-repost](soundcloud-repost.md) | Restored in `packages/soundcloud_repost` |
| [sample-inventory](sample-inventory.md) | **Restored** — `catalogs.sample_inventory` |
| [vst-indexer](vst-indexer.md) | **Restored** — `catalogs.vst_indexer` |
| [minimal-plugin-catalog](minimal-plugin-catalog.md) | **Restored** — `catalogs.minimal_catalog` |
| [rift-preset-catalog](rift-preset-catalog.md) | **Restored** — `catalogs.rift_catalog` |
| [gpt-trainer](gpt-trainer.md) | Placeholder — no backup available |

Each PRD includes: purpose, I/O, dependencies, paths, behavior notes, and recreation priority.
