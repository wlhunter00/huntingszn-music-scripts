# Auto-cue accuracy worklog

Status as of 2026-11-03 (America/New_York night). This is the working record for PR #9 (`cursor/auto-cue-package-d400`). The earlier held-out **100% / 96.7%** figure was leakage (the track was its own few-shot example). The leak-free numbers are below and in [`auto-cue-kfold-results.md`](auto-cue-kfold-results.md).

## Clean results (5-fold, seed 42)

Few-shot and the GBM for a fold see only the other folds. The scored track, every other track in its test fold, and same-title copies (remix tags stripped, BPM within 3 or duration within 8%) are excluded. A post-run check found **0** self-retrievals and **0** test-fold mates in the few-shot lists. Thresholds were not fit on the test fold: LLM confidence 0.5 (the package default), ranker probability 0.3 (the predeclared gate). `ranker_nopct` zeros `track_pct`.

Gold pool, 289 tracks. The pool is mostly house (247). Bass is 25 tracks, DnB 15, midtempo 2.

| Method | Cue4 | Cue6 | Cue4 prec @ thresh (cov) | Cue6 prec @ thresh (cov) |
|--------|------|------|---------------------------|---------------------------|
| LLM only | **67.8%** (196/289) | **59.5%** (172/289) | 68.5% (99%) | 60.4% (99%) |
| Ranker, with `track_pct` | 68.9% | 59.2% | **84.6%** (72%) | **77.2%** (62%) |
| Ranker, no `track_pct` | 34.9% | 58.1% | 45.0% (58%) | 76.0% (61%) |
| Combined, with `track_pct` | 70.6% | 58.1% | 71.3% (99%) | 58.9% (99%) |
| Combined, no `track_pct` | 47.8% | 57.8% | 48.3% (99%) | 58.4% (99%) |

LLM by band on the pool: bass 52% / 44%, DnB 60% / 47%, house 70% / 62%. ±16 errors for LLM: 11 cue4, 14 cue6.

QA set, 37 tracks, same exclusion rule, GBM trained on the pool with QA title-copies removed:

| Method | Cue4 | Cue6 |
|--------|------|------|
| LLM only | **67.6%** (25/37) | **48.6%** (18/37) |
| Ranker, with `track_pct` | 64.9% | 45.9% |
| Ranker, no `track_pct` | 40.5% | 51.4% |
| Combined, with `track_pct` | 62.2% | 48.6% |

QA LLM by band: bass 73% / 36%, DnB 58% / 33%, house 75% / 75%. LLM ±16: 6 cue4, 5 cue6.

What this says:

- The pool is not a 100% problem. Honest LLM accuracy is about **68% / 60%**, in the same range as the QA set, not above it.
- `track_pct` is most of the cue4 ranker. Removing it drops pool cue4 from 69% to 35%. Cue6 barely moves (59% → 58%), so cue6 is not just “where in the track.”
- At the predeclared 0.3 probability, the ranker that still has `track_pct` is the high-precision option on the pool (cue4 85% precision at 72% coverage). LLM self-confidence does not abstain: coverage stays ~99% and precision equals accuracy.
- Combined does not beat LLM on the QA set. On the pool it picks up about 3 cue4 points and gives back about 1 cue6 point.

Fold membership is `docs/auto-cue-kfold-folds.json`. Full band tables are in `docs/auto-cue-kfold-results.md`.

## What this work is

Improve raw cue 4 and cue 6 beat accuracy for the `auto_cue` package. A wrong cue is worse than a blank, but the current ask is raw accuracy first, with per-cue blanking left as-is. Measure every change on the 37-track QA eval (`qa-all/gold.csv`; often called the 42-track set) and on a held-out slice of the gold pool (`gold-pool/g2_*.mp3`, 289 files, listed in `gold_pool_clean.csv`). Report cue 4 / cue 6 accuracy, precision at the per-cue confidence threshold, and a by-BPM-band table.

BPM bands used throughout:

| Band | BPM |
|------|-----|
| bass | < 80 |
| dnb | 80–100 |
| midtempo | 100–115 |
| house | 115+ |

Model for the LLM runs: `gpt-6.1-terra`, reasoning effort `medium`. Gold pool audio lives at `/workspace/gold-pool/g2_NNN.mp3` (289 files). QA audio lives at `/workspace/qa-all/`.

## Honest numbers (what to trust)

### 37-track QA eval, LLM only

These runs do not retrieve the QA track from the gold pool as itself, so they are the numbers to trust until a clean gold-pool fold exists.

| Stage | Cue4 | Cue6 | Cue4 ±16 | Cue6 ±16 | bass c4/c6 | dnb c4/c6 | house c4/c6 |
|-------|------|------|----------|----------|------------|-----------|-------------|
| Baseline (scoring before the ±16 experiments) | 59.5% (22/37) | 48.6% (18/37) | 9 | 5 | 73% / 45% | 33% / 17% | 75% / 83% |
| Naive “always prefer +16 sustained” prompt + extra +16 candidates | 27.0% (10/37) | 16.2% (6/37) | 22 | 17 | 9% / 9% | 58% / 42% | 8% / 0% |
| After reverting that, with liberal 16-beat candidates + DnB-only “prefer later” + quieter sustain penalty | 64.9% (24/37) | 48.6% (18/37) | 7 | 6 | 64% / 36% | 58% / 33% | 75% / 75% |
| BPM-band-aware scoring (current code) | 64.9% (24/37) | 54.1% (20/37) | 6 | 3 | 73% / 45% | 58% / 33% | 75% / 83% |

Same 37-track set, three predictors, after the BPM-band-aware scoring:

| Method | Cue4 | Cue6 |
|--------|------|------|
| LLM only | 64.9% | 54.1% |
| GBM ranker only | 62.2% | 45.9% |
| Combined (ranker if prob > 0.3, else LLM) | 67.6% | 54.1% |

The combined cue4 gain is +2.7 points on the same 37 tracks the scoring was iterated against. It is not a held-out proof.

Precision at a per-cue confidence threshold was the earlier calibration track, not this accuracy track. Calibrated code-confidence did not reach 90% precision (cue4 topped out near 85.7% at low coverage; cue6 was inverted: a higher threshold lowered precision). Those signals are still in the package. They were not refit in this accuracy pass.

### Gold-pool “held-out” 100% / 96.7% — do not use

A 30-track slice of the shuffled gold pool (seed 42, 70/30 split, first 30 of the 87 held-out tracks) scored cue4 30/30 and cue6 29/30. That is not generalization. The eval is ~65/54 on the QA set. The gap is the leak below.

## Leakage audit

Script: `audit_leakage.py` (local, not required for the package). Split matches `eval_split.py`: seed 42, 289 pool tracks with audio after dropping the 37 QA filenames, 202 train / 87 held-out.

### (a) Few-shot retrieval includes the track being scored

`GoldPool.get_nearest_by_bpm` ranks every pool track with audio by `|bpm diff| + 0.01 * |length diff|`. `eval_split.py` calls `get_pool_fewshot_examples(pool, ...)` with the full pool.

Result: all 87 held-out tracks are still in that pool. On the 30 tracks that were actually scored, **30/30 retrieved themselves in the top-5 few-shot examples**. The prompt then contains that track’s own gold cues. A BPM/length match of zero is the nearest neighbor of a track to itself. This fully explains 100% / 96.7%.

### (b) Ranker and scoring weights vs the held-out slice

- Scoring weights (low-energy bonus, `delta_low` 0.4 → 0.2, 16-beat threshold × 0.7, then the BPM-band split) were chosen by looking at the **37-track QA eval**, not by a gold-pool train fold. The QA set is the number we keep quoting, so those weights are overfit to it until a clean pool fold says otherwise.
- `train_ranker.py` walks `pool.tracks` in dict order, skips QA filenames, and stops at 150 tracks. The held-out split is a **shuffle** of a different list and starts at index 202 of that shuffled list. “First 150 in dict order” and “index ≥ 202 after shuffle” are not the same partition. The audit’s “no overlap” line is **not a guarantee** — it compared two different orderings. The ranker must be retrained on an explicit train-fold path set before any held-out ranker number is believed.
- The 37-track LLM-vs-ranker table above is still tainted in a second way: the GBM was fit on gold-pool tracks, then scored on QA. That part is a real holdout relative to the ranker’s training rows, but the **features and candidate generator** were tuned on that same QA set. Ranker-only 62.2% / 45.9% is “GBM on QA audio,” not “GBM on a pool fold the weights never saw.”

### (c) `track_pct`

GBM importance on the 150-track fit:

| Cue | Top features |
|-----|----------------|
| cue4 | `track_pct` 0.486, `low_db` 0.169, `drop_score` 0.119, `delta_low` 0.107 |
| cue6 | `track_pct` 0.375, `contrast` 0.172, `drop_score` 0.143, `delta_low` 0.131 |

Train vs shuffled-holdout mean cue4 position: 0.309 vs 0.305. The split itself does not shift the prior. `track_pct` is still a position prior: gold drops sit in a narrow fraction of the track, so the ranker can look good by betting on “around 30% in” without hearing the drop. It should be ablated on a clean fold (model with and without `track_pct`).

### (d) Duplicate songs

A crude stem-overlap check between held-out titles and the 37 QA filenames found no obvious duplicates. It strips words like “remix” and looks for substring containment. It will miss the same record under a different filename, a radio edit vs extended mix, or a remix that doesn’t share a long substring. A real check needs normalized artist+title (and duration) before the clean fold is trusted.

## What was built (chronological)

1. **Calibrated per-cue confidence** (`calibrated_confidence.py`). Margin, zoom agreement, kick slam-in, lattice alignment, code agreement, rival ±16 strength, plus self-consistency across samples. Code agreement started stuck at 0.15 because the tolerance was too tight; widening to 16 beats and matching the drop-candidate list fixed the constant. The fitted curves still did not justify a 90% precision abstain. Cue6 was inverted. Work pivoted to raw accuracy.

2. **±16 error study.** On the baseline QA run, 13 of 16 ±16 mistakes were the model 16 beats **before** gold. Phrase features at the prediction had a larger low-band jump than at gold. Interpretation: the scorer likes the energy **transition**; gold often marks the **sustained** drop a phrase later. A discriminator that tried to label drop-start vs run-up vs continuation picked gold only ~6% of the time (inverted), so it was not shipped as a rule.

3. **Failed fix.** Extra “+16 sustained” candidates and a prompt that said always prefer the later steady-energy beat. QA accuracy fell to 27% / 16%. The model overshot: many new errors were +16. Reverted.

4. **Candidate recall.** Gold cue6 was in the candidate list 41% of the time before the liberal 16-beat pass, **73%** after (27/37 exact; the other 10 were 4–8 beats off the 16-beat grid, e.g. 228 vs 224). Gold cue4 on DnB is often 1 beat before a 16-beat boundary (63, 79, 95). Those still miss an exact-beat match.

5. **DnB spacing.** Cue3→cue4 is ~32 beats in both DnB and house when counted in the Serato grid as stored. Cue4→cue6 is shorter in DnB (~123 beats) than house (~186). That is consistent with 85 BPM labels being the half-time grid, not with a simple “double every beat index” bug. The ±16 misses on DnB were mostly “transition vs sustain,” not a doubled grid. No half-time rewrite was applied.

6. **BPM-band-aware scoring** (current `features.py`). One global weight set improved DnB and hurt bass (cue4 73→64, cue6 45→36) and house cue6 (83→75). Split the score:
   - bass &lt; 80: `delta_low` weight 0.35, original sustain penalty (quiet drop after a loud phrase is penalized).
   - DnB 80–100: bonus for `low_db` &gt; -15 / -20, `delta_low` weight 0.2, sustain penalty only if the phrase itself is quiet (`low_db` &lt; -20).
   - else: milder loudness bonus, `delta_low` 0.3, sustain penalty only if `low_db` &lt; -22.
   - 16-beat (non-32) candidate threshold: DnB ×0.7, bass ×0.9, other ×0.8.
   - Prompt “prefer the later of two candidates 16 apart” is **DnB only**.

   QA after this: bass back to 73/45, DnB held at 58/33, house cue6 back to 83, overall cue6 48.6→54.1, ±16 errors 12→9. Still tuned on the QA set.

7. **Ranker.** Logistic regression and gradient boosting on candidate rows (phrase features + BPM one-hots + `track_pct`). 150 pool tracks, 2438 candidates, ~5% positive. Test split of those rows: cue4 GBM precision 0.75 / recall 0.48 / F1 0.585; cue6 GBM precision 0.636 / recall 0.318 / F1 0.424. Logistic did not converge cleanly and had low precision. QA comparison table is in the honest-numbers section. Models were saved to `ranker_models.pkl` locally; that pickle is not part of the package commit.

8. **Leak audit and the start of the fix.** `get_nearest_by_bpm` and `get_pool_fewshot_examples` now take `exclude_paths`. Default is `None`, so existing callers are unchanged and **still leak** until `eval_split.py` (and any QA eval that might share a filename with the pool) passes the track under test, and until a clean fold passes the entire test fold.

## Clean-fold plan (done)

1. `GoldPool.paths_to_exclude` drops the scored track, a matching library path, and same-title copies. `get_pool_fewshot_examples` already accepted `exclude_paths`. The package eval, `eval_split.py`, and `eval_ranker_comparison.py` pass that set.
2. `eval_kfold.py` runs 5-fold (seed 42) on all 289 pool audio files. QA filenames are not in the pool. Fold lists are saved.
3. Scoring weights stayed frozen. Each fold refits the GBM on train-fold candidates only, with and without `track_pct`.
4. Title match: parenthesis and remix words stripped, key length at least 4, and BPM within 3 or duration within 8%. Those paths are removed from few-shot and from that fold’s ranker training. Cross-fold title bans on this split were small (3 paths held out of fold 0’s train set).
5. Results are the tables at the top of this file. Per-fold raw rows are in `kfold_predictions.jsonl` locally and are not committed.
6. PR #9 stays unmerged.

## Files touched for this accuracy thread

| Path | Role |
|------|------|
| `packages/auto_cue/auto_cue/features.py` | Drop score and candidate list. BPM-band weights live in `_identify_drop_candidates`. |
| `packages/auto_cue/auto_cue/llm.py` | Prompt. DnB-only adjacent-candidate tie-break. |
| `packages/auto_cue/auto_cue/gold.py` | `exclude_paths` added; callers not updated yet. |
| `packages/auto_cue/auto_cue/calibrated_confidence.py` | Earlier abstention work. Not the accuracy fix. |
| `eval_split.py` | Leaky held-out runner. Must exclude the test fold before reuse. |
| `train_ranker.py` | GBM/logistic fit. Must take an explicit train path list. |
| `eval_ranker_comparison.py` | LLM vs ranker vs combined on the 37 QA tracks. |

## Decision log (short)

- Abstention first: code confidence did not separate correct from wrong well enough for 90% precision. Stopped pushing the threshold.
- ±16 is mostly “early by one phrase,” concentrated in DnB, not a universal +16 shift. Forcing +16 globally destroyed bass and house.
- Bass and DnB need different transition-vs-sustain weights. One global `delta_low` cut regressed bass.
- Cue6 misses are largely “gold not on the candidate lattice” plus “not the last drop,” not only the ±16 offset. Candidate recall 41% → 73% is necessary and not sufficient.
- Any gold-pool accuracy number is invalid until few-shot cannot see the scored track or its fold-mates.
