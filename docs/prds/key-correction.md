# PRD: key_correction (DJ library key pipeline)

**Status:** Lost — recreate.

## Purpose

Correct musical key tags in the DJ Spotify library: catalog current keys, resolve via Spotify API, fallback to Essentia analysis, compare, write back to FLAC/MP3.

## Pipeline (5 steps)

| Step | File | Role |
|------|------|------|
| 1 | `step1_catalog.py` | Walk library; read INITIALKEY (FLAC) / TKEY (MP3) via ffprobe; write catalog CSV |
| 2 | `step2_spotify_lookup.py` | Spotify search + audio features for key |
| 3 | `step3_essentia_fallback.py` | Essentia key detection when Spotify missing |
| 4 | `step4_compare.py` | Diff catalog vs Spotify vs Essentia |
| 5 | `step5_overwrite.py` | Write winning key back to files |

## Supporting modules

- `config.py` — **had hardcoded Spotify credentials** (rotate before reuse)
- `key_utils.py` — camelot / musical key helpers

## Paths (old config)

```python
LIBRARY_PATH = "/Volumes/Will Hunter Music/DJ Music/Spotify"
OUTPUT_DIR = "/Volumes/Will Hunter Music/Scripts/key_correction/output"
```

## Dependencies

```
mutagen
spotipy
essentia
pandas
```

## Recreation notes

- Use `.env` for `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.
- Essentia install is heavy on macOS — document in README.
- Makefile: `make key-correct-1` … `make key-correct-5`.
- **Different from `music-script`** (harmonic match finder for DJ sets).
