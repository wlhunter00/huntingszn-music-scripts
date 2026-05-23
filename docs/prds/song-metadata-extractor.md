# PRD: song-metadata-extractor

**Status:** Lost — recreate (largest library tool).

## Purpose

Robust filename → ID3 metadata for Platinum Notes (and similar libraries): features, remixes, mashups, known multi-word artists, optional force-update.

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Folder | `G:\Platnium Notes` | `--root` → `paths.PLATINUM_NOTES` |
| Flag | `FORCE_UPDATE = True` | `--force` CLI flag |

## Dependencies

- `mutagen` (EasyID3, ID3NoHeaderError)
- `re`

## Behavior (from scan)

- `KNOWN_ARTISTS` list (baby keem, daft punk, jay z, etc.) — do not split these names.
- Patterns: `ft.`, `feat.`, `remix`, `edit`, `flip`, `mashup`, collab indicators (` x `, ` vs `, ` & `).
- Strip `_PN` suffix from stem before parse.
- Replace `-` with spaces for parsing.
- Write `artist` (contributing artists) and `title` to EasyID3.
- Summary stats at end.

## Recreation notes

- **~19 KB** — recover from backup/Time Machine if possible before rewriting.
- Split into: `parse_song_info()`, `process_music_folder()`, `KNOWN_ARTISTS` config file.
- Makefile: `make platinum-metadata [--dry-run] [--force]`.
