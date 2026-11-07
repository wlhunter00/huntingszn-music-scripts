# Updated Evaluation Results

**Date:** November 3, 2026
**Model:** gpt-6.1-terra (reasoning_effort=medium)
**Config:** fewshot (v2 pool) + demucs

## Summary

| Metric | Value | Target |
|--------|-------|--------|
| Total Tracks | 42 | - |
| Processed | 40 | - |
| Abstained | 2 (4.8%) | <=35% |
| **Cue4 Precision** | **55.0%** | >=90% |
| **Cue6 Precision** | **45.0%** | >=90% |
| API Cost | $0.49 total ($0.012/track) | - |

## Per-Cue Metrics (Precision / Coverage / Accuracy)

| Cue | Precision | Coverage | Accuracy | Emitted/Correct/Gold |
|-----|-----------|----------|----------|---------------------|
| 1 | 75% | 95% | 71% | 40/30/42 |
| 2 | 52% | 95% | 50% | 40/21/42 |
| 3 | 52% | 95% | 50% | 40/21/42 |
| **4** | **55%** | 95% | 52% | 40/22/42 |
| 5 | 47% | 90% | 43% | 38/18/42 |
| **6** | **45%** | 95% | 43% | 40/18/42 |
| 7 | 35% | 95% | 33% | 40/14/42 |
| 8 | 40% | 95% | 38% | 40/16/42 |

## Candidate Recall (Gold Drop in Candidate Set)

| Cue | Recall | Details |
|-----|--------|---------|
| Cue4 | 62% | 23/37 tracks |
| Cue6 | 41% | 15/37 tracks |

**Improvement from baseline:**
- Cue4: ~37% → 62% (+25pp)
- Cue6: ~10% → 41% (+31pp)

## Error Analysis

| Error Type | Count | % of Total |
|------------|-------|------------|
| ±16 beats | 58 | 37% |
| ±32 beats | 16 | 10% |
| Other | 84 | 53% |
| **Total** | **158** | - |

**Drop cues specifically:**
- Cue4: ±16 errors=10, ±32 errors=1
- Cue6: ±16 errors=6, ±32 errors=1

## Results by BPM Band

| BPM Band | Tracks | Processed | Cue4 | Cue6 |
|----------|--------|-----------|------|------|
| bass (<80) | 11 | 10 | 55% | 45% |
| dnb (80-100) | 12 | 12 | **33%** | **17%** |
| midtempo (100-115) | 2 | 2 | 50% | 50% |
| house (115+) | 12 | 12 | **75%** | **67%** |
| unknown | 5 | 4 | 40% | 40% |

## Key Findings

### What's Working
1. **Per-cue abstention implemented** - Coverage is 90-95% across all cues
2. **Candidate recall improved significantly** - Especially cue6 from ~10% to 41%
3. **House tracks perform well** - 75%/67% accuracy for cue4/cue6
4. **Low abstention rate** - 4.8% (well under 35% limit)

### What Needs Work
1. **DnB tracks perform poorly** - Only 33%/17% accuracy
   - Many ±16 beat errors suggest grid alignment issues
   - Faster BPM may cause different phrase structures
2. **Cue6 candidate recall still low** - 41% vs 62% for cue4
   - Need better detection of "last drop" in second half
3. **Grid off-lattice issues** - Many errors at exactly ±16 beats

### Recommended Next Steps (Priority Order)
1. **Investigate dnb band** - Why are 80-100 BPM tracks so much worse?
2. **Improve second-half drop detection** - Boost cue6 candidate recall
3. **Grid alignment fixes** - Address the ±16 beat systematic errors
4. **Consider confidence thresholding** - Precision could be improved by being more selective (trading coverage)
