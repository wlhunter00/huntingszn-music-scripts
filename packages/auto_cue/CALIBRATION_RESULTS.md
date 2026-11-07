# Calibrated Confidence Results

**Date:** November 3, 2026
**Model:** gpt-6.1-terra (3 samples for self-consistency)
**Tracks:** 37 eval tracks

## Summary

Attempted to implement calibrated per-cue abstention using code-based signals:
- Self-consistency across 3 model samples
- Code agreement (is prediction in candidate list?)
- Margin (gap between best and second-best candidate)
- Kick slam-in strength
- Lattice alignment
- ±16 ambiguity

**Key Finding:** Cannot achieve 90% precision with current signals.

## Precision/Coverage Curves

### CUE4

| Threshold | Precision | Coverage |
|-----------|-----------|----------|
| 0.50 | 61.3% | 83.8% |
| 0.70 | 68.2% | 59.5% |
| 0.80 | 78.6% | 37.8% |
| 1.00 | **85.7%** | 18.9% |

**Max precision: 85.7%** (short of 90% target)

### CUE6

| Threshold | Precision | Coverage |
|-----------|-----------|----------|
| 0.35 | 46.7% | 81.1% |
| 0.45 | **50.0%** | 70.3% |
| 0.65 | 47.1% | 45.9% |
| 1.00 | 20.0% | 13.5% |

**CRITICAL:** Cue6 precision DECREASES at higher thresholds!
Calibration is inverted - high confidence predictions are LESS likely to be correct.

## Root Cause Analysis

### Why Self-Consistency Doesn't Help
- Model samples are highly correlated (SC ≈ 1.00 for most predictions)
- When the model is wrong, all 3 samples are wrong the same way
- ±16 beat errors are systematic across samples

### Why Code Confidence Doesn't Help
- Wrong predictions are often in the candidate list
- Multiple candidates at similar scores
- Best code candidate ≠ gold cue in many cases

### Example Problem Cases

| Track | Cue | Pred | Gold | Error | Combined Conf |
|-------|-----|------|------|-------|---------------|
| qa05 | 4 | 48 | 68 | 20 | **0.75** |
| qa05 | 6 | 128 | 152 | 24 | **1.00** |
| qa21 | 4 | 80 | 160 | 80 | 0.70 |
| qa24 | 4 | 128 | 184 | 56 | **1.00** |
| qa36 | 4 | 192 | 84 | 108 | 0.67 |

## Conclusions

1. **90% precision is not achievable** with current signals
2. **Cue6 is fundamentally harder** - calibration is inverted
3. **Model accuracy (~55%) is the limiting factor**, not calibration
4. **±16 beat errors are systematic** and confident

## Recommended Next Steps

1. **Accept lower precision target** (80% may be achievable for cue4)
2. **Focus on model accuracy** - improve the underlying 55% accuracy first
3. **Consider rule-based abstention** - abstain on specific patterns (dnb tracks, ±16 ambiguity)
4. **Human-in-the-loop** - for high-stakes cues, require human verification
