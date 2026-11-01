# Blind Evaluation Results

Mode: Rule-based
Model: gpt-4o-mini

## Per-Track Results

| Track | Cue 1 | Cue 2 | Cue 3 | Cue 4 | Cue 5 | Cue 6 | Cue 7 | Cue 8 | Status |
|-------|-------|-------|-------|-------|-------|-------|-------|-------|--------|
| Britney Spears - Toxic (Levity | ✓ 0.0 | ✗ 16.0 | ✗ 12.0 | ✗ 12.0 | ✗ 56.0 | ✗ 56.0 | ✗ 52.0 | ✗ 20.0 | partial |
| Don’t Stop the Music (NGHTMRE  | — | — | — | — | — | — | — | — | ABSTAIN |
| FLUX PAVILION - EMOTIONAL (UNN | — | — | — | — | — | — | — | — | ABSTAIN |
| Justin Timberlake - What Goes  | ✗ 16.0 | ✗ 16.0 | ✗ 80.0 | ✗ 80.0 | ✓ 0.0 | ✓ 0.0 | ✗ 32.0 | ✗ 32.0 | partial |
| These Words - Extended Mix.mp3 | ✓ 0.0 | ✗ 32.0 | ✗ 96.0 | ✗ 96.0 | ✗ 160.0 | ✗ 64.0 | ✗ 32.0 | ✓ 0.0 | partial |

### Abstain Decisions

- **Don’t Stop the Music (NGHTMRE Remix) [DnB].mp3**: Abstaining: cue4 has weak score (-5.1); cue4 at 64 has -54% of max drop score; cue6 at 224 has 47% of max drop score
- **FLUX PAVILION - EMOTIONAL (UNNEVN REMIX) 15.mp3**: Abstaining: cue4 has weak score (0.3); cue4 at 64 has 4% of max drop score

## Summary

```
Total tracks: 5
Processed: 3
Abstained: 2 (40.0%)

Per-cue accuracy (within 1.0 beat):
  Cue 1: 2/3 = 66.7% (mean error: 5.3 beats)
  Cue 2: 0/3 = 0.0% (mean error: 21.3 beats)
  Cue 3: 0/3 = 0.0% (mean error: 62.7 beats)
  Cue 4: 0/3 = 0.0% (mean error: 62.7 beats)
  Cue 5: 1/3 = 33.3% (mean error: 72.0 beats)
  Cue 6: 1/3 = 33.3% (mean error: 40.0 beats)
  Cue 7: 0/3 = 0.0% (mean error: 38.7 beats)
  Cue 8: 1/3 = 33.3% (mean error: 17.3 beats)

All 8 correct: 0/3
Cue 4 accuracy: 0.0% (spec: >= 85%)
Cue 6 accuracy: 33.3% (spec: >= 85%)
Abstain rate: 40.0% (spec: <= 35%)
```
