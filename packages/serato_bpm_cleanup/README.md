# serato-bpm-cleanup

Round fractional Serato BPMs (128.31, 128.5, …) to integers so the beatgrid
does not slowly drift. **Default is dry-run.** Nothing is written unless you
pass `--write`.

```bash
uv sync --package serato-bpm-cleanup
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music" --help
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music"
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music" --write
```

## Close Serato first

Serato DJ Pro can write in-memory analysis back to files on exit. `--write`
**refuses** if a Serato DJ / `Serato.exe` process looks running (Windows
`tasklist`, elsewhere `ps`). A close-Serato warning is printed even on dry-run.

## What this rewrites

Investigated on-disk layout (Holzhaus `serato-tags`, `serato-tools`, pyserato):

| Store | Role | `--write` |
| --- | --- | --- |
| `GEOB:Serato BeatGrid` | Grid: first-beat offset + BPM (terminal marker) | **Yes**, constant (single-marker) grids only. BPM float is rounded; **first-beat `position_s` is kept**. |
| `GEOB:Serato Autotags` | ASCII BPM + gain | **Yes**, BPM string only (`115.00` → `128.00`). Gain untouched. |
| ID3 `TBPM` | Display BPM | **Yes** |
| `_Serato_/database V2` `tbpm` | Library list BPM | **Yes** when `--db` is set or auto-detected |
| `GEOB:Serato Markers2` / `Markers_` | Hot cues, loops, names, colors | **Never** (read-only, for the cue safety rule) |
| ID3 `COMM` | Comments | **Never** used for cue count or BPM |
| Rekordbox / B2 | — | **Never** touched. No deletes. |

**Dynamic (multi-marker) beatgrids** are not rewritten. Changing only the
terminal BPM would desync earlier segments. Those tracks can still get Autotags
+ TBPM rounded; the report notes `dynamic-grid-not-rewritten`.

pyserato is a crate / hot-cue helper. It does **not** parse BeatGrid or Autotags,
so this tool implements those payloads from the documented GEOB layout instead.

## Hard rule: cues

If the track has **any** Serato hot cues, saved loops, or named/colored markers,
it is **skipped** (`skip-has-cues`) and listed separately. Cue count comes from
Serato marker GEOBs only. Loops count as cues. `--write` is a no-op on those
files. Exit status is non-zero only on real failures, not on skips.

## Pointing at the library

```bash
# Audio folder (required if auto-detect cannot find DJ Music / Music)
uv run --package serato-bpm-cleanup serato-bpm-cleanup --library "H:\DJ Music"

# Serato database (Windows library is often next to MIXO, not on the HDD)
uv run --package serato-bpm-cleanup serato-bpm-cleanup \
  --library "H:\DJ Music" \
  --db "C:\Users\Will\Music\_Serato_\database V2"
```

Auto-detect tries, in order:

- `--library` / `--db`
- `DJ Music` and `Platnium Notes` on `MUSIC_DRIVE_ROOT`
- Windows: `C:\Users\Will\Music` and `C:\Users\Will\Music\_Serato_\database V2`
- `~/Music/_Serato_/database V2`
- `_Serato_/database V2` next to the music root (portable drive)

## Backups

`--write` copies each mutated audio file and the database (if updated) into
`serato-bpm-cleanup-backups/<UTC timestamp>/` (override with `--backup-dir`).
Originals are never deleted.

## Report

Dry-run prints a table: path, current BPM, proposed integer, cue-count, action
(`fix` / `skip-has-cues` / `skip-already-integer`). Optional `--csv FILE`.

Locked defaults: fractional if `abs(bpm - round(bpm)) >= 0.02`. Proposed BPM is
nearest integer. Tempo is never doubled or halved.
