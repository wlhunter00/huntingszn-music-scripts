# auto-cue

Automatic Serato hot-cue tagger for HuntingSzn. Predicts 8 cues from audio features using Will's cue system.

## Features

### Cue-6 last-drop evaluation variants

The evaluator also reports `_lastdrop` variants of the raw and `_build32`
methods. A separate cue-6 GBM adds later drop-level window counts, beats to
track end, post-candidate bass/RMS/kick trends and levels relative to the
track's strongest candidate windows. The original folds, identity exclusions,
classifier settings and 0.3 gate are unchanged; cue 4 is never modified.
Without `track_pct` is not position-free because beats-to-end remains a feature.

These are **evaluation-only** variants. Pool selection improved the saved
context-model combined+build32 cue 6 from 189/289 to 201/289, but held-out QA
fell from 20/37 to 19/37. Fixed last-full-section and outro filters performed
worse and are not enabled in evaluation. Changed picks receive zero emission
confidence pending calibration. Original metrics and production CLI cue
writing remain unchanged; the QA result does not justify deployment.

### Offline structural build prior

The evaluator additionally reports `_build32` variants of its five original
methods. A pick lacking both a bass and RMS rise from the preceding 32 beats
to the following 16 beats is replaced with the first supported candidate in
ranker order. Cue 4 is processed before cue 6; replacements preserve their
ordering. Missing windows and abstentions are left unchanged. The zero-gain
cutoff is fixed, not fitted on QA, and uses no gold cues at inference.

Raw predictions, the existing 0.3 gate, and the original five metrics remain
unchanged. Variant picks are saved separately for reproducible replay. Changed
picks have zero emission confidence pending calibration: raw exact-hit gains
are not evidence of calibrated confidence. This is an evaluation variant, not
a change to production CLI cue writing.

Pool-only selection on the saved context-ranker run improved combined cue 4
from 229/289 to 231/289 and cue 6 from 187/289 to 189/289. Held-out QA stayed
26/37 and 20/37. This small gain does not meet the 80% cue-4 target. Fixed
same-phase snapping hurt pool cue 4 and is not enabled.

### Audio-derived phrase phase

Phrase extraction estimates a 0/4/8/12-beat phase from normalized bass, RMS,
kick-density transitions and novelty, using only the audio beat features.
The strongest quarter of 16-beat-spaced boundary evidence determines the phase;
short or silent tracks fall back to zero. No gold cues are used at inference.

Because half-phrase alignment is ambiguous, candidate generation retains the
zero- and eight-beat hypotheses plus the estimated phase and its eight-beat
counterpart. Each hypothesis has independently aggregated 8/16/32-beat windows
and the existing drop scoring/shortlist. The original zero-phase top five stay
at the head of the candidate list; scored alternatives follow, without duplicates.
This deliberately increases the candidate budget, not just its recall numerator.
The prompt shows primary-phase windows and alternate candidate windows, and
explicitly lists the alternate candidates. Ranker vectors include audio phase
support and look up shifted windows by their actual starting beat.

All window starts, candidate beats, track percentages and written cue positions
remain in the original Serato grid coordinates. The phase must never be added
again when writing cues. Feature caches are versioned so old zero-phase-only
features are not silently reused.

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
| 3 | Run-up to first drop | cue4 - 16 or 32 |
| 2 | Intro/entry | 16-beat steps before cue3 |
| 1 | Intro | Beat 0, cue2, or a 16-beat step before cue2 |
| 6 | Last drop | Judgment call |
| 5 | Run-up to last drop | cue6 - 16 or 32 |
| 7 | Mix-out point | cue6 + 32 or 64 |
| 8 | Last call | cue6 + 64 or 96; at least 32 beats before end |

Cue 4 anchors the 16-beat intro lattice; cue 6 anchors the 32-beat outro
lattice. A single-drop track may have cue6 = cue4. Missing drop predictions
leave dependent cues unknown. The LLM predicts primary positions; the package
derives run-up cues 3 and 5. Positions are beat offsets, not milliseconds.

## Reproducible paid baseline

From the repository root, fetch the original datasets with locally configured
B2 credentials (never put credentials in the command or commit them):

```bash
mkdir -p /workspace/qa-all /workspace/gold-pool
rclone copy b2:huntingszn-music/_auto-cue-data/qa-all/ /workspace/qa-all/
rclone copy b2:huntingszn-music/_auto-cue-data/gold-pool/ /workspace/gold-pool/
```

The evaluator expects audio at each dataset root; the archive stores it in
`small/`. Create local aliases once (no remote writes):

```bash
python - <<'PY'
from pathlib import Path
for root in (Path('/workspace/qa-all'), Path('/workspace/gold-pool')):
    for audio in (root / 'small').glob('*.mp3'):
        alias = root / audio.name
        if not alias.exists():
            alias.symlink_to(Path('small') / audio.name)
PY
```

Use writable alternative roots if needed and pass `--pool-dir` / `--qa-dir`.
QA has 40 audio files; three named exclusions leave 37 tracks. The clean pool
has 289 rows; 19 additional archived audio files are not evaluated. Labels are
in CSVs; the small audio copies intentionally contain no Serato tags.

Commit source changes before running. Supply `OPENAI_API_KEY` through the
environment. On Linux, run one process per output directory:

```bash
make auto-cue-baseline ARGS='smoke --output /home/ubuntu/autocue-data/my-baseline --budget 15'
make auto-cue-baseline ARGS='full --output /home/ubuntu/autocue-data/my-baseline --budget 15'
make auto-cue-baseline ARGS='analyze --output /home/ubuntu/autocue-data/my-baseline'
```

The target adds the optional scikit-learn evaluation dependency without changing
production dependencies. `--repo` selects the checkout containing `eval_kfold.py`.
The imported `auto_cue` package must also live inside that checkout; otherwise
the runner refuses to mix evaluator and package revisions. Run through that
checkout's uv environment instead.
Default roots are `/workspace/gold-pool` and `/workspace/qa-all`.
An exclusive `.running` file prevents concurrent paid runs in one output
directory. After an unclean exit, verify its recorded PID is no longer running
before removing only that lock file; keep all receipts and stop markers.
The smoke test scores two tracks with the entire first fold excluded; the full
run reuses them. Five folds (seed 42) exclude self, the held-out fold, and
same-title copies from ranker training and few-shot retrieval. QA identities
are excluded from pool examples/training. Model: `gpt-6.1-terra`, medium reasoning,
4096 output-token cap, one LLM worker. Feature extraction currently requires
Linux/fork. Use the same environment and dataset for comparisons; model output
is not guaranteed deterministic.

Successful API responses are fsynced before parsing and scoring; prediction rows
are also fsynced. Repeat the same command/output directory to resume, not a new
directory. A manifest rejects changed source revision, CSVs, or audio (size and
SHA-256 for every MP3/FLAC under both roots, including local aliases). Feature
cache filenames include the audio content hash and beatgrid parameters, not the
audio filename. Manifests created before audio fingerprinting fail closed and
cannot be resumed with this version. Transport/5xx
failures allow three retries with exponential backoff; each uncertain attempt's
reservation remains in the budget. Authentication and other HTTP errors stop
immediately. Budget checks include actual spend plus uncertain reservations and
a conservative next-request reserve, using repository model pricing. No tool
can establish the final billing of a lost response: review `STOP.json` and
pending receipts manually before approving repayment. A pending request after a
crash fails closed instead of automatically being issued again. Do not delete
receipts to reset spending. Keep all output outside the repository.

### Reference: 2026-11-07, source `1cc3ddf`

Exact hit is within **1 beat**, including low-confidence predictions; missing
predictions count as misses. Values below are **cue4 / cue6** percentages.

| Method | Pool (289) | QA (37) |
|--------|------------|---------|
| LLM | 67.1 / 59.2 | 67.6 / 51.4 |
| Ranker with position | 68.9 / 59.2 | 64.9 / 45.9 |
| LLM + ranker with position | 70.2 / 58.5 | 62.2 / 45.9 |
| Ranker without position | 34.9 / 58.1 | 40.5 / 51.4 |
| LLM + ranker without position | 47.4 / 58.1 | 56.8 / 54.1 |

Combined methods use the predeclared ranker probability gate of 0.3, then fall
back to the LLM. Historical LLM scores were pool 67.8/59.5 and QA 67.6/48.6.
Recorded cost was $4.89919285, with $0.050551 reserved for one uncertain call.
`docs/auto-cue-baseline.json` contains method/band metrics and signed error
buckets for this run. Buckets are hits within ±1 beat, misses within ±2 beats
of signed 16-beat multiples, other misses, or no prediction. Compare later
`summary.json` and `analysis.json` against it; do not overwrite the reference.

## Safety

- Never modifies tracks with human (non-MIK) cues
- Never touches BPM-locked tracks
- Skips tracks in Sets/, Perma Playlists/, Produced by me crates
- Never rewrites dynamic (multi-marker) grids
- Abstains when confidence is low
