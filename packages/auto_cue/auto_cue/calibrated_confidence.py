"""Calibrated per-cue confidence from code signals.

The model's self-reported confidence is uncalibrated (reports 0.9 while 100+ beats off).
This module computes calibrated confidence from objective signals:

1. Margin: Gap between top and second drop candidate scores
2. Agreement across zooms: Multi-scale analysis (8/16/32 beat phrases)
3. Kick slam-in strength: Strong evidence for drop
4. Lattice alignment: Whether pick is on 16/32-beat grid
5. Code agreement: Whether model's pick matches strongest code-detected candidate
6. ±16 ambiguity: Strong rival exactly 16 beats away = blank

Thresholds are fit on gold pool (not eval set) to avoid overfitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from auto_cue.ranker import phrase_at_beat

if TYPE_CHECKING:
    from auto_cue.features import PhraseFeatures, TrackFeatures


@dataclass
class CueConfidenceSignals:
    """Signals used to compute calibrated confidence for a cue."""
    cue_slot: int  # 4 or 6
    predicted_beat: int | None

    # Signal values (all normalized to 0-1 or interpretable range)
    margin: float = 0.0  # Score gap to second-best candidate
    zoom_agreement: float = 0.0  # Agreement across 8/16/32 phrase sizes
    kick_slam_strength: float = 0.0  # Kick onset strength at predicted beat
    on_lattice: bool = True  # Whether pick is on 16-beat grid
    code_agreement: bool = True  # Whether model pick matches code's best candidate
    code_rank_score: float = 1.0  # How good is predicted vs best candidate (0-1)
    rival_16_strength: float = 0.0  # Strength of candidate exactly ±16 beats away
    is_candidate: bool = True  # Whether predicted beat is in code's candidate list

    # Derived calibrated confidence
    calibrated_confidence: float = 0.0
    abstain_reasons: list[str] = field(default_factory=list)


@dataclass
class CalibrationResult:
    """Result of calibrated confidence computation."""
    cue4_signals: CueConfidenceSignals | None = None
    cue6_signals: CueConfidenceSignals | None = None

    # Final decisions
    cue4_confident: bool = True
    cue6_confident: bool = True

    # Confidence scores (0-1, calibrated)
    cue4_confidence: float = 1.0
    cue6_confidence: float = 1.0


def _get_phrase_at_beat(
    phrases: list[PhraseFeatures],
    beat: int,
) -> PhraseFeatures | None:
    """Find a window starting at the predicted beat on its own phase."""
    for p in phrases:
        if p.beat_start == beat:
            return p
    return None


def _get_drop_score_at_beat(features: TrackFeatures, beat: int) -> float:
    """Get the drop score at a specific beat position."""
    # Check 32-beat phrases first
    for p in features.phrases_32:
        if p.beat_start == beat:
            return p.drop_score
    # Check 16-beat phrases
    for p in features.phrases_16:
        if p.beat_start == beat:
            return p.drop_score
    return 0.0


def _compute_margin(
    features: TrackFeatures,
    predicted_beat: int | None,
    is_cue6: bool = False,
) -> float:
    """Compute margin between predicted beat's score and second-best candidate.

    Higher margin = more confident.
    """
    if predicted_beat is None:
        return 0.0

    # Get all candidate scores
    candidate_scores: list[tuple[int, float]] = []
    for p in features.phrases_32:
        if p.is_drop_candidate:
            candidate_scores.append((p.beat_start, p.drop_score))
    for p in features.phrases_16:
        if p.is_drop_candidate and p.beat_start % 32 != 0:
            candidate_scores.append((p.beat_start, p.drop_score))

    if not candidate_scores:
        return 0.0

    # For cue6, focus on second half
    half_track = features.total_beats // 2
    if is_cue6:
        candidate_scores = [(b, s) for b, s in candidate_scores if b >= half_track * 0.6]
    else:
        candidate_scores = [(b, s) for b, s in candidate_scores if b < half_track * 1.4]

    if not candidate_scores:
        return 0.0

    # Find predicted beat's score
    predicted_score = _get_drop_score_at_beat(features, predicted_beat)

    # Find best other candidate
    other_scores = [s for b, s in candidate_scores if abs(b - predicted_beat) > 8]
    if not other_scores:
        return 1.0  # No rivals = max margin

    second_best = max(other_scores)
    margin = predicted_score - second_best

    # Normalize: typical margins range from -2 to +4
    return float(np.clip(margin / 3.0, 0.0, 1.0))


def _compute_zoom_agreement(
    features: TrackFeatures,
    predicted_beat: int | None,
) -> float:
    """Check if the predicted beat is a strong candidate across all zoom levels.

    Returns 0-1 where 1 = strong candidate at all scales.
    """
    if predicted_beat is None:
        return 0.0

    agreement = 0.0
    checks = 0

    # Check 8-beat phrases
    p = _get_phrase_at_beat(features.phrases_8, predicted_beat)
    if p is not None:
        # Is this phrase high-energy relative to neighbors?
        agreement += 0.5 if p.delta_kick > 0 else 0.0
        agreement += 0.5 if p.delta_low > 3.0 else 0.0
        checks += 1

    # Check 16-beat phrases
    p = _get_phrase_at_beat(features.phrases_16, predicted_beat)
    if p is not None:
        agreement += 0.5 if p.delta_kick > 0.05 else 0.0
        agreement += 0.5 if p.drop_score > 1.0 else 0.0
        checks += 1

    # Check 32-beat phrases
    p = _get_phrase_at_beat(features.phrases_32, predicted_beat)
    if p is not None:
        agreement += 0.5 if p.is_drop_candidate else 0.0
        agreement += 0.5 if p.drop_score > 1.5 else 0.0
        checks += 1

    if checks == 0:
        return 0.0

    return agreement / (checks * 1.0)  # Normalize to 0-1


def _compute_kick_slam_strength(
    features: TrackFeatures,
    predicted_beat: int | None,
) -> float:
    """Compute kick slam-in strength at the predicted beat.

    Strong kick slam = confident drop detection.
    """
    if predicted_beat is None:
        return 0.0

    # Find the phrase at this beat
    phrase = _get_phrase_at_beat(features.phrases_16, predicted_beat)
    if phrase is None:
        return 0.0

    # Kick slam is delta_kick (kick density change)
    kick_slam = max(0, phrase.delta_kick)

    # Also consider delta_low (bass jump)
    bass_jump = max(0, phrase.delta_low / 10.0)  # Normalize

    # Combine
    strength = kick_slam * 3.0 + bass_jump

    return float(np.clip(strength, 0.0, 1.0))


def _check_lattice_alignment(
    predicted_beat: int | None,
    lattice_size: int = 16,
    phase: int = 0,
) -> bool:
    """Check if predicted beat is on the expected lattice."""
    if predicted_beat is None:
        return True  # N/A
    return (predicted_beat - phase) % lattice_size == 0


def _check_code_agreement(
    features: TrackFeatures,
    predicted_beat: int | None,
    is_cue6: bool = False,
) -> tuple[bool, float]:
    """Check if model's pick matches the strongest code-detected candidate.

    Returns:
        (agrees, rank_score) where rank_score is 1.0 if best, <1.0 if not
    """
    if predicted_beat is None:
        return False, 0.0  # No prediction = no agreement

    # Check against drop_candidates list (includes both 32-beat and 16-beat)
    if not features.drop_candidates:
        return False, 0.0

    # Get candidate scores from drop_candidates
    half_track = features.total_beats // 2

    candidate_scores: list[tuple[int, float]] = []

    # Build score map from all phrases
    score_map: dict[int, float] = {}
    for p in features.phrases_32:
        score_map[p.beat_start] = p.drop_score
    for p in features.phrases_16:
        if p.beat_start not in score_map or p.drop_score > score_map[p.beat_start]:
            score_map[p.beat_start] = p.drop_score

    # Filter to relevant region
    for beat in features.drop_candidates:
        score = score_map.get(beat, 0.0)
        if is_cue6 and beat >= half_track * 0.4:
            candidate_scores.append((beat, score))
        elif not is_cue6 and beat <= half_track * 1.6:
            candidate_scores.append((beat, score))

    if not candidate_scores:
        # Fallback: use all drop candidates
        for beat in features.drop_candidates:
            score = score_map.get(beat, 0.0)
            candidate_scores.append((beat, score))

    if not candidate_scores:
        return False, 0.0

    # Find best candidate and predicted candidate's score
    best_beat, best_score = max(candidate_scores, key=lambda x: x[1])

    # Find the predicted beat's score (if it's near a candidate)
    pred_score = 0.0
    pred_is_candidate = False
    for beat, score in candidate_scores:
        if abs(beat - predicted_beat) <= 16:  # Allow some tolerance (16 beats)
            pred_score = max(pred_score, score)  # Take best score nearby
            pred_is_candidate = True

    # Also check if predicted beat is directly in score_map
    if not pred_is_candidate:
        # Check nearby phrases
        for phrase_beat, score in score_map.items():
            if abs(phrase_beat - predicted_beat) <= 8:
                pred_score = max(pred_score, score)
                pred_is_candidate = True
                break

    # If predicted beat isn't even near a candidate, lower confidence but not zero
    if not pred_is_candidate:
        # Give partial credit if prediction is on the beat grid
        if predicted_beat % 16 == 0:
            return False, 0.2
        return False, 0.0

    # Check if model's pick is the best or close to it
    agrees = abs(predicted_beat - best_beat) <= 16

    # Rank score: how close is predicted score to best score
    if best_score > 0:
        rank_score = pred_score / best_score
    else:
        rank_score = 0.5

    return agrees, float(np.clip(rank_score, 0.0, 1.0))


def _compute_rival_16_strength(
    features: TrackFeatures,
    predicted_beat: int | None,
) -> float:
    """Check if there's a strong rival exactly ±16 beats away.

    High rival strength = should abstain (±16 ambiguity).
    """
    if predicted_beat is None:
        return 0.0

    predicted_score = _get_drop_score_at_beat(features, predicted_beat)

    # Check ±16 positions
    rival_beats = [predicted_beat - 16, predicted_beat + 16]
    rival_scores = []

    for rival_beat in rival_beats:
        if 0 <= rival_beat < features.total_beats:
            rival_score = _get_drop_score_at_beat(features, rival_beat)
            if rival_score > 0:
                rival_scores.append(rival_score)

    if not rival_scores:
        return 0.0

    max_rival = max(rival_scores)

    # If rival is nearly as strong as prediction, high ambiguity
    if predicted_score > 0:
        ratio = max_rival / predicted_score
    else:
        ratio = max_rival  # Predicted has no score but rival does

    # Ratio near 1.0 = high ambiguity
    return float(np.clip(ratio, 0.0, 1.0))


def compute_cue_confidence_signals(
    features: TrackFeatures,
    predicted_beat: int | None,
    cue_slot: int,
) -> CueConfidenceSignals:
    """Compute all confidence signals for a single cue prediction.

    Args:
        features: Track features
        predicted_beat: Predicted beat position (or None)
        cue_slot: 4 or 6

    Returns:
        CueConfidenceSignals with all signals computed
    """
    is_cue6 = cue_slot == 6

    signals = CueConfidenceSignals(
        cue_slot=cue_slot,
        predicted_beat=predicted_beat,
    )

    if predicted_beat is None:
        signals.abstain_reasons.append("model returned null")
        signals.calibrated_confidence = 0.0
        return signals

    # Compute all signals
    signals.margin = _compute_margin(features, predicted_beat, is_cue6)
    signals.zoom_agreement = _compute_zoom_agreement(features, predicted_beat)
    signals.kick_slam_strength = _compute_kick_slam_strength(features, predicted_beat)
    phrase = phrase_at_beat(features, predicted_beat)
    phase = phrase.beat_start % 16 if phrase is not None else features.phrase_phase
    signals.on_lattice = _check_lattice_alignment(predicted_beat, 32 if is_cue6 else 16, phase)
    code_agrees, code_rank = _check_code_agreement(features, predicted_beat, is_cue6)
    signals.code_agreement = code_agrees
    signals.code_rank_score = code_rank
    signals.is_candidate = code_rank > 0.1  # Predicted beat is near a candidate
    signals.rival_16_strength = _compute_rival_16_strength(features, predicted_beat)

    # Build abstain reasons
    if signals.code_rank_score < 0.3:
        signals.abstain_reasons.append(f"weak candidate rank ({signals.code_rank_score:.2f})")
    if signals.margin < 0.15:
        signals.abstain_reasons.append(f"low margin ({signals.margin:.2f})")
    if signals.zoom_agreement < 0.3:
        signals.abstain_reasons.append(f"poor zoom agreement ({signals.zoom_agreement:.2f})")
    if signals.kick_slam_strength < 0.1:
        signals.abstain_reasons.append(f"weak kick slam ({signals.kick_slam_strength:.2f})")
    if not signals.on_lattice:
        signals.abstain_reasons.append("off-lattice")
    if not signals.code_agreement:
        signals.abstain_reasons.append("code disagrees with model")
    if signals.rival_16_strength > 0.7:
        signals.abstain_reasons.append(f"±16 ambiguity ({signals.rival_16_strength:.2f})")

    # Compute calibrated confidence
    confidence = compute_calibrated_confidence(signals)
    signals.calibrated_confidence = confidence

    return signals


def compute_calibrated_confidence(
    signals: CueConfidenceSignals,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute calibrated confidence from signals.

    Calibration is based on multiple signals:
    - code_rank_score: Is this a high-scoring candidate?
    - margin: Is there a strong second-best candidate?
    - zoom_agreement: Does this look like a drop at multiple scales?
    - kick_slam: Is there a kick slam-in at this point?
    - on_lattice: Is this on the expected 16/32-beat grid?
    - code_agreement: Does this match code's #1 candidate?
    - rival_16: Is there a strong candidate ±16 beats away?

    Args:
        signals: Computed signals
        weights: Optional custom weights

    Returns:
        Calibrated confidence 0-1
    """
    if weights is None:
        # Default weights (balanced for precision/coverage tradeoff)
        weights = {
            "code_rank": 0.30,  # How good is this candidate vs the best?
            "margin": 0.15,    # Gap to second-best
            "zoom_agreement": 0.15,
            "kick_slam": 0.15,
            "on_lattice": 0.05,
            "code_agreement": 0.20,  # Is this the code's #1 pick?
            "rival_16_penalty": -0.20,
        }

    # Start with base score from code_rank
    # This gives partial credit even for non-best candidates
    score = 0.0

    # Code rank - how good is this vs best candidate (0-1)
    score += signals.code_rank_score * weights["code_rank"]

    # Other positive signals
    score += signals.margin * weights["margin"]
    score += signals.zoom_agreement * weights["zoom_agreement"]
    score += signals.kick_slam_strength * weights["kick_slam"]
    score += (1.0 if signals.on_lattice else 0.0) * weights["on_lattice"]
    score += (1.0 if signals.code_agreement else 0.0) * weights["code_agreement"]

    # Penalty for ±16 ambiguity (strong rival = uncertain)
    score += signals.rival_16_strength * weights["rival_16_penalty"]

    # Small base to avoid being overly pessimistic
    base = 0.15

    confidence = base + score
    return float(np.clip(confidence, 0.0, 1.0))


def compute_calibrated_result(
    features: TrackFeatures,
    cue4_beat: int | None,
    cue6_beat: int | None,
    *,
    cue4_threshold: float = 0.5,
    cue6_threshold: float = 0.5,
) -> CalibrationResult:
    """Compute calibrated confidence for both drops.

    Args:
        features: Track features
        cue4_beat: Predicted cue4 beat
        cue6_beat: Predicted cue6 beat
        cue4_threshold: Threshold for cue4 to be confident
        cue6_threshold: Threshold for cue6 to be confident

    Returns:
        CalibrationResult with confidence decisions
    """
    result = CalibrationResult()

    # Compute signals for cue4
    result.cue4_signals = compute_cue_confidence_signals(
        features, cue4_beat, cue_slot=4
    )
    result.cue4_confidence = result.cue4_signals.calibrated_confidence
    result.cue4_confident = result.cue4_confidence >= cue4_threshold

    # Compute signals for cue6
    result.cue6_signals = compute_cue_confidence_signals(
        features, cue6_beat, cue_slot=6
    )
    result.cue6_confidence = result.cue6_signals.calibrated_confidence
    result.cue6_confident = result.cue6_confidence >= cue6_threshold

    return result


def compute_self_consistency_confidence(
    predictions: list[tuple[int | None, int | None]],
    tolerance_beats: int = 16,
) -> tuple[float, float, int | None, int | None]:
    """Compute confidence from self-consistency across multiple model samples.

    Args:
        predictions: List of (cue4_beat, cue6_beat) from multiple samples
        tolerance_beats: Max difference to consider predictions "agreeing"

    Returns:
        (cue4_confidence, cue6_confidence, consensus_cue4, consensus_cue6)
        where confidence = fraction of samples that agree with consensus
    """
    if not predictions:
        return 0.0, 0.0, None, None

    n_samples = len(predictions)

    def find_consensus(beats: list[int | None]) -> tuple[float, int | None]:
        """Find most common beat and confidence."""
        valid_beats = [b for b in beats if b is not None]
        if not valid_beats:
            return 0.0, None

        # Group beats that are within tolerance
        groups: list[list[int]] = []
        for beat in valid_beats:
            found = False
            for group in groups:
                if any(abs(beat - g) <= tolerance_beats for g in group):
                    group.append(beat)
                    found = True
                    break
            if not found:
                groups.append([beat])

        # Find largest group
        if not groups:
            return 0.0, None

        largest = max(groups, key=len)
        consensus = int(np.median(largest))

        # Confidence = fraction agreeing (with None counted as disagreement)
        n_agree = len(largest)
        confidence = n_agree / n_samples

        return confidence, consensus

    cue4_beats = [p[0] for p in predictions]
    cue6_beats = [p[1] for p in predictions]

    cue4_conf, cue4_consensus = find_consensus(cue4_beats)
    cue6_conf, cue6_consensus = find_consensus(cue6_beats)

    return cue4_conf, cue6_conf, cue4_consensus, cue6_consensus


@dataclass
class CalibratedCueResult:
    """Result of applying calibrated confidence with blank propagation."""
    cue1: int | None = None
    cue2: int | None = None
    cue3: int | None = None
    cue4: int | None = None
    cue5: int | None = None
    cue6: int | None = None
    cue7: int | None = None
    cue8: int | None = None

    cue4_confident: bool = False
    cue6_confident: bool = False
    cue4_confidence: float = 0.0
    cue6_confidence: float = 0.0

    blanked_slots: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[int, int]:
        """Return dict of slot -> beat for non-None cues."""
        result = {}
        for i in range(1, 9):
            beat = getattr(self, f"cue{i}")
            if beat is not None:
                result[i - 1] = beat  # Convert to 0-indexed
        return result


def apply_calibrated_thresholds(
    cue_set,  # CueSet from prediction_to_cue_set
    cue4_confidence: float,
    cue6_confidence: float,
    *,
    cue4_threshold: float = 0.5,
    cue6_threshold: float = 0.5,
) -> CalibratedCueResult:
    """Apply calibrated confidence thresholds with blank propagation.

    Blank propagation rules:
    - cue4 blank → cues 1-3 blank (intro lattice depends on cue4)
    - cue6 blank → cue5 blank (run-up depends on cue6)
    - cue6 blank → cue7/8 blank (if anchored on cue6, not mid-song)

    Args:
        cue_set: CueSet from prediction
        cue4_confidence: Calibrated confidence for cue4 (0-1)
        cue6_confidence: Calibrated confidence for cue6 (0-1)
        cue4_threshold: Threshold for cue4 to be confident
        cue6_threshold: Threshold for cue6 to be confident

    Returns:
        CalibratedCueResult with blanks propagated
    """
    result = CalibratedCueResult(
        cue4_confidence=cue4_confidence,
        cue6_confidence=cue6_confidence,
    )

    # Check cue4 confidence
    cue4_confident = cue4_confidence >= cue4_threshold and cue_set.cue4 is not None
    result.cue4_confident = cue4_confident

    if cue4_confident:
        result.cue4 = cue_set.cue4
        result.cue3 = cue_set.cue3
        result.cue2 = cue_set.cue2
        result.cue1 = cue_set.cue1
    else:
        # Blank propagation: cue4 blank → cues 1-3 blank
        result.blanked_slots.extend([1, 2, 3, 4])

    # Check cue6 confidence
    cue6_confident = cue6_confidence >= cue6_threshold and cue_set.cue6 is not None
    result.cue6_confident = cue6_confident

    if cue6_confident:
        result.cue6 = cue_set.cue6
        result.cue5 = cue_set.cue5

        # cue7/8 only if anchored on cue6 (not mid-song)
        if not cue_set.cue7_midsong:
            result.cue7 = cue_set.cue7
            result.cue8 = cue_set.cue8
    else:
        # Blank propagation: cue6 blank → cue5 blank, cue7/8 if anchored
        result.blanked_slots.append(5)
        result.blanked_slots.append(6)
        if not cue_set.cue7_midsong:
            result.blanked_slots.extend([7, 8])

    return result


@dataclass
class ThresholdFitResult:
    """Result of fitting confidence thresholds on gold pool."""
    cue4_thresholds: dict[str, float]  # precision -> threshold
    cue6_thresholds: dict[str, float]
    cue4_precision_curve: list[tuple[float, float, float]]  # (threshold, precision, coverage)
    cue6_precision_curve: list[tuple[float, float, float]]


def fit_thresholds_on_gold_pool(
    gold_data: list[tuple[TrackFeatures, dict[int, int]]],
    model_predictions: list[tuple[int | None, int | None]],
) -> ThresholdFitResult:
    """Fit confidence thresholds on gold pool data.

    Args:
        gold_data: List of (features, gold_cues) tuples
        model_predictions: List of (cue4_beat, cue6_beat) predictions

    Returns:
        ThresholdFitResult with optimal thresholds for each precision target
    """
    cue4_data: list[tuple[float, bool]] = []  # (confidence, is_correct)
    cue6_data: list[tuple[float, bool]] = []

    for (features, gold), (pred_cue4, pred_cue6) in zip(gold_data, model_predictions):
        gold_cue4 = gold.get(3)  # 0-indexed: slot 3 = cue4
        gold_cue6 = gold.get(5)  # 0-indexed: slot 5 = cue6

        # Cue4
        if gold_cue4 is not None:
            signals = compute_cue_confidence_signals(features, pred_cue4, cue_slot=4)
            is_correct = pred_cue4 is not None and abs(pred_cue4 - gold_cue4) <= 1.0
            cue4_data.append((signals.calibrated_confidence, is_correct))

        # Cue6
        if gold_cue6 is not None:
            signals = compute_cue_confidence_signals(features, pred_cue6, cue_slot=6)
            is_correct = pred_cue6 is not None and abs(pred_cue6 - gold_cue6) <= 1.0
            cue6_data.append((signals.calibrated_confidence, is_correct))

    def compute_precision_coverage_curve(
        data: list[tuple[float, bool]],
    ) -> list[tuple[float, float, float]]:
        """Compute precision/coverage at various thresholds."""
        thresholds = np.arange(0.0, 1.01, 0.05)
        curve = []

        total = len(data)
        if total == 0:
            return [(0.0, 0.0, 0.0)]

        for thresh in thresholds:
            # Emitted = predictions above threshold
            emitted = [(conf, correct) for conf, correct in data if conf >= thresh]
            n_emitted = len(emitted)

            if n_emitted == 0:
                precision = 1.0  # No predictions = perfect precision
                coverage = 0.0
            else:
                n_correct = sum(1 for _, correct in emitted if correct)
                precision = n_correct / n_emitted
                coverage = n_emitted / total

            curve.append((float(thresh), precision, coverage))

        return curve

    cue4_curve = compute_precision_coverage_curve(cue4_data)
    cue6_curve = compute_precision_coverage_curve(cue6_data)

    def find_threshold_for_precision(
        curve: list[tuple[float, float, float]],
        target_precision: float,
    ) -> float:
        """Find lowest threshold that achieves target precision."""
        for thresh, prec, cov in curve:
            if prec >= target_precision:
                return thresh
        # If no threshold achieves target, return highest
        return 1.0

    cue4_thresholds = {
        "80": find_threshold_for_precision(cue4_curve, 0.80),
        "90": find_threshold_for_precision(cue4_curve, 0.90),
        "95": find_threshold_for_precision(cue4_curve, 0.95),
    }

    cue6_thresholds = {
        "80": find_threshold_for_precision(cue6_curve, 0.80),
        "90": find_threshold_for_precision(cue6_curve, 0.90),
        "95": find_threshold_for_precision(cue6_curve, 0.95),
    }

    return ThresholdFitResult(
        cue4_thresholds=cue4_thresholds,
        cue6_thresholds=cue6_thresholds,
        cue4_precision_curve=cue4_curve,
        cue6_precision_curve=cue6_curve,
    )
