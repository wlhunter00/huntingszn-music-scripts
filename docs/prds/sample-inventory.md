# PRD: sample_inventory

**Status:** Lost — recreate.

## Purpose

Crawl configured drive roots and produce a CSV inventory of samples, Ableton projects, racks, presets, etc., classified by extension and folder name heuristics.

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Roots | `G:\Producing Sounds`, `G:\Ableton`, `G:\Stem Splitting`, `G:\Instruments`, `G:\serum presets` | CLI `--roots` or `paths.SAMPLE_ROOTS` |
| Output | `sample_inventory_YYYY-MM-DD.csv` | `data/catalogs/` gitignored |

## Dependencies

- stdlib: `os`, `csv`, `argparse`, `re`, `datetime`

## Behavior

- `FILE_TYPES` dict: Ableton Rack (`.adg`), Project (`.als`), Plugin Preset (`.fxp`, `.vstpreset`, …), Drum Sample (`.wav` in drum folders), etc.
- Match by extension + folder name keywords.
- Emit rows: path, type, size, modified date (verify columns when recreating).

## Recreation notes

- **~9 KB** + generated CSVs were **multi-MB** — never commit CSV output.
- Useful for finding duplicate samples across Producing Sounds / Ableton.
