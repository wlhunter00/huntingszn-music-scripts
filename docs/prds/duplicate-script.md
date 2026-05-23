# PRD: duplicate-script

**Status:** Lost — recreate.

## Purpose

Find and remove duplicate audio files in the DJ Spotify library folder by comparing artist metadata (mutagen).

## Inputs / outputs

| | Default (old) | Target |
|--|---------------|--------|
| Library | `G:\DJ Music\Spotify` | `$MUSIC_DRIVE_ROOT/DJ Music/Spotify` |
| Action | Delete duplicate files | Same; add `--dry-run` |

## Dependencies

- `mutagen` (EasyID3 / File)

## Behavior (from scan)

1. Walk library path.
2. Read artist tag per file.
3. Track seen artists; on duplicate artist, delete the newer/duplicate file (confirm exact rule when recreating — original used a `music` set and delete on collision).

## Recreation notes

- **~2.4 KB**, single file.
- Use `argparse` + `paths.DJ_SPOTIFY`.
- Add dry-run and logging before any delete.
