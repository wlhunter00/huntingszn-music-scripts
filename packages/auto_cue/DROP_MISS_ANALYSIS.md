# Drop Miss Analysis (Cue 4 and Cue 6)

**Model**: gpt-6.1-terra (medium reasoning)
**Configuration**: + fewshot (v2 pool) + demucs
**Eval set**: 42 tracks (excluding qa06, qa25, qa32)

## Overall Performance

- Total tracks: 37
- Processed: 33 (abstained: 4)
- **Cue4 correct**: 20/37 = 54.1%
- **Cue6 correct**: 16/37 = 43.2%

## Cause Classification

### Cue 4 Misses

| Cause | Count | % of Misses |
|-------|-------|-------------|
| candidate_recall | 6 | 35% |
| skipped | 4 | 24% |
| grid_off_lattice | 3 | 18% |
| fakeout_runup | 2 | 12% |
| gold_questionable | 1 | 6% |
| fakeout_post | 1 | 6% |

### Cue 6 Misses

| Cause | Count | % of Misses |
|-------|-------|-------------|
| candidate_recall | 8 | 38% |
| grid_off_lattice | 7 | 33% |
| skipped | 4 | 19% |
| wrong_drop | 1 | 5% |
| fakeout_post | 1 | 5% |

## Candidate Recall

- **Cue4**: Gold in candidates for 5/17 misses = 29% recall
- **Cue6**: Gold in candidates for 2/21 misses = 10% recall

*When gold is in candidates, the issue is model judgment. When gold is NOT in candidates, feature/recall failed.*

## Per-Track Miss Details

### Cue 4 Misses

| Track | BPM Band | Gold | Pred | Offset | Cause | In Candidates | Gold Score | Pred Score |
|-------|----------|------|------|--------|-------|---------------|------------|------------|
| qa01.mp3 | bass (<80) | 96 | 80 | -16 | fakeout_runup | ✓ | 7.2 | 0.0 |
| qa05.mp3 | bass (<80) | 68 | 48 | -20 | grid_off_lattice | ✗ | 0.0 | 10.0 |
| qa07.mp3 | bass (<80) | 112 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa09.mp3 | bass (<80) | 48 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa10.mp3 | bass (<80) | 72 | 80 | +8 | grid_off_lattice | ✗ | 6.2 | 6.2 |
| qa12.mp3 | dnb (80-100) | 64 | 48 | -16 | fakeout_runup | ✓ | 8.7 | 8.7 |
| qa14.mp3 | dnb (80-100) | 80 | 64 | -16 | candidate_recall | ✗ | 7.0 | 7.0 |
| qa15.mp3 | dnb (80-100) | 96 | 80 | -16 | candidate_recall | ✗ | 5.2 | 5.2 |
| qa17.mp3 | dnb (80-100) | 64 | -1 | +0 | skipped | ✓ | 0.0 | 0.0 |
| qa21.mp3 | dnb (80-100) | 160 | 80 | -80 | gold_questionable | ✓ | 0.0 | 7.3 |
| qa22.mp3 | dnb (80-100) | 80 | 64 | -16 | candidate_recall | ✗ | 5.9 | 5.9 |
| qa23.mp3 | dnb (80-100) | 80 | 64 | -16 | candidate_recall | ✗ | 8.3 | 8.3 |
| qa24.mp3 | house (115+) | 184 | 128 | -56 | grid_off_lattice | ✗ | 0.0 | 11.0 |
| qa27.mp3 | house (115+) | 208 | 112 | -96 | candidate_recall | ✗ | 6.9 | 4.0 |
| qa31.mp3 | house (115+) | 128 | 144 | +16 | fakeout_post | ✓ | 0.0 | 6.3 |
| qa36.mp3 | midtempo (100-115) | 84 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa38.mp3 | dnb (80-100) | 112 | 128 | +16 | candidate_recall | ✗ | 6.3 | 5.2 |

### Cue 6 Misses

| Track | BPM Band | Gold | Pred | Offset | Cause | In Candidates | Gold Score | Pred Score |
|-------|----------|------|------|--------|-------|---------------|------------|------------|
| qa01.mp3 | bass (<80) | 208 | 192 | -16 | candidate_recall | ✗ | 6.1 | 6.1 |
| qa03.mp3 | bass (<80) | 228 | 192 | -36 | grid_off_lattice | ✗ | 5.8 | 11.9 |
| qa05.mp3 | bass (<80) | 152 | 128 | -24 | grid_off_lattice | ✗ | 7.0 | 7.0 |
| qa07.mp3 | bass (<80) | 248 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa09.mp3 | bass (<80) | 80 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa10.mp3 | bass (<80) | 200 | 192 | -8 | grid_off_lattice | ✗ | 4.3 | 4.3 |
| qa11.mp3 | bass (<80) | 228 | 224 | -4 | grid_off_lattice | ✗ | 6.3 | 6.3 |
| qa12.mp3 | dnb (80-100) | 176 | 160 | -16 | candidate_recall | ✗ | 3.4 | 3.4 |
| qa14.mp3 | dnb (80-100) | 208 | 192 | -16 | candidate_recall | ✗ | 7.2 | 7.2 |
| qa15.mp3 | dnb (80-100) | 192 | 176 | -16 | candidate_recall | ✗ | 4.0 | 4.0 |
| qa17.mp3 | dnb (80-100) | 196 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa19.mp3 | dnb (80-100) | 168 | 160 | -8 | grid_off_lattice | ✗ | 3.8 | 3.8 |
| qa20.mp3 | dnb (80-100) | 196 | 192 | -4 | grid_off_lattice | ✗ | 6.5 | 6.5 |
| qa21.mp3 | dnb (80-100) | 224 | 272 | +48 | candidate_recall | ✗ | 0.0 | 0.0 |
| qa22.mp3 | dnb (80-100) | 240 | 224 | -16 | candidate_recall | ✗ | 7.2 | 7.2 |
| qa23.mp3 | dnb (80-100) | 208 | 192 | -16 | candidate_recall | ✗ | 8.2 | 8.2 |
| qa31.mp3 | house (115+) | 240 | 304 | +64 | candidate_recall | ✗ | 4.4 | 0.0 |
| qa35.mp3 | house (115+) | 224 | 400 | +176 | wrong_drop | ✓ | 4.7 | 6.3 |
| qa36.mp3 | midtempo (100-115) | 212 | -1 | +0 | skipped | ✗ | 0.0 | 0.0 |
| qa38.mp3 | dnb (80-100) | 248 | 256 | +8 | grid_off_lattice | ✗ | 3.7 | 6.6 |
| qa39.mp3 | house (115+) | 384 | 400 | +16 | fakeout_post | ✓ | 3.0 | 6.0 |

## Feature Comparison (Gold vs Predicted)

Representative examples showing feature values at gold drop vs model's pick:


### Fakeout Runup Examples

**qa01.mp3** - Gold beat 96, Predicted beat 80

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 7.2 | 0.0 | -7.2 |
| Bass Jump | 12.9 | -10.7 | -23.6 |
| Contrast | 5.4 | 6.0 | +0.6 |
| Novelty | 0.9 | 0.9 | -0.1 |
| Kick Density | 0.1 | 0.2 | +0.0 |
| Post Sustain | -17.4 | 12.9 | +30.3 |
| RMS dB | -9.4 | -14.1 | -4.7 |

**qa12.mp3** - Gold beat 63, Predicted beat 48

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 8.7 | 8.7 | +0.0 |
| Bass Jump | 13.4 | 13.4 | +0.0 |
| Contrast | 3.0 | 3.0 | +0.0 |
| Novelty | 0.7 | 0.7 | +0.0 |
| Kick Density | 0.1 | 0.1 | +0.0 |
| Post Sustain | 2.6 | 2.6 | +0.0 |
| RMS dB | -11.4 | -11.4 | +0.0 |


### Fakeout Post Examples

**qa31.mp3** - Gold beat 127, Predicted beat 144

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 0.0 | 6.3 | +6.3 |
| Bass Jump | -28.0 | 5.8 | +33.8 |
| Contrast | 0.3 | 6.4 | +6.1 |
| Novelty | 0.7 | 0.7 | +0.1 |
| Kick Density | 0.1 | 0.1 | +0.0 |
| Post Sustain | 5.8 | 11.7 | +5.9 |
| RMS dB | -19.4 | -17.0 | +2.4 |

**qa39.mp3** - Gold beat 383, Predicted beat 400

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 3.0 | 6.0 | +2.9 |
| Bass Jump | -1.7 | 5.8 | +7.5 |
| Contrast | 4.0 | 5.1 | +1.1 |
| Novelty | 0.9 | 0.8 | -0.2 |
| Kick Density | 0.1 | 0.1 | +0.0 |
| Post Sustain | 5.8 | 2.6 | -3.2 |
| RMS dB | -9.3 | -9.1 | +0.2 |


### Candidate Recall Examples

**qa14.mp3** - Gold beat 80, Predicted beat 64

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 7.0 | 7.0 | +0.0 |
| Bass Jump | 9.6 | 9.6 | +0.0 |
| Contrast | 3.2 | 3.2 | +0.0 |
| Novelty | 0.7 | 0.7 | +0.0 |
| Kick Density | 0.1 | 0.1 | +0.0 |
| Post Sustain | 2.6 | 2.6 | +0.0 |
| RMS dB | -10.6 | -10.6 | +0.0 |

**qa15.mp3** - Gold beat 95, Predicted beat 80

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 5.2 | 5.2 | +0.0 |
| Bass Jump | 2.4 | 2.4 | +0.0 |
| Contrast | 4.5 | 4.5 | +0.0 |
| Novelty | 1.0 | 1.0 | +0.0 |
| Kick Density | 0.1 | 0.1 | +0.0 |
| Post Sustain | 5.4 | 5.4 | +0.0 |
| RMS dB | -11.9 | -11.9 | +0.0 |

**qa22.mp3** - Gold beat 80, Predicted beat 64

| Feature | Gold | Pred | Delta |
|---------|------|------|-------|
| Drop Score | 5.9 | 5.9 | +0.0 |
| Bass Jump | 5.7 | 5.7 | +0.0 |
| Contrast | 2.9 | 2.9 | +0.0 |
| Novelty | 0.9 | 0.9 | +0.0 |
| Kick Density | 0.2 | 0.2 | +0.0 |
| Post Sustain | 1.9 | 1.9 | +0.0 |
| RMS dB | -11.5 | -11.5 | +0.0 |

## Would Simple Rules Beat the Model?

### Rule: Pick highest drop_score on lattice

- **Cue4**: Would fix 1/5 judgment errors = 20%
- **Cue6**: Would fix 0/2 judgment errors = 0%

Examples where gold score > pred score:

- **qa01.mp3**: Gold beat 96 (score=7.2) vs Pred beat 80 (score=0.0)

## Misses by BPM Band

| BPM Band | Tracks | Cue4 Misses | Cue6 Misses |
|----------|--------|-------------|-------------|
| bass (<80) | 11 | 5 | 7 |
| dnb (80-100) | 12 | 8 | 10 |
| midtempo (100-115) | 2 | 1 | 1 |
| house (115+) | 12 | 3 | 3 |

## Top 3 Concrete Fixes (Ranked by Expected Gain)

### Fix #1: Improve candidate recall (feature scoring)

**Misses potentially fixed**: 14 (37% of all misses)

**Implementation**: Lower drop_score threshold OR add more candidate positions. Currently gold drops are not even surfaced as candidates in these cases.

### Fix #2: Support non-16-beat lattice drops

**Misses potentially fixed**: 10 (26% of all misses)

**Implementation**: Some tracks have drops on beats like 68, 72, 152 that are not on 16-beat boundaries. Consider adding 8-beat lattice or flexible lattice detection.

### Fix #3: Fix validation/abstention logic

**Misses potentially fixed**: 8 (21% of all misses)

**Implementation**: Model abstains due to validation errors (cue4>cue5, cue7>cue5). Either relax these rules or improve candidate selection to avoid impossible configurations.

## Summary

The main failure modes are:

1. **candidate_recall**: 14 misses (37%)
1. **grid_off_lattice**: 10 misses (26%)
1. **skipped**: 8 misses (21%)
1. **fakeout_runup**: 2 misses (5%)
1. **fakeout_post**: 2 misses (5%)
1. **gold_questionable**: 1 misses (3%)
1. **wrong_drop**: 1 misses (3%)