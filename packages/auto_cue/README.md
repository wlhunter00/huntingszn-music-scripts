# auto-cue

Automatic Serato hot-cue tagger for HuntingSzn. Predicts 8 cues from audio features using Will's cue system.

## Features

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

### First-drop selection

The first-drop ranker extends candidate features with immediate 16/32-beat bass,
RMS and kick gains, energy relative to the track's loud sections, preceding
break/build context, distance from the first strong kick-in, and earlier
similarly energetic candidates. These are computed from audio only, without
cue 1 or any other inference-time gold label. `track_pct` can still be ablated;
that ablation is **not** position-free: first-kick distance and earlier-section
counts intentionally retain musical-order context.

The evaluator trains cue-4 models on permitted training tracks only. Each track
has equal total training weight. Cue-6 features and models are unchanged. The
target prompt replaces its expanded candidate list with a scored, ranker-ordered
list of all candidates for cue 4, while retaining the complete phrase table for independent
cue-6 selection. Scores are advisory, not LLM confidence. A subsequent breakdown
does not disqualify an earlier full mix-in entry merely because `sust` is negative.

The existing 0.3 combined-method gate is fixed, not fitted on QA. All scored
candidates are shown; no top-K truncation is applied. Any future threshold
tuning must be nested within pool folds.
The baseline exports a full-pool model to `first-drop-model.json` under its
output directory. Model files and evaluation outputs are not committed. JSON
inference does not require sklearn or load executable pickle data:

```bash
uv run auto-cue --file "track.mp3" --first-drop-model "$OUTPUT/first-drop-model.json"
```

Without `--first-drop-model`, the CLI keeps the unranked candidate presentation;
the revised first-drop interpretation still applies. Cue beats always remain in
original grid coordinates. Model export names its input schema and refuses
incompatible feature definitions or malformed trees.

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
