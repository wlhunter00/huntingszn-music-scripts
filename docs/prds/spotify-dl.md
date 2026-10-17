# PRD: spotify-dl (`sp-dl`)

**Status:** Implemented in `packages/downloads` (2026-08-23).

## Purpose

Accept Spotify track / album / playlist URLs, resolve official catalog metadata, find a confident match on YouTube (then SoundCloud), download via existing `yt-dlp` helpers, and tag the file with Spotify title/artist/album/artwork.

**Non-goal:** Decrypting or ripping Spotify protected streams (see research doc).

## Inputs / outputs

| | Default |
|--|---------|
| Output | `paths.DOWNLOADS / YYYY-MM-DD` |
| Library | `--to-library` → `paths.DJ_SPOTIFY` |
| History | `sp-dl-history.json` in the output dir |
| Args | URL(s), `--output-dir`, `--to-library`, `--best`, `--source`, `--min-score`, `--limit`, `--skip-existing`, `--dry-run`, `--no-tag`, `--market`, `--auth-token` |

## Dependencies

- `yt-dlp[default]`
- `spotipy`
- `mutagen`
- `ffmpeg` (system)
- Deno or Node (YouTube JS challenges)
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`

## Behavior

1. Parse Spotify URL/URI/id.
2. Client-credentials Spotify Web API → normalized tracks (paginated albums/playlists).
3. Search `ytsearchN:` then optional `scsearchN:`; score by title/artist/duration/version markers.
4. Reject below `--min-score` (default 55).
5. `run_yt_dlp` with `Artist - Title.%(ext)s` template.
6. Overwrite tags + embed Spotify artwork (unless `--no-tag`).
7. Record status in JSON manifest for resume / `--skip-existing`.

## Related docs

- Research: [`../research/viwizard-spotify-converter-analysis.md`](../research/viwizard-spotify-converter-analysis.md)
- Makefile: `make sp-dl URL=... ARGS='--dry-run'`

## Recreation notes

- Modules: `spotify.py`, `spotify_api.py`, `source_resolver.py`, `metadata.py`
- Shares `_common.run_yt_dlp` with `sc-dl` / `yt-dl`
