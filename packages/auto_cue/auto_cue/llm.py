"""LLM-based cue picker for selecting all cue positions.

Uses an OpenAI model to pick all 8 cues with model judgment on each one:
- Cue 4 and 6 (drops) are primary picks
- Cues 1, 2, 7, 8 are also model-chosen from valid candidates (not just derived)
- Cues 3 and 5 are derived deterministically (cue4-32 and cue6-32)
- Validator still enforces 32-beat lattice constraints
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from auto_cue.features import TrackFeatures, format_phrase_table
from auto_cue.validate import CueSet

DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are a DJ cue point assistant. You analyze audio features to place 8 hot cues for Serato DJ.

# Will's Serato cue system

## Slot meanings (YOU must choose each one)
- Cue 4: FIRST DROP (the main drop - biggest energy jump, set first)
- Cue 3: Buildup start = cue4 - 32 beats (deterministic)
- Cue 2: Transition end point - often right before a vocal enters. Choose from: cue3-32, cue3-64, or cue3-96
- Cue 1: Intro/cue-in - where the DJ would start. Choose from: beat 0, or any cue4-k*32 that's before cue2
- Cue 6: LAST DROP (can be same as cue4 for single-drop tracks, or a later drop)
- Cue 5: Build into last drop = cue6 - 32 beats (deterministic)
- Cue 7: First mix-out point. Choose from: cue6+32, cue6+64, OR a mid-song point if outro is short
- Cue 8: "Last call" - about 32-48 beats before the track ends. Choose from: cue7+32, or end-32, end-48

## Lattice rules (MUST be followed)
- Cues 1, 2, 3, 4: ALL must be on the same 32-beat lattice anchored at cue4
- Cues 5, 6, 7, 8: ALL must be on the same 32-beat lattice anchored at cue6
- The two lattices are INDEPENDENT (cue6 - cue4 need not be multiple of 32)

## Genre patterns
- Bass music (dubstep, DnB, trap, ~70-87 BPM): cue1 often at beat 0, cue4→cue6 ≈ 96 beats
- House/pop (~126 BPM): longer intros, cue4→cue6 ≈ 192 beats, cue7 may be mid-song

## Decision guidelines
- Cue 1: Where should mixing IN start? Look for a clean intro section.
- Cue 2: Where should the incoming track be fully mixed? Often right before vocals.
- Cue 7: Where should mixing OUT start? Short outro = use mid-song point before cue5.
- Cue 8: Final warning point. Should be 32-48 beats before audio ends.
- CRITICAL: If you can't confidently place cue4 or cue6, set "abstain": true
- A blank song is MUCH better than wrong cues

You MUST respond with valid JSON only. No markdown, no explanation."""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "cue1_beat": {"type": ["integer", "null"], "description": "Beat position for cue 1, or null if uncertain"},
        "cue2_beat": {"type": ["integer", "null"], "description": "Beat position for cue 2, or null if uncertain"},
        "cue4_beat": {"type": ["integer", "null"], "description": "Beat position for cue 4 (first drop)"},
        "cue6_beat": {"type": ["integer", "null"], "description": "Beat position for cue 6 (last drop)"},
        "cue7_beat": {"type": ["integer", "null"], "description": "Beat position for cue 7, or null if uncertain"},
        "cue8_beat": {"type": ["integer", "null"], "description": "Beat position for cue 8, or null if uncertain"},
        "cue7_midsong": {"type": "boolean", "description": "True if cue7 is a mid-song point before cue5"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Overall confidence 0-1"},
        "abstain": {"type": "boolean", "description": "True if unable to confidently place drops"},
        "rationale": {"type": "string", "description": "Brief explanation of choices"}
    },
    "required": ["cue4_beat", "cue6_beat", "confidence", "abstain", "rationale"],
    "additionalProperties": False
}


@dataclass
class LLMPrediction:
    """Result from LLM cue prediction."""
    cue1_beat: int | None
    cue2_beat: int | None
    cue4_beat: int
    cue6_beat: int
    cue7_beat: int | None
    cue8_beat: int | None
    cue7_midsong: bool
    confidence: float
    abstain: bool
    rationale: str
    raw_response: str = ""


@dataclass
class AbstainDecision:
    """Structured abstention with reasons."""
    should_abstain: bool
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    
    def add_reason(self, reason: str, penalty: float = 0.15) -> None:
        self.reasons.append(reason)
        self.confidence = max(0.0, self.confidence - penalty)


def get_api_key() -> str:
    """Get OpenAI API key from environment."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ValueError("OPENAI_API_KEY not set")
    return key


def predict_cues_llm(
    features: TrackFeatures,
    *,
    model: str = DEFAULT_MODEL,
    style: str | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> LLMPrediction:
    """Use LLM to predict all cue positions with model judgment.
    
    Args:
        features: Extracted audio features
        model: Model name (default: gpt-4o-mini)
        style: Track style hint (e.g., "dubstep", "house")
        examples: Few-shot examples from gold tracks
    
    Returns:
        LLMPrediction with all cue positions and confidence
    """
    phrase_table = format_phrase_table(features)
    
    valid_cue1_options = _get_valid_cue1_options(features)
    valid_cue8_options = _get_valid_cue8_options(features)
    
    prompt_parts = ["## This track", ""]
    
    if style:
        prompt_parts.append(f"Style: {style}")
    
    prompt_parts.append(f"Total beats: {features.total_beats}")
    prompt_parts.append(f"BPM: {features.bpm:.1f}")
    prompt_parts.append("")
    prompt_parts.append(phrase_table)
    prompt_parts.append("")
    prompt_parts.append(f"Valid cue1 options (32-beat boundaries): {valid_cue1_options[:8]}")
    prompt_parts.append(f"Valid cue8 options (near end): {valid_cue8_options}")
    
    if examples:
        prompt_parts.append("")
        prompt_parts.append("## Similar gold tracks (for reference)")
        for ex in examples[:3]:
            prompt_parts.append(f"- {ex.get('name', 'track')}: cue4={ex.get('cue4')}, cue6={ex.get('cue6')}")
    
    prompt_parts.append("")
    prompt_parts.append("Pick all cues. cue3 = cue4-32, cue5 = cue6-32 are derived.")
    prompt_parts.append("Return JSON with your choices. Set abstain=true if drop positions are unclear.")
    
    user_prompt = "\n".join(prompt_parts)
    
    api_key = get_api_key()
    
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0,
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        result = response.json()
    
    content = result["choices"][0]["message"]["content"]
    
    return _parse_llm_response(content, features)


def _get_valid_cue1_options(features: TrackFeatures) -> list[int]:
    """Get valid cue1 beat positions (32-beat boundaries in first quarter)."""
    options = []
    max_beat = min(features.total_beats // 4, 128)
    for beat in range(0, max_beat + 1, 32):
        options.append(beat)
    return options


def _get_valid_cue8_options(features: TrackFeatures) -> list[int]:
    """Get valid cue8 beat positions (near end)."""
    options = []
    for offset in [32, 48, 64]:
        beat = features.total_beats - offset
        if beat > 0:
            options.append(beat)
    return sorted(options)


def _parse_llm_response(content: str, features: TrackFeatures) -> LLMPrediction:
    """Parse LLM JSON response."""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}") from e
    
    if data.get("abstain", False):
        raise ValueError(f"LLM abstained: {data.get('rationale', 'no reason given')}")
    
    cue4 = data.get("cue4_beat")
    cue6 = data.get("cue6_beat")
    
    if cue4 is None or cue6 is None:
        raise ValueError("LLM response missing cue4_beat or cue6_beat")
    
    cue1 = data.get("cue1_beat")
    cue2 = data.get("cue2_beat")
    cue7 = data.get("cue7_beat")
    cue8 = data.get("cue8_beat")
    
    return LLMPrediction(
        cue1_beat=int(cue1) if cue1 is not None else None,
        cue2_beat=int(cue2) if cue2 is not None else None,
        cue4_beat=int(cue4),
        cue6_beat=int(cue6),
        cue7_beat=int(cue7) if cue7 is not None else None,
        cue8_beat=int(cue8) if cue8 is not None else None,
        cue7_midsong=bool(data.get("cue7_midsong", False)),
        confidence=float(data.get("confidence", 0.8)),
        abstain=False,
        rationale=str(data.get("rationale", "")),
        raw_response=content,
    )


def _assess_drop_confidence(features: TrackFeatures) -> AbstainDecision:
    """Assess confidence in drop detection from audio features.
    
    Returns AbstainDecision with reasons and adjusted confidence.
    """
    decision = AbstainDecision(should_abstain=False, confidence=0.7)
    
    if not features.drop_candidates:
        decision.should_abstain = True
        decision.add_reason("no drop candidates detected", 0.5)
        return decision
    
    if len(features.phrases) < 4:
        decision.should_abstain = True
        decision.add_reason("track too short for analysis", 0.5)
        return decision
    
    drop_scores = [p.drop_score for p in features.phrases if p.is_drop_candidate]
    
    if not drop_scores:
        decision.should_abstain = True
        decision.add_reason("no phrases scored as drops", 0.5)
        return decision
    
    max_score = max(drop_scores)
    
    if max_score < 2.0:
        decision.add_reason(f"weak drop evidence (max_score={max_score:.1f} < 2.0)", 0.2)
    
    if max_score < 1.5:
        decision.should_abstain = True
        decision.add_reason(f"very weak drop evidence (max_score={max_score:.1f} < 1.5)", 0.3)
        return decision
    
    if len(drop_scores) >= 2:
        sorted_scores = sorted(drop_scores, reverse=True)
        top_two_ratio = sorted_scores[1] / sorted_scores[0] if sorted_scores[0] > 0 else 0
        
        if top_two_ratio > 0.9:
            decision.add_reason(f"ambiguous top drops (ratio={top_two_ratio:.2f})", 0.15)
    
    if len(drop_scores) >= 3:
        sorted_scores = sorted(drop_scores, reverse=True)
        top_three_similar = all(
            s / sorted_scores[0] > 0.8 for s in sorted_scores[:3]
        ) if sorted_scores[0] > 0 else False
        
        if top_three_similar:
            decision.add_reason("multiple similar-strength drop candidates", 0.1)
    
    rms_values = [p.rms_db for p in features.phrases]
    if rms_values:
        rms_range = max(rms_values) - min(rms_values)
        if rms_range < 6.0:
            decision.add_reason(f"flat dynamics (rms_range={rms_range:.1f}dB < 6dB)", 0.15)
    
    candidates = features.drop_candidates
    third = features.total_beats // 3
    two_thirds = 2 * features.total_beats // 3
    
    first_third_drops = [c for c in candidates if 64 <= c <= third]
    last_third_drops = [c for c in candidates if c > two_thirds]
    
    if not first_third_drops and not last_third_drops:
        decision.add_reason("drops only in middle third - unusual structure", 0.1)
    
    if decision.confidence < 0.4:
        decision.should_abstain = True
    
    return decision


def predict_cues_rules(features: TrackFeatures) -> LLMPrediction:
    """Rule-based fallback when LLM is not available.
    
    Now includes proper confidence gating - will abstain when:
    - Weak drop evidence (low scores)
    - Ambiguous candidates (similar scores)
    - Unusual track structure
    - Flat dynamics
    - Selected positions have poor scores relative to alternatives
    """
    confidence_check = _assess_drop_confidence(features)
    
    if confidence_check.should_abstain:
        reasons = "; ".join(confidence_check.reasons)
        raise ValueError(f"Abstaining: {reasons}")
    
    phrase_scores = {p.beat_start: p.drop_score for p in features.phrases if p.is_drop_candidate}
    max_score = max(phrase_scores.values()) if phrase_scores else 0
    
    candidates = [b for b in features.drop_candidates if b >= 64]
    if not candidates:
        candidates = features.drop_candidates
    
    if not candidates:
        raise ValueError("Abstaining: no valid drop candidates")
    
    third = features.total_beats // 3
    two_thirds = 2 * features.total_beats // 3
    
    first_third = [b for b in candidates if b <= third and b >= 64]
    second_third = [b for b in candidates if third < b <= two_thirds]
    last_third = [b for b in candidates if b > two_thirds]
    
    if first_third:
        cue4 = first_third[0]
    elif second_third:
        cue4 = second_third[0]
    else:
        cue4 = max(64, candidates[0]) if candidates else 96
    
    if cue4 < 64:
        cue4 = 64
    
    if last_third:
        cue6 = last_third[0]
    elif second_third:
        cue6 = second_third[-1] if second_third[-1] > cue4 else second_third[0]
    else:
        cue6 = cue4 + 96
    
    if cue6 < cue4:
        cue6 = cue4
    if cue6 == cue4 and len(candidates) > 1:
        later = [c for c in candidates if c > cue4]
        if later:
            cue6 = later[0]
    
    cue4_score = phrase_scores.get(cue4, 0)
    cue6_score = phrase_scores.get(cue6, 0)
    
    if cue4_score < 1.5:
        confidence_check.add_reason(f"cue4 has weak score ({cue4_score:.1f})", 0.15)
    if cue6_score < 1.5:
        confidence_check.add_reason(f"cue6 has weak score ({cue6_score:.1f})", 0.15)
    
    if max_score > 0:
        cue4_relative = cue4_score / max_score
        cue6_relative = cue6_score / max_score
        
        if cue4_relative < 0.5:
            confidence_check.add_reason(
                f"cue4 at {cue4} has {cue4_relative:.0%} of max drop score", 0.2
            )
        if cue6_relative < 0.5:
            confidence_check.add_reason(
                f"cue6 at {cue6} has {cue6_relative:.0%} of max drop score", 0.2
            )
    
    if confidence_check.confidence < 0.4:
        reasons = "; ".join(confidence_check.reasons)
        raise ValueError(f"Abstaining: {reasons}")
    
    is_bass_music = features.bpm < 100
    
    cue3 = cue4 - 32
    cue5 = cue6 - 32
    
    if is_bass_music:
        cue2 = cue3 - 32
        cue1 = 0
    else:
        cue2 = cue3 - 64
        if cue2 < 32:
            cue2 = cue3 - 32
        cue1 = cue4 - 128
        if cue1 < 0:
            cue1 = cue4 - 96
        if cue1 < 0:
            cue1 = 0
    
    if cue1 >= cue2:
        cue1 = max(0, cue2 - 32)
    if cue1 >= cue2:
        cue1 = 0
        if cue2 <= 0:
            cue2 = 32
    
    cue7 = cue6 + 32
    
    min_end_margin = 8
    max_cue8 = features.total_beats - min_end_margin
    
    cue8 = cue6 + 64
    
    if cue8 > max_cue8:
        k = max(1, (max_cue8 - cue6) // 32)
        cue8 = cue6 + k * 32
    
    if cue8 < cue7:
        cue8 = cue7
    
    if cue8 > features.total_beats - min_end_margin:
        cue8 = cue7
    
    rationale_parts = ["rule-based"]
    if confidence_check.reasons:
        rationale_parts.append(f"warnings: {', '.join(confidence_check.reasons)}")
    
    return LLMPrediction(
        cue1_beat=cue1,
        cue2_beat=cue2,
        cue4_beat=cue4,
        cue6_beat=cue6,
        cue7_beat=cue7,
        cue8_beat=cue8,
        cue7_midsong=False,
        confidence=confidence_check.confidence,
        abstain=False,
        rationale="; ".join(rationale_parts),
        raw_response="",
    )


def prediction_to_cue_set(
    prediction: LLMPrediction,
    total_beats: int,
) -> CueSet:
    """Convert LLM prediction to a complete CueSet."""
    cues = CueSet(total_beats=total_beats, cue7_midsong=prediction.cue7_midsong)
    
    cues.cue4 = prediction.cue4_beat
    cues.cue6 = prediction.cue6_beat
    
    cues.cue3 = max(0, prediction.cue4_beat - 32)
    cues.cue5 = max(0, prediction.cue6_beat - 32)
    
    if prediction.cue1_beat is not None:
        cues.cue1 = prediction.cue1_beat
    else:
        cues.cue1 = 0
    
    if prediction.cue2_beat is not None:
        cues.cue2 = prediction.cue2_beat
    else:
        cues.cue2 = max(0, cues.cue3 - 32)
    
    if prediction.cue7_beat is not None:
        cues.cue7 = prediction.cue7_beat
    else:
        cues.cue7 = cues.cue6 + 32
    
    if prediction.cue8_beat is not None:
        cues.cue8 = prediction.cue8_beat
    else:
        cues.cue8 = cues.cue7 + 32
        if cues.cue8 > total_beats - 16:
            max_cue8 = total_beats - 16
            k = (max_cue8 - cues.cue6) // 32
            cues.cue8 = cues.cue6 + k * 32
            if cues.cue8 <= cues.cue7:
                cues.cue8 = cues.cue7 + 32
    
    if cues.cue1 >= cues.cue2:
        if cues.cue2 > 16:
            cues.cue1 = cues.cue2 - 16
        else:
            cues.cue1 = 0
            if cues.cue2 == 0:
                cues.cue2 = 16
    
    cues.confidences = {
        1: prediction.confidence * 0.9,
        2: prediction.confidence * 0.85,
        3: 0.95,
        4: prediction.confidence,
        5: 0.95,
        6: prediction.confidence,
        7: prediction.confidence * 0.85,
        8: prediction.confidence * 0.8,
    }
    
    return cues
