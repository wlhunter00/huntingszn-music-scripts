# HuntingSzn Studio

Electron control panel for the music scripts on the HuntingSzn drive. Buttons call the existing `uv run` CLIs and stream the log. Beat Visualizer stays in its own repo and is launched from here.

## Requirements

- Node 18+
- `uv` on PATH (or `%USERPROFILE%\.local\bin\uv.exe`)
- Music drive mounted as **HuntingSzn** with `Scripts/pyproject.toml`
- Optional: Beat Visualizer at `%USERPROFILE%\Documents\GitHub\visualizer-thumbnail-generator`

## Run

```bash
cd apps/studio
npm install
npm start
```

## Tabs

- **Release** — mashup covers, clean/crystal transform, embed-cover, open Beat Visualizer
- **DJ ingest** — open ViWizard / Platinum Notes / Mixed In Key / Serato, `pn-pipeline`, dry-run then copy into `DJ Music`, dedupe, mik-clear-cues, serato-bpm-cleanup (explicit `H:\_Serato_\database V2`)
- **Tools** — stem-split, open folders

The B2 watcher is left alone. Do not run manual `library-sync publish` from this app while the scheduled watcher is running.
