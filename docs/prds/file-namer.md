# PRD: file-namer

**Status:** Lost — recreate.

## Purpose

Walk a music folder; for files missing ID3 title/artist, parse `Artist - Title` from filename and write EasyID3 tags.

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Folder | `G:\Platnium Notes` | CLI `--root` defaulting to `paths.PLATINUM_NOTES` |
| Output | Updated MP3 tags | Print summary counts |

## Dependencies

- `mutagen` (EasyID3, ID3NoHeaderError)

## Behavior

- Skip files that already have both `title` and `artist`.
- Parse `part1 - part2` → artists = part1, title = part2 (special case for "(Evalution" evaluation edits).
- Print summary: total, already tagged, updated, unparseable.

## Recreation notes

- **~5.5 KB** — smaller than song-metadata-extractor.
- Prefer merging into one `library_tools.metadata` module with a `--simple` mode vs full extractor.
