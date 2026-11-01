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


class LLMAPIError(Exception):
    """Raised for API/auth/HTTP errors that should cause immediate failure."""
    pass


class CueAbstainError(Exception):
    """Raised when the predictor decides to abstain (legitimate abstention)."""
    pass


from auto_cue.features import TrackFeatures, format_phrase_table
from auto_cue.validate import CueSet

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_REASONING_EFFORT = "medium"

REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini", "gpt-6-luna"}

MODEL_PRICING = {
    "gpt-6-luna": {"input": 0.10, "output": 0.50, "cached_input": 0.01},
}

SYSTEM_PROMPT = """You are a DJ cue point assistant. Analyze audio phrase table to place 8 hot cues for Serato DJ.

# Will's cue system

## DROP DETECTION (most important)
- Cue 4: FIRST DROP - the BIGGEST energy jump. Look for highest positive Δrms + Δlow after a quieter buildup section. Usually beat 64-128.
- Cue 6: LAST DROP - the final big energy moment. Often the last high-scoring drop candidate, usually 96-192 beats after cue4. For single-drop tracks, cue6 = cue4.

## Other cues (derived from drops)
- Cue 3 = cue4 - 32 (automatic, buildup)
- Cue 5 = cue6 - 32 (automatic, buildup)
- Cue 2: Pre-vocal entry. Pick cue4 - 64, cue4 - 96, or cue4 - 128 (must be < cue3)
- Cue 1: Intro. Usually beat 0, or cue4 - k*32 where k gives you < cue2

## CRITICAL: Cue 7 and Cue 8 LATTICE RULE
Cues 7 and 8 MUST be on cue6's 32-beat lattice:
- Cue 7 = cue6 + 32 (preferred) or cue6 + 64
- Cue 8 = cue6 + 64 (if cue7=cue6+32) or cue6 + 96 (if cue7=cue6+64)
- cue8 should be ~32-48 beats before track ends, BUT must be cue6 + k*32

## How to read the phrase table
- "beat": starting beat of 32-beat phrase
- "rms_db": overall loudness (higher = louder)
- "low_db": bass energy 20-150Hz (drops have HIGH low_db)
- "Δrms", "Δlow": change vs previous phrase (BIG POSITIVE = likely drop)
- "drop": drop candidate score (higher = more likely)

## Genre hints
- Bass/DnB (70-90 BPM): cue1 at 0, drops ~96 beats apart
- House (120-130 BPM): longer intros, drops ~192 beats apart

Set abstain=true ONLY if you genuinely cannot identify where the drops are."""

OPENAI_JSON_SCHEMA = {
    "name": "cue_prediction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "cue1_beat": {"type": ["integer", "null"], "description": "Beat for cue 1 (intro), or null"},
            "cue2_beat": {"type": ["integer", "null"], "description": "Beat for cue 2 (pre-vocal), or null"},
            "cue4_beat": {"type": ["integer", "null"], "description": "Beat for cue 4 (FIRST DROP), or null if abstaining"},
            "cue6_beat": {"type": ["integer", "null"], "description": "Beat for cue 6 (LAST DROP), or null if abstaining"},
            "cue7_beat": {"type": ["integer", "null"], "description": "Beat for cue 7 (mix-out = cue6+32 or cue6+64), or null"},
            "cue8_beat": {"type": ["integer", "null"], "description": "Beat for cue 8 (last call = cue6+64 or cue6+96), or null"},
            "cue7_midsong": {"type": "boolean", "description": "True if cue7 is mid-song (rare)"},
            "abstain": {"type": "boolean", "description": "True if drops are unclear"},
            "rationale": {"type": "string", "description": "Brief reasoning"}
        },
        "required": ["cue1_beat", "cue2_beat", "cue4_beat", "cue6_beat", "cue7_beat", "cue8_beat", "cue7_midsong", "abstain", "rationale"],
        "additionalProperties": False
    }
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
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0


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
        raise LLMAPIError("OPENAI_API_KEY environment variable not set")
    return key


def predict_cues_llm(
    features: TrackFeatures,
    *,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
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
        LLMPrediction with all cue positions
        
    Raises:
        LLMAPIError: For API/auth/HTTP errors (should cause immediate failure)
        CueAbstainError: When model abstains (legitimate abstention)
    """
    phrase_table = format_phrase_table(features)
    
    prompt_parts = [
        f"## Track Info",
        f"Total beats: {features.total_beats}",
        f"BPM: {features.bpm:.1f}",
    ]
    
    if style:
        prompt_parts.append(f"Style: {style}")
    
    prompt_parts.append("")
    prompt_parts.append("## Phrase Table (32-beat phrases)")
    prompt_parts.append(phrase_table)
    
    prompt_parts.append("")
    prompt_parts.append("## Instructions")
    prompt_parts.append("1. Find cue4 (first drop): Look for the phrase with highest positive Δrms + Δlow, usually the first big energy jump.")
    prompt_parts.append("2. Find cue6 (last drop): Usually the last high-scoring drop, often 96-192 beats after cue4.")
    prompt_parts.append("3. Derive: cue3 = cue4-32, cue5 = cue6-32")
    prompt_parts.append("4. Set cue7 = cue6+32 and cue8 = cue6+64 (MUST be on cue6's 32-beat lattice)")
    prompt_parts.append("5. Set cue2 and cue1 on cue4's 32-beat lattice")
    prompt_parts.append("")
    prompt_parts.append(f"Track ends at beat {features.total_beats}. cue8 should be around beat {features.total_beats - 40} but MUST be cue6 + k*32.")
    
    if examples:
        prompt_parts.append("")
        prompt_parts.append("## Similar tracks (for reference)")
        for ex in examples[:3]:
            prompt_parts.append(f"- {ex.get('name', 'track')}: cue4={ex.get('cue4')}, cue6={ex.get('cue6')}")
    
    user_prompt = "\n".join(prompt_parts)
    
    try:
        api_key = get_api_key()
    except LLMAPIError:
        raise
    
    is_reasoning_model = any(model.startswith(rm) for rm in REASONING_MODELS)
    
    request_body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": OPENAI_JSON_SCHEMA,
        },
    }
    
    if is_reasoning_model:
        request_body["max_completion_tokens"] = 2048
        if reasoning_effort in ("low", "medium", "high"):
            request_body["reasoning_effort"] = reasoning_effort
    else:
        request_body["temperature"] = 0
        request_body["max_tokens"] = 1024
    
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise LLMAPIError(f"OpenAI API authentication failed (401): check OPENAI_API_KEY") from e
        elif e.response.status_code == 429:
            raise LLMAPIError(f"OpenAI API rate limited (429)") from e
        else:
            raise LLMAPIError(f"OpenAI API HTTP error {e.response.status_code}: {e.response.text[:200]}") from e
    except httpx.RequestError as e:
        raise LLMAPIError(f"OpenAI API request failed: {e}") from e
    except Exception as e:
        raise LLMAPIError(f"OpenAI API unexpected error: {e}") from e
    
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMAPIError(f"Unexpected API response structure: {result}") from e
    
    usage = result.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    
    pricing = MODEL_PRICING.get(model, {"input": 0.10, "output": 0.50, "cached_input": 0.01})
    uncached_input = input_tokens - cached_tokens
    cost_usd = (
        uncached_input * pricing["input"] +
        cached_tokens * pricing.get("cached_input", pricing["input"]) +
        output_tokens * pricing["output"]
    ) / 1_000_000
    
    prediction = _parse_llm_response(content, features)
    prediction.input_tokens = input_tokens
    prediction.output_tokens = output_tokens
    prediction.model = model
    prediction.cost_usd = cost_usd
    
    return prediction


def _parse_llm_response(content: str, features: TrackFeatures) -> LLMPrediction:
    """Parse LLM JSON response.
    
    Raises:
        CueAbstainError: If model chose to abstain
        LLMAPIError: If response is malformed
    """
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
        raise LLMAPIError(f"Failed to parse LLM response as JSON: {e}\nResponse: {content[:200]}") from e
    
    if data.get("abstain", False):
        raise CueAbstainError(f"LLM abstained: {data.get('rationale', 'no reason given')}")
    
    cue4 = data.get("cue4_beat")
    cue6 = data.get("cue6_beat")
    
    if cue4 is None or cue6 is None:
        raise CueAbstainError(f"LLM returned null for cue4_beat or cue6_beat (implicit abstain): {data.get('rationale', '')}")
    
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
        confidence=0.8,  # Fixed confidence; don't trust model self-report
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
    
    Raises:
        CueAbstainError: When confidence is too low or no valid candidates
    """
    confidence_check = _assess_drop_confidence(features)
    
    if confidence_check.should_abstain:
        reasons = "; ".join(confidence_check.reasons)
        raise CueAbstainError(f"Abstaining: {reasons}")
    
    phrase_scores = {p.beat_start: p.drop_score for p in features.phrases if p.is_drop_candidate}
    max_score = max(phrase_scores.values()) if phrase_scores else 0
    
    candidates = [b for b in features.drop_candidates if b >= 64]
    if not candidates:
        candidates = features.drop_candidates
    
    if not candidates:
        raise CueAbstainError("Abstaining: no valid drop candidates")
    
    sorted_by_score = sorted(candidates, key=lambda b: phrase_scores.get(b, 0), reverse=True)
    
    third = features.total_beats // 3
    two_thirds = 2 * features.total_beats // 3
    
    first_half_candidates = [b for b in sorted_by_score if b < features.total_beats // 2 and b >= 64]
    second_half_candidates = [b for b in sorted_by_score if b >= features.total_beats // 2]
    
    if first_half_candidates:
        cue4 = first_half_candidates[0]
    elif sorted_by_score:
        cue4 = sorted_by_score[0]
    else:
        raise CueAbstainError("Abstaining: cannot find credible first drop candidate")
    
    if second_half_candidates:
        cue6 = second_half_candidates[0]
    else:
        later_candidates = [b for b in sorted_by_score if b > cue4]
        if later_candidates:
            cue6 = later_candidates[0]
        else:
            cue6 = cue4
    
    if cue6 < cue4:
        cue6 = cue4
    
    cue4_score = phrase_scores.get(cue4, 0)
    cue6_score = phrase_scores.get(cue6, 0)
    
    if cue4_score < 1.5:
        confidence_check.add_reason(f"cue4 has weak score ({cue4_score:.1f})", 0.15)
    if cue6_score < 1.5 and cue6 != cue4:
        confidence_check.add_reason(f"cue6 has weak score ({cue6_score:.1f})", 0.15)
    
    if max_score > 0:
        cue4_relative = cue4_score / max_score
        if cue4_relative < 0.5:
            confidence_check.add_reason(
                f"cue4 at {cue4} has {cue4_relative:.0%} of max drop score", 0.2
            )
    
    if confidence_check.confidence < 0.4:
        reasons = "; ".join(confidence_check.reasons)
        raise CueAbstainError(f"Abstaining: {reasons}")
    
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
    
    if cue2 >= cue3:
        if cue3 > 32:
            cue2 = cue3 - 32
        else:
            cue2 = 0
            cue1 = 0
    
    # Note: duplicates are allowed in 18% of tracks (e.g., cue2=cue3, cue7=cue8)
    
    cue7 = cue6 + 32
    cue8 = cue6 + 64
    
    min_end_margin = 8
    max_cue8 = features.total_beats - min_end_margin
    
    if cue8 > max_cue8:
        k = max(1, (max_cue8 - cue6) // 32)
        cue8 = cue6 + k * 32
    
    if cue8 <= cue7:
        cue8 = cue7
    
    if cue8 > features.total_beats - min_end_margin:
        cue8 = cue7
    
    # Note: duplicates like cue7=cue8 are allowed near track end
    
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
    """Convert LLM prediction to a complete CueSet.
    
    Ensures all cues respect 32-beat lattice constraints:
    - Cues 1,2,3 on cue4's lattice: (cue4 - cueN) % 32 == 0
    - Cues 5,7,8 on cue6's lattice: (cueN - cue6) % 32 == 0
    """
    cues = CueSet(total_beats=total_beats, cue7_midsong=prediction.cue7_midsong)
    
    cues.cue4 = prediction.cue4_beat
    cues.cue6 = prediction.cue6_beat
    
    if prediction.cue4_beat < 64:
        cues.cue3 = prediction.cue4_beat
        cues.cue2 = prediction.cue4_beat
        cues.cue1 = 0
    else:
        cues.cue3 = prediction.cue4_beat - 32
    
    if prediction.cue6_beat < 64:
        cues.cue5 = prediction.cue6_beat
    else:
        cues.cue5 = prediction.cue6_beat - 32
    
    if prediction.cue4_beat >= 64:
        if prediction.cue2_beat is not None:
            offset = (prediction.cue4_beat - prediction.cue2_beat) % 32
            if offset != 0:
                k = round((prediction.cue4_beat - prediction.cue2_beat) / 32)
                cues.cue2 = prediction.cue4_beat - k * 32
            else:
                cues.cue2 = prediction.cue2_beat
        else:
            cues.cue2 = max(0, cues.cue3 - 32)
        
        if cues.cue2 < 0:
            cues.cue2 = 0
        if cues.cue2 > cues.cue3:
            cues.cue2 = cues.cue3
    
    if prediction.cue4_beat >= 64:
        if prediction.cue1_beat is not None:
            offset = (prediction.cue4_beat - prediction.cue1_beat) % 32
            if offset != 0:
                k = round((prediction.cue4_beat - prediction.cue1_beat) / 32)
                cues.cue1 = prediction.cue4_beat - k * 32
            else:
                cues.cue1 = prediction.cue1_beat
        else:
            cues.cue1 = 0
        
        if cues.cue1 < 0:
            cues.cue1 = 0
    
    if prediction.cue4_beat >= 64:
        if cues.cue2 <= 0:
            cues.cue2 = cues.cue3
        
        if cues.cue1 >= cues.cue2:
            cues.cue1 = max(0, cues.cue2 - 32)
        
        if cues.cue1 >= cues.cue2 and cues.cue2 > 0:
            cues.cue1 = 0
        
        if cues.cue1 >= cues.cue2:
            if cues.cue3 > 32:
                cues.cue2 = cues.cue3
                cues.cue1 = cues.cue3 - 32
            else:
                cues.cue2 = cues.cue3
                cues.cue1 = 0
    
    if prediction.cue7_beat is not None:
        cue7_offset = prediction.cue7_beat - prediction.cue6_beat
        if cue7_offset % 32 != 0:
            k = max(1, round(cue7_offset / 32))
            cues.cue7 = prediction.cue6_beat + k * 32
        else:
            cues.cue7 = prediction.cue7_beat
    else:
        cues.cue7 = cues.cue6 + 32
    
    if prediction.cue8_beat is not None:
        cue8_offset = prediction.cue8_beat - prediction.cue6_beat
        if cue8_offset % 32 != 0:
            k = max(1, round(cue8_offset / 32))
            cues.cue8 = prediction.cue6_beat + k * 32
        else:
            cues.cue8 = prediction.cue8_beat
    else:
        cues.cue8 = cues.cue6 + 64
    
    if cues.cue8 > total_beats - 8:
        max_cue8 = total_beats - 8
        k = max(1, (max_cue8 - cues.cue6) // 32)
        cues.cue8 = cues.cue6 + k * 32
    
    if cues.cue8 <= cues.cue7:
        cues.cue8 = cues.cue7
    
    cues.confidences = {
        1: 0.8,
        2: 0.8,
        3: 0.95,
        4: 0.9,
        5: 0.95,
        6: 0.9,
        7: 0.8,
        8: 0.8,
    }
    
    return cues
