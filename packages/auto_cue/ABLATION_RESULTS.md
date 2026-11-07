# Ablation Study Results

**Model**: gpt-6.1-terra (medium reasoning)  
**Eval set**: 42 tracks (excluding qa06, qa25, qa32)  
**Gold pool**: v2 cleaned (289 tracks) for few-shot examples  
**Lattice rules**: Corrected 16/32 run-ups (cue3/cue5 can be 16 or 32 beats before drops)

## Summary

| Arm | Cue4 (all) | Cue6 (all) | All 8 | Skip Rate | Cost/track |
|-----|------------|------------|-------|-----------|------------|
| **Baseline** | 47.6% | 42.9% | 7/38 | 9.5% | $0.0033 |
| **+ Fewshot** | 50.0% | 45.2% | 7/40 | 4.8% | $0.0100 |
| **+ Demucs** | 42.9% | 38.1% | 7/35 | 16.7% | $0.0022 |
| **+ Both** | **54.8%** | **45.2%** | 7/39 | 7.1% | $0.0024 |

**Key findings:**
- **+Fewshot+Demucs** achieves the best Cue4 hit rate (54.8%), improving +7.2pp over baseline
- Few-shot examples reduce skip rate (4.8% vs 9.5% baseline) while maintaining accuracy
- Demucs alone increases skip rate (16.7%) without improving accuracy
- All configurations struggle on drum-and-bass tracks (17-33% Cue6 hit rate)

---

## Arm 1: Terra Baseline (no fewshot, no demucs)

### Main Metrics
- **Cue4 (all songs)**: 20/42 = 47.6%
- **Cue6 (all songs)**: 18/42 = 42.9%
- **All 8 correct**: 7/38 (processed)
- **Skip rate**: 4/42 = 9.5%
- **Cost/track**: $0.0033

### Error Analysis (±16/±32)
- Total errors (>1 beat): 155
- ±16 beat errors: 52
- ±32 beat errors: 25
- Other errors: 78
- Cue4 ±16: 7, ±32: 3
- Cue6 ±16: 6, ±32: 0

### Results by BPM Band
| BPM Band | Tracks | Processed | Cue4 | Cue6 |
|----------|--------|-----------|------|------|
| bass (<80) | 11 | 9 | 55% | 36% |
| dnb (80-100) | 12 | 11 | 33% | 17% |
| house (115+) | 12 | 11 | 67% | 75% |
| midtempo (100-115) | 2 | 2 | 0% | 50% |
| unknown | 5 | 5 | 40% | 40% |

---

## Arm 2: + Fewshot (v2 pool)

### Main Metrics
- **Cue4 (all songs)**: 21/42 = 50.0%
- **Cue6 (all songs)**: 19/42 = 45.2%
- **All 8 correct**: 7/40 (processed)
- **Skip rate**: 2/42 = 4.8%
- **Cost/track**: $0.0100

### Error Analysis (±16/±32)
- Total errors (>1 beat): 159
- ±16 beat errors: 56
- ±32 beat errors: 21
- Other errors: 82
- Cue4 ±16: 10, ±32: 2
- Cue6 ±16: 5, ±32: 1

### Results by BPM Band
| BPM Band | Tracks | Processed | Cue4 | Cue6 |
|----------|--------|-----------|------|------|
| bass (<80) | 11 | 9 | 45% | 36% |
| dnb (80-100) | 12 | 12 | 33% | 17% |
| house (115+) | 12 | 12 | 75% | 83% |
| midtempo (100-115) | 2 | 2 | 50% | 50% |
| unknown | 5 | 5 | 40% | 40% |

---

## Arm 3: + Demucs (vocal activity)

### Main Metrics
- **Cue4 (all songs)**: 18/42 = 42.9%
- **Cue6 (all songs)**: 16/42 = 38.1%
- **All 8 correct**: 7/35 (processed)
- **Skip rate**: 7/42 = 16.7%
- **Cost/track**: $0.0022

### Error Analysis (±16/±32)
- Total errors (>1 beat): 143
- ±16 beat errors: 53
- ±32 beat errors: 19
- Other errors: 71
- Cue4 ±16: 7, ±32: 3
- Cue6 ±16: 6, ±32: 0

### Results by BPM Band
| BPM Band | Tracks | Processed | Cue4 | Cue6 |
|----------|--------|-----------|------|------|
| bass (<80) | 11 | 8 | 45% | 27% |
| dnb (80-100) | 12 | 11 | 33% | 17% |
| house (115+) | 12 | 10 | 58% | 67% |
| midtempo (100-115) | 2 | 2 | 0% | 50% |
| unknown | 5 | 4 | 40% | 40% |

---

## Arm 4: + Fewshot + Demucs (everything)

### Main Metrics
- **Cue4 (all songs)**: 23/42 = 54.8%
- **Cue6 (all songs)**: 19/42 = 45.2%
- **All 8 correct**: 7/39 (processed)
- **Skip rate**: 3/42 = 7.1%
- **Cost/track**: $0.0024

### Error Analysis (±16/±32)
- Total errors (>1 beat): 155
- ±16 beat errors: 61
- ±32 beat errors: 17
- Other errors: 77
- Cue4 ±16: 10, ±32: 1
- Cue6 ±16: 6, ±32: 0

### Results by BPM Band
| BPM Band | Tracks | Processed | Cue4 | Cue6 |
|----------|--------|-----------|------|------|
| bass (<80) | 11 | 10 | 64% | 36% |
| dnb (80-100) | 12 | 12 | 33% | 17% |
| house (115+) | 12 | 12 | 75% | 83% |
| midtempo (100-115) | 2 | 1 | 50% | 50% |
| unknown | 5 | 4 | 40% | 40% |

---

## Analysis

### Best Configuration: +Fewshot+Demucs
The combined approach achieves the best drop detection:
- **Cue4: 54.8%** (+7.2pp vs baseline)
- **Cue6: 45.2%** (+2.3pp vs baseline)
- Moderate skip rate (7.1%)

### BPM Band Performance
Performance varies significantly by genre/tempo:
- **House (115+ BPM)**: Best performance (75-83% Cue4, 75-83% Cue6)
- **Bass (<80 BPM)**: Mid-range (45-64% Cue4, 27-36% Cue6)
- **DnB (80-100 BPM)**: Consistently poor (33% Cue4, 17% Cue6) — likely due to complex/non-standard drop structures

### Error Patterns
- ±16 beat errors dominate (~35-40% of all errors)
- ±32 beat errors are less common (~12-16% of all errors)
- Cue4 has more ±16 errors than Cue6 (10 vs 6 in best arm)
- Suggests model sometimes picks adjacent phrase boundaries

### Cost Analysis
- Baseline: $0.0033/track (cheapest)
- +Fewshot: $0.0100/track (3x baseline due to longer prompts)
- +Demucs: $0.0022/track (lower because of higher skip rate)
- +Both: $0.0024/track (similar to demucs-only)

### Recommendations
1. Use **+Fewshot+Demucs** for best accuracy
2. Consider specialized handling for DnB tracks
3. The ±16 beat error pattern suggests the model sometimes identifies run-ups instead of drops
4. House music is well-handled; focus improvement efforts on bass/DnB
