# Leak-free k-fold results

5-fold gold pool, seed 42. Few-shot and the GBM see only the train fold, with the scored track, its test-fold mates, and same-title copies removed. `ranker_nopct` / `combined_nopct` zero out `track_pct`.

API cost recorded this run: $4.91. Resumed rows are not re-billed in that figure.

## Gold pool, pooled across folds

Raw accuracy is exact within 1 beat. Precision is among predictions whose score clears the predeclared threshold (LLM 0.5, ranker 0.3). Coverage is the share of gold cues that cleared that threshold. Thresholds were not fit on these folds.

| Method | Band | Cue4 acc | Cue4 prec (cov) | Cue6 acc | Cue6 prec (cov) | ±16 c4/c6 |
|--------|------|----------|-----------------|----------|-----------------|-----------|
| llm | all | 67.8% (196/289) | 68.5% (99%) | 59.5% (172/289) | 60.4% (99%) | 11/14 |
| llm | bass (<80) | 52.0% (13/25) | 54.2% (96%) | 44.0% (11/25) | 45.8% (96%) | 6/3 |
| llm | dnb (80-100) | 60.0% (9/15) | 60.0% (100%) | 46.7% (7/15) | 46.7% (100%) | 2/4 |
| llm | midtempo (100-115) | 0.0% (0/2) | 0.0% (100%) | 0.0% (0/2) | 0.0% (100%) | 0/0 |
| llm | house (115+) | 70.4% (174/247) | 71.0% (99%) | 62.3% (154/247) | 63.1% (99%) | 3/7 |
| ranker_pct | all | 68.9% (199/289) | 84.6% (72%) | 59.2% (171/289) | 77.2% (62%) | 11/9 |
| ranker_pct | bass (<80) | 56.0% (14/25) | 75.0% (48%) | 52.0% (13/25) | 66.7% (48%) | 5/1 |
| ranker_pct | dnb (80-100) | 60.0% (9/15) | 77.8% (60%) | 53.3% (8/15) | 100.0% (33%) | 1/2 |
| ranker_pct | midtempo (100-115) | 50.0% (1/2) | 50.0% (100%) | 50.0% (1/2) | 0.0% (50%) | 0/0 |
| ranker_pct | house (115+) | 70.9% (175/247) | 85.9% (75%) | 60.3% (149/247) | 77.8% (66%) | 5/6 |
| ranker_nopct | all | 34.9% (101/289) | 45.0% (58%) | 58.1% (168/289) | 76.0% (61%) | 2/7 |
| ranker_nopct | bass (<80) | 24.0% (6/25) | 37.5% (32%) | 40.0% (10/25) | 50.0% (48%) | 2/1 |
| ranker_nopct | dnb (80-100) | 20.0% (3/15) | 50.0% (40%) | 60.0% (9/15) | 100.0% (33%) | 0/1 |
| ranker_nopct | midtempo (100-115) | 0.0% (0/2) | 0.0% (100%) | 50.0% (1/2) | 0.0% (0%) | 0/0 |
| ranker_nopct | house (115+) | 37.2% (92/247) | 45.8% (62%) | 59.9% (148/247) | 77.2% (64%) | 0/5 |
| combined_pct | all | 70.6% (204/289) | 71.3% (99%) | 58.1% (168/289) | 58.9% (99%) | 11/14 |
| combined_pct | bass (<80) | 56.0% (14/25) | 58.3% (96%) | 44.0% (11/25) | 45.8% (96%) | 5/2 |
| combined_pct | dnb (80-100) | 60.0% (9/15) | 60.0% (100%) | 46.7% (7/15) | 46.7% (100%) | 2/4 |
| combined_pct | midtempo (100-115) | 50.0% (1/2) | 50.0% (100%) | 0.0% (0/2) | 0.0% (100%) | 0/0 |
| combined_pct | house (115+) | 72.9% (180/247) | 73.5% (99%) | 60.7% (150/247) | 61.5% (99%) | 4/8 |
| combined_nopct | all | 47.8% (138/289) | 48.3% (99%) | 57.8% (167/289) | 58.4% (99%) | 9/13 |
| combined_nopct | bass (<80) | 44.0% (11/25) | 45.8% (96%) | 40.0% (10/25) | 41.7% (96%) | 5/2 |
| combined_nopct | dnb (80-100) | 46.7% (7/15) | 46.7% (100%) | 53.3% (8/15) | 53.3% (100%) | 2/3 |
| combined_nopct | midtempo (100-115) | 0.0% (0/2) | 0.0% (100%) | 0.0% (0/2) | 0.0% (100%) | 0/0 |
| combined_nopct | house (115+) | 48.6% (120/247) | 49.0% (99%) | 60.3% (149/247) | 60.8% (99%) | 2/8 |

## QA eval (37 tracks), few-shot from the pool with same-title copies removed

Raw accuracy is exact within 1 beat. Precision is among predictions whose score clears the predeclared threshold (LLM 0.5, ranker 0.3). Coverage is the share of gold cues that cleared that threshold. Thresholds were not fit on these folds.

| Method | Band | Cue4 acc | Cue4 prec (cov) | Cue6 acc | Cue6 prec (cov) | ±16 c4/c6 |
|--------|------|----------|-----------------|----------|-----------------|-----------|
| llm | all | 67.6% (25/37) | 67.6% (100%) | 48.6% (18/37) | 50.0% (97%) | 6/5 |
| llm | bass (<80) | 72.7% (8/11) | 72.7% (100%) | 36.4% (4/11) | 40.0% (91%) | 1/1 |
| llm | dnb (80-100) | 58.3% (7/12) | 58.3% (100%) | 33.3% (4/12) | 33.3% (100%) | 4/3 |
| llm | midtempo (100-115) | 50.0% (1/2) | 50.0% (100%) | 50.0% (1/2) | 50.0% (100%) | 0/0 |
| llm | house (115+) | 75.0% (9/12) | 75.0% (100%) | 75.0% (9/12) | 75.0% (100%) | 1/1 |
| ranker_pct | all | 64.9% (24/37) | 69.7% (89%) | 45.9% (17/37) | 59.1% (59%) | 7/5 |
| ranker_pct | bass (<80) | 72.7% (8/11) | 72.7% (100%) | 36.4% (4/11) | 40.0% (45%) | 1/1 |
| ranker_pct | dnb (80-100) | 50.0% (6/12) | 45.5% (92%) | 33.3% (4/12) | 50.0% (50%) | 5/3 |
| ranker_pct | midtempo (100-115) | 50.0% (1/2) | 100.0% (50%) | 50.0% (1/2) | 100.0% (50%) | 0/0 |
| ranker_pct | house (115+) | 75.0% (9/12) | 90.0% (83%) | 66.7% (8/12) | 70.0% (83%) | 1/1 |
| ranker_nopct | all | 40.5% (15/37) | 61.9% (57%) | 51.4% (19/37) | 66.7% (65%) | 4/4 |
| ranker_nopct | bass (<80) | 54.5% (6/11) | 71.4% (64%) | 45.5% (5/11) | 60.0% (45%) | 1/1 |
| ranker_nopct | dnb (80-100) | 25.0% (3/12) | 50.0% (33%) | 33.3% (4/12) | 50.0% (67%) | 3/3 |
| ranker_nopct | midtempo (100-115) | 0.0% (0/2) | 0.0% (50%) | 50.0% (1/2) | 100.0% (50%) | 0/0 |
| ranker_nopct | house (115+) | 50.0% (6/12) | 66.7% (75%) | 75.0% (9/12) | 80.0% (83%) | 0/0 |
| combined_pct | all | 62.2% (23/37) | 62.2% (100%) | 48.6% (18/37) | 50.0% (97%) | 8/3 |
| combined_pct | bass (<80) | 72.7% (8/11) | 72.7% (100%) | 36.4% (4/11) | 40.0% (91%) | 1/0 |
| combined_pct | dnb (80-100) | 41.7% (5/12) | 41.7% (100%) | 33.3% (4/12) | 33.3% (100%) | 6/3 |
| combined_pct | midtempo (100-115) | 50.0% (1/2) | 50.0% (100%) | 50.0% (1/2) | 50.0% (100%) | 0/0 |
| combined_pct | house (115+) | 75.0% (9/12) | 75.0% (100%) | 75.0% (9/12) | 75.0% (100%) | 1/0 |
| combined_nopct | all | 56.8% (21/37) | 56.8% (100%) | 54.1% (20/37) | 55.6% (97%) | 6/3 |
| combined_nopct | bass (<80) | 63.6% (7/11) | 63.6% (100%) | 45.5% (5/11) | 50.0% (91%) | 1/0 |
| combined_nopct | dnb (80-100) | 58.3% (7/12) | 58.3% (100%) | 33.3% (4/12) | 33.3% (100%) | 4/3 |
| combined_nopct | midtempo (100-115) | 50.0% (1/2) | 50.0% (100%) | 50.0% (1/2) | 50.0% (100%) | 0/0 |
| combined_nopct | house (115+) | 50.0% (6/12) | 50.0% (100%) | 83.3% (10/12) | 83.3% (100%) | 1/0 |

