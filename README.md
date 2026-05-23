# Will Hunter Music — Scripts

Private tooling for DJ library management, stem splitting, downloads, and harmonic matching.

## Quick start

```bash
cd "/Volumes/Will Hunter Music/Scripts"
cp .env.example .env   # fill in API keys as needed

cd music-script
pip install -e ".[dev]"
python -m music_script --help
```

## Docs

- [INVENTORY.md](INVENTORY.md) — what exists vs what was lost
- [docs/prds/](docs/prds/) — mini PRDs to recreate lost scripts

## On the drive (not in this folder yet)

- **Stem splitting:** `/Volumes/Will Hunter Music/Stem Splitting/` (`demucs-master.py`, `verify_stems.py`)

## Git

Repo initialized here; push to private GitHub in a later phase. Never commit `.env`, cookies, transcripts, or generated CSVs.
