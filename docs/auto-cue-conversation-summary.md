# Auto-cue conversation summary

This note covers the work on PR #9 (`cursor/auto-cue-package-d400`) from the accuracy thread through the leak-free k-fold. Detail and tables live in [auto-cue-accuracy-worklog.md](auto-cue-accuracy-worklog.md) and [auto-cue-kfold-results.md](auto-cue-kfold-results.md). PR #9 was not merged.

The package predicts Serato hot cues. The cues that matter here are cue 4 (the mix-in / first drop) and cue 6 (the last drop). A hit is within 1 beat of gold. BPM bands are bass under 80, drum and bass 80–100, midtempo 100–115, and house 115 and up. The LLM is `gpt-6.1-terra` at medium reasoning. The QA set is 37 tracks in `qa-all` (three bad gold files were already dropped). The gold pool is 289 tracks with audio at `gold-pool/g2_*.mp3`.

## What was asked

1. Make per-cue abstention actually fire. A wrong cue is worse than a blank. Target about 90% precision, with blank propagation: a blank cue 4 blanks cues 1–3, and a blank cue 6 blanks cue 5.
2. Then shift to raw cue 4 and cue 6 accuracy, in this order: the ±16-beat errors, cue 6 as the last drop, drum and bass, then a small non-LLM ranker. Measure each change on the QA set and on a held-out slice of the gold pool.
3. After a 100% / 96.7% “held-out” score, audit for leakage. The eval set was only about 65% / 54%, so that gap was not believable.
4. Finish the clean plan: a track must not retrieve itself or a same-title copy, run a real k-fold where few-shot and the gradient booster see only the train fold, ablate `track_pct`, and report cue 4 / cue 6 by BPM band for the LLM, the ranker, and the combination, plus the QA set under the same rule.
5. Write this work up in docs on the PR. Do not merge PR #9. Do not print the API key.

## Abstention

`calibrated_confidence.py` scores each cue from code signals: margin, zoom agreement, kick slam-in, lattice alignment, agreement with the candidate list, and how strong a rival 16 beats away is. Self-consistency across multiple samples was added too.

The first agreement check always returned 0.15 because the tolerance was too tight. Widening it to 16 beats and matching the drop-candidate list fixed the constant. The curves still did not support a 90% precision abstain. Cue 4 topped out near 86% precision at low coverage. Cue 6 was inverted: a higher threshold lowered precision. The signals do not separate correct from wrong well enough. Work moved to raw accuracy. The abstention code stayed in the package.

## ±16 beats

On the baseline QA run, most ±16 mistakes were the model 16 beats early. The predicted phrase had a larger low-band jump than the gold phrase. The model was marking the energy transition. Gold often marks the sustained drop one phrase later. A hand-built discriminator for drop-start versus run-up versus continuation picked gold only about 6% of the time, so it was not shipped.

Forcing a +16 “sustained” candidate and telling the model to always prefer the later beat dropped QA accuracy to 27% cue 4 and 16% cue 6. The model overshot. That change was reverted.

A later, narrower version of the same idea is what stuck: drum and bass gets a bonus for already-loud bass and a lower weight on the low-band jump, and the prompt’s “prefer the later of two candidates 16 apart” applies to drum and bass only. Bass and house keep a stronger transition weight. One global weight change had improved drum and bass and hurt bass (cue 4 73% to 64%, cue 6 45% to 36%). Splitting the weights by band put bass and house back and kept the drum and bass gain.

## Cue 6 and drum and bass

Cue 6 gold was in the candidate list 41% of the time before 16-beat phrases were admitted more freely, and 73% after. The misses that remain are often a few beats off the 16-beat grid.

Drum and bass spacing on the stored Serato grid is about 32 beats from cue 3 to cue 4, the same as house. Cue 4 to cue 6 is shorter in drum and bass than in house, which fits an 85 BPM half-time label rather than a bug that doubles every beat index. No half-time rewrite was applied. The drum and bass misses were mostly transition versus sustain.

## Ranker, before the leak was closed

A gradient booster and a logistic model were fit on candidate rows from pool tracks. The useful model was the booster. On a row-wise test split of that fit, cue 4 was about 75% precision and 48% recall. Cue 6 was about 64% precision and 32% recall. The top feature was `track_pct`, the candidate’s position in the track.

A comparison on the QA set, before few-shot exclusion was wired, was roughly LLM 65% / 54%, ranker 62% / 46%, combined 68% / 54% on cue 4 / cue 6. Those weights and the candidate generator had been tuned on the same QA set, so that combined gain was not a clean holdout. The logistic model did not converge cleanly and was dropped.

## The leak

The 30-track “held-out” run scored cue 4 30/30 and cue 6 29/30. `get_nearest_by_bpm` ranks every pool track with audio. The nearest neighbor of a track is itself. All 30 scored tracks were in their own top five few-shot examples, so the prompt contained that track’s gold cues.

Other audit notes:

- Scoring weights were chosen on the QA set, not on a pool train fold.
- The ranker’s “first 150 tracks in dict order” was not the same partition as the shuffled holdout, so “no overlap” was not a real guarantee.
- Train and holdout mean cue 4 position were almost the same (0.309 vs 0.305), so the split itself did not shift `track_pct`. The feature can still memorize “drops sit near 30% of the track.”
- A crude title check found no obvious QA/pool duplicates. A later normalized check is what the k-fold uses. It is stricter, and it still only banned a handful of train paths in fold 0.

## What was finished after the audit

`GoldPool.paths_to_exclude` drops the scored track, a matching library path, and same-title copies. Titles are lowercased, parentheticals and remix words are stripped, and a match also requires BPM within 3 or duration within 8%. The package eval, the split script, and the ranker comparison pass that set. Unit tests cover self-exclusion and a same-title remix copy.

`eval_kfold.py` runs 5-fold on all 289 pool tracks (seed 42). Few-shot examples and the booster for a fold come only from the other folds, minus same-title copies of the test fold. `track_pct` is fit both on and off. Fold membership is [auto-cue-kfold-folds.json](auto-cue-kfold-folds.json). After the run, saved predictions had 0 self-retrievals and 0 test-fold mates in the example lists.

The QA set was scored the same way. Its booster was trained on the pool after tracks that match a QA title were removed.

## Numbers to keep

Gold pool, 289 tracks, leak-free:

| Method | Cue 4 | Cue 6 | Cue 4 precision (coverage) |
|--------|-------|-------|----------------------------|
| LLM only | 67.8% (196/289) | 59.5% (172/289) | 68.5% (99%) at confidence 0.5 |
| Ranker with `track_pct` | 68.9% | 59.2% | 84.6% (72%) at probability 0.3 |
| Ranker without `track_pct` | 34.9% | 58.1% | 45.0% (58%) |
| Combined with `track_pct` | 70.6% | 58.1% | 71.3% (99%) |

LLM by band on the pool: bass 52% / 44% (25 tracks), drum and bass 60% / 47% (15), house 70% / 62% (247). Midtempo is 2 tracks. LLM ±16 errors: 11 on cue 4, 14 on cue 6.

QA set, 37 tracks, same exclusion:

| Method | Cue 4 | Cue 6 |
|--------|-------|-------|
| LLM only | 67.6% (25/37) | 48.6% (18/37) |
| Ranker with `track_pct` | 64.9% | 45.9% |
| Combined with `track_pct` | 62.2% | 48.6% |

LLM by band on QA: bass 73% / 36%, drum and bass 58% / 33%, house 75% / 75%. LLM ±16 errors: 6 on cue 4, 5 on cue 6.

Reading of those numbers:

- Honest pool accuracy matches the QA set. It is not 100%.
- The cue 4 ranker is mostly a position prior. Removing `track_pct` cuts cue 4 from 69% to 35%. Cue 6 barely moves, so cue 6 is not just “where in the track.”
- LLM self-confidence does not abstain. Coverage stays near 99% and precision equals accuracy. The ranker at probability 0.3 is the high-precision option on the pool, and only while `track_pct` is included.
- Combined does not beat the LLM on the QA set. On the pool it gains about 3 cue 4 points and loses about 1 cue 6 point.

Thresholds were declared ahead of the fold (0.5 and 0.3). They were not tuned on the test fold. The audio scoring weights were still chosen on the QA set before this k-fold, so the QA table is not a pure untouched holdout of those weights. The pool fold is the untouched holdout for the booster.

## Files

| Path | What it is |
|------|------------|
| `packages/auto_cue/auto_cue/features.py` | Drop score and candidate list. Weights depend on BPM band. |
| `packages/auto_cue/auto_cue/llm.py` | Prompt. “Prefer the later candidate” is drum and bass only. |
| `packages/auto_cue/auto_cue/gold.py` | `paths_to_exclude` and few-shot `exclude_paths`. |
| `packages/auto_cue/auto_cue/ranker.py` | Candidate feature vector, with `track_pct` optional. |
| `packages/auto_cue/auto_cue/calibrated_confidence.py` | Earlier abstention attempt. Not the accuracy fix. |
| `packages/auto_cue/tests/test_gold_exclusion.py` | Self and same-title exclusion. |
| `eval_kfold.py` | Leak-free 5-fold plus the QA set. |
| `docs/auto-cue-kfold-results.md` | Full band tables, including precision and ±16 counts. |
| `docs/auto-cue-kfold-folds.json` | Which pool paths were in which fold. |
| `docs/auto-cue-accuracy-worklog.md` | Decision log and the leakage audit. |

## Left as-is

PR #9 is open and not merged. Cue 6 on bass and drum and bass is still the weak spot (QA 36% and 33%). Gold that sits a beat or two off the 16-beat grid is still missing the candidate list. LLM confidence is not a usable abstain signal. A later pass could refit the audio weights inside the train fold only, or use the ranker’s probability as the abstain score without treating `track_pct` as musical evidence.
