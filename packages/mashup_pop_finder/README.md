# mashup-pop-finder

Given one base song (title + artist), find other popular songs whose
musical **key matches** and whose **BPM is harmonically compatible** with
the base — within ±20%, or 2× / 0.5× also within ±20% (the DJ
"double-time / half-time" matches).

Pipeline:

1. Look up the base on **songkeyfinder.com** → get its key.
2. From songkeyfinder.com's "songs in this key" listing → collect candidates.
3. For each candidate, look up BPM on **songbpm.com** (default, no API key) or optionally **GetSongBPM.com**.
4. Keep candidates whose BPM passes the 1× / 2× / 0.5× ±20% tolerance test.
5. Print a Rich table + write a CSV.

## Recon-first workflow

The HTML shape of songkeyfinder.com and the exact response shape of the
GetSongBPM API are **not** hard-coded in this repo. Instead, the package
ships a `recon` subcommand that captures real responses on your machine.
Production selectors live in `mashup_pop_finder/selectors.py` and start out as
`None`; the production scraper refuses to run until they're filled in
against real captured HTML. **No guessed selectors in production code.**

You run recon once locally, share the dumped HTML + summary back, the
selectors get finalized against the real markup, and only then does the
`match` command work.

### Phase A — recon (on your machine)

```bash
cd ~/Documents/mashup-pop-finder

# 1. Install + env
pip install -e ".[dev]"
cp .env.example .env

# 2. Search recon — saves HTML for any URL shape that returns 200
python -m mashup_pop_finder recon search --title "Levitating" --artist "Dua Lipa"

# 3. Key-listing recon — same idea for /key/<slug>-style URLs
python -m mashup_pop_finder recon key --key "B minor"

# 4. Analyze every saved HTML and write recon-output/SUMMARY.md
python -m mashup_pop_finder recon analyze

# 5. (after getting an API key from https://getsongbpm.com/api)
#    Edit .env to add GETSONGBPM_API_KEY, then:
python -m mashup_pop_finder recon api-probe --title "Levitating" --artist "Dua Lipa"
```

Share `recon-output/SUMMARY.md` + a couple of representative HTML files
back. Selectors get pinned, fixtures land in `tests/fixtures/`, parser
tests get written, you receive an updated zip.

### Phase B — match (after selectors are filled in)

```bash
python -m mashup_pop_finder match \
    --title "Levitating" --artist "Dua Lipa" \
    --output ./levitating-matches.csv \
    --limit 50
```

Output: a Rich table (`rank | title | artist | key | bpm | ratio |
match_type`) and a CSV with the same columns.

## CLI reference

```
python -m mashup_pop_finder recon search --title TITLE --artist ARTIST [--output-dir DIR]
python -m mashup_pop_finder recon key --key "B minor" [--output-dir DIR]
python -m mashup_pop_finder recon api-probe [--title T --artist A] [--output-dir DIR]
python -m mashup_pop_finder recon analyze [--input-dir DIR]

python -m mashup_pop_finder match --title T --artist A
    [--base-key "B minor"]      # skip step 1
    [--base-bpm 103]            # skip the base BPM lookup
    [--bpm-source songbpm]      # songbpm (default) or getsongbpm
    [--tolerance 0.20]          # default ±20%
    [--limit 50]                # max candidates evaluated
    [--pages 3]                 # songkeyfinder pages (30 songs each; default: auto from --limit)
    [--output matches.csv]      # CSV output path
    [--rate-limit-sleep 1.5]    # seconds between scraper/API calls
    [--debug]                   # verbose tracebacks
```

Example — songs in A major harmonically compatible with 87 BPM:

```bash
python -m mashup_pop_finder match \
    --title "—" --artist "—" \
    --base-key "A major" --base-bpm 87 \
    --pages 4 --limit 100 --output ./a-major-87.csv
```

## BPM sources

| `--bpm-source` | API key? | Notes |
|----------------|----------|--------|
| `songbpm` (default) | No | Scrapes [songbpm.com](https://songbpm.com); polite rate limit recommended. |
| `getsongbpm` | Yes (`GETSONGBPM_API_KEY`) | Legacy; only if you already have a key. |

## Attribution

With the default source, `match` prints *BPM data via songbpm.com*.
If you use `--bpm-source getsongbpm`, it prints the GetSongBPM attribution instead.

## Spinning this off into its own repo

```bash
cd ~/Documents/mashup-pop-finder
git init && git add . && git commit -m "Initial commit"
gh repo create mashup-pop-finder --private --source=. --push
```
