# auto-cue

Automatic Serato hot-cue tagger for HuntingSzn. Predicts 8 cues from audio features using Will's cue system.

## Features

- Dry-run by default, `--write` to mutate
- Backs up files before writing
- Refuses while Serato is running
- Supports MP3 and FLAC
- Never modifies protected tracks (human cues, BPM lock, Sets/Perma crates)

## Installation

```bash
uv sync --package auto-cue
```

## Usage

```bash
# Dry-run on library
uv run --package auto-cue auto-cue --library "H:\DJ Music"

# Process single file with explanation
uv run --package auto-cue auto-cue --file track.mp3 --explain

# Write cues (with backup)
uv run --package auto-cue auto-cue --library "H:\DJ Music" --write

# Replace MIK Energy cues
uv run --package auto-cue auto-cue --library "H:\DJ Music" --write --replace-mik

# With LLM (requires OPENAI_API_KEY)
OPENAI_API_KEY=sk-... uv run --package auto-cue auto-cue --library "H:\DJ Music" --explain
```

## Evaluation

```bash
# Rule-based blind eval (no API key needed)
uv run --package auto-cue auto-cue-eval /path/to/gold-songs

# LLM eval (requires OPENAI_API_KEY)
OPENAI_API_KEY=sk-... uv run --package auto-cue auto-cue-eval /path/to/gold-songs --use-llm

# Custom model
OPENAI_API_KEY=sk-... uv run --package auto-cue auto-cue-eval /path/to/gold-songs --use-llm --model gpt-4o
```

## Will's Cue System

| Slot | Meaning | Rule |
|------|---------|------|
| 4 | First drop | Judgment call |
| 3 | Buildup | cue4 - 32 |
| 2 | Transition end | cue3 - 32/64/96 |
| 1 | Intro | First beat or cue4 - k·32 |
| 6 | Last drop | Judgment call |
| 5 | Build to last | cue6 - 32 |
| 7 | Mix-out point | cue6 + 32 |
| 8 | Last call | ~32-48 beats before end |

Cues 1-4 and 5-8 are on separate 32-beat lattices anchored at cue4 and cue6.

## Safety

- Never modifies tracks with human (non-MIK) cues
- Never touches BPM-locked tracks
- Skips tracks in Sets/, Perma Playlists/, Produced by me crates
- Never rewrites dynamic (multi-marker) grids
- Abstains when confidence is low
