# PRD: vst_indexer

**Status:** Lost — recreate.

## Purpose

Scan VST/VST3 plugin directories and write a CSV catalog (`vst_plugins.csv`).

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Output | `vst_plugins.csv` next to script | `data/catalogs/vst_plugins.csv` |

## Dependencies

- stdlib (likely `os`, `csv`, `pathlib`)

## Behavior

- Walk standard plugin paths on Mac/Windows (recreate path list for macOS: `~/Library/Audio/Plug-Ins/VST`, VST3, etc.).
- **~3 KB** script, **~15 KB** CSV output.

## Recreation notes

- Pair with `minimal_plugin_catalog` under `packages/catalogs/`.
