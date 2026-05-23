# music-script

Given one base song (title + artist), find other popular songs whose
musical **key matches** and whose **BPM is harmonically compatible** with
the base — within ±20%, or 2× / 0.5× also within ±20% (the DJ
"double-time / half-time" matches).

Pipeline:

1. Look up the base on **songkeyfinder.com** → get its key.
2. From songkeyfinder.com's "songs in this key" listing → collect candidates.
3. For each candidate, hit **GetSongBPM.com**'s free API → get BPM.
4. Keep candidates whose BPM passes the 1× / 2× / 0.5× ±20% tolerance test.
5. Print a Rich table + write a CSV.

## Recon-first workflow

The HTML shape of songkeyfinder.com and the exact response shape of the
GetSongBPM API are **not** hard-coded in this repo. Instead, the package
ships a `recon` subcommand that captures real responses on your machine.
Production selectors live in `music_script/selectors.py` and start out as
`None`; the production scraper refuses to run until they're filled in
against real captured HTML. **No guessed selectors in production code.**

You run recon once locally, share the dumped HTML + summary back, the
selectors get finalized against the real markup, and only then does the
`match` command work.

### Phase A — recon (on your machine)

```bash
cd ~/Documents/music-script

# 1. Install + env
pip install -e ".[dev]"
cp .env.example .env

# 2. Search recon — saves HTML for any URL shape that returns 200
python -m music_script recon search --title "Levitating" --artist "Dua Lipa"

# 3. Key-listing recon — same idea for /key/<slug>-style URLs
python -m music_script recon key --key "B minor"

# 4. Analyze every saved HTML and write recon-output/SUMMARY.md
python -m music_script recon analyze

# 5. (after getting an API key from https://getsongbpm.com/api)
#    Edit .env to add GETSONGBPM_API_KEY, then:
python -m music_script recon api-probe --title "Levitating" --artist "Dua Lipa"
```

Share `recon-output/SUMMARY.md` + a couple of representative HTML files
back. Selectors get pinned, fixtures land in `tests/fixtures/`, parser
tests get written, you receive an updated zip.

### Phase B — match (after selectors are filled in)

```bash
python -m music_script match \
    --title "Levitating" --artist "Dua Lipa" \
    --output ./levitating-matches.csv \
    --limit 50
```

Output: a Rich table (`rank | title | artist | key | bpm | ratio |
match_type`) and a CSV with the same columns.

## CLI reference

```
python -m music_script recon search --title TITLE --artist ARTIST [--output-dir DIR]
python -m music_script recon key --key "B minor" [--output-dir DIR]
python -m music_script recon api-probe [--title T --artist A] [--output-dir DIR]
python -m music_script recon analyze [--input-dir DIR]

python -m music_script match --title T --artist A
    [--base-key "B minor"]      # skip step 1
    [--base-bpm 103]            # skip the base BPM lookup
    [--tolerance 0.20]          # default ±20%
    [--limit 50]                # max candidates evaluated
    [--output matches.csv]      # CSV output path
    [--rate-limit-sleep 1.5]    # seconds between API calls
    [--debug]                   # verbose tracebacks
```

## Attribution

This tool calls the free **GetSongBPM** API. Per their terms, the
`match` command always prints

> Powered by GetSongBPM — https://getsongbpm.com

on startup. Don't remove that.

## Spinning this off into its own repo

```bash
cd ~/Documents/music-script
git init && git add . && git commit -m "Initial commit"
gh repo create music-script --private --source=. --push
```
