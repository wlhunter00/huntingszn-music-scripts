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
from typing import Any

import httpx


class LLMAPIError(Exception):
    """Raised for API/auth/HTTP errors that should cause immediate failure."""
    pass


class CueAbstainError(Exception):
    """Raised when the predictor decides to abstain (legitimate abstention)."""
    pass


from auto_cue.features import TrackFeatures, format_phrase_table  # noqa: E402
from auto_cue.validate import CueSet  # noqa: E402

DEFAULT_MODEL = "gpt-6.1-terra"
DEFAULT_REASONING_EFFORT = "medium"

REASONING_MODELS = {
    "o1", "o1-mini", "o1-preview", "o3", "o3-mini",
    "gpt-6-luna", "gpt-6.1-terra",
}

MODEL_PRICING = {
    "gpt-6-luna": {"input": 0.10, "output": 0.50, "cached_input": 0.01},
    "gpt-6.1-terra": {"input": 1.00, "output": 5.00, "cached_input": 0.05},
}

STATIC_RULES = """# Will's Hot Cue System for Serato DJ

You are placing 8 hot cues on a DJ track. Cues must be on the 32-beat phrase grid.

## DROP DETECTION (PRIMARY TASK)
- **Cue 4** = FIRST DROP: Biggest energy jump. Look for highest kick density jump \
(Δkick) and contrast score. Usually beat 64-128.
- **Cue 6** = LAST DROP: Final big energy moment. Often the last high-scoring drop, \
96-192 beats after cue4. Single-drop tracks: cue6=cue4.

## DERIVED CUES (automatic from drops)
- Cue 3 = cue4 - 32 (buildup before first drop)
- Cue 5 = cue6 - 32 (buildup before last drop)

## LATTICE RULES (CRITICAL)
- Cues 1,2,3 must be on cue4's 32-beat lattice: (cue4 - cueN) mod 32 == 0
- Cues 5,7,8 must be on cue6's 32-beat lattice: (cueN - cue6) mod 32 == 0
- Cue 2: Pre-vocal entry at cue4-64, cue4-96, or cue4-128 (must be < cue3). Look for \
vocal activity starting.
- Cue 1: Intro at 0 or cue4 - k*32 where result < cue2
- Cue 7 = cue6 + 32 (preferred) or cue6 + 64. Look for outro/vocal fade.
- Cue 8 = cue6 + 64 or cue6 + 96 (must be 32+ beats before track end)

## READING THE PHRASE TABLE
Each row is a 16-beat phrase. Key columns:
- **beat**: Starting beat of phrase
- **32?**: "▶" marks 32-beat boundaries (where cues should go)
- **pct**: Position as % of track (cue4 typically 20-45%, cue6 typically 55-85%)
- **rms/low**: Overall loudness and bass energy (<150Hz)
- **Δlow**: Bass change from previous phrase (BIG POSITIVE = kick coming in = DROP)
- **kick/Δkick**: Kick onset density and its change (KEY DROP SIGNAL)
- **vocal**: Vocal activity from isolated stem (use for cue2 entry, cue7/8 outro)
- **build**: Rising spectral centroid/highband/flatness (riser/buildup before drop)
- **snare**: Snare-roll detection (1-5kHz onset acceleration before drop)
- **contr**: Multi-scale before/after contrast (section boundary detection)
- **novel**: Self-similarity novelty (new section, not repeating)
- **gap**: Pre-drop gap (quiet moment right before the drop)
- **sust**: Post-drop sustain (CRITICAL: real drops stay loud, fake-outs drop off)
- **drop**: Combined drop score (higher = more likely drop point)

## DROP DETECTION STRATEGY
1. Look for high **Δkick** (kick drums coming back in after dropout)
2. High **contr** and **novel** = section change = potential drop
3. High **build** or **snare** in the phrase BEFORE = buildup into drop
4. High **gap** = quiet moment right before the drop
5. **FAKE-OUT CHECK**: Real drops have **sust >= -2** (energy stays high). \
If sust < -4, it's likely a fake-out (build peak, not the actual drop)

## BPM-BASED PATTERNS
- **bass (<80 BPM)**: cue1 at 0, drops ~64-96 beats apart, heavy kick patterns
- **dnb (80-100 BPM)**: cue1 at 0, drops ~96 beats apart, fast breaks
- **midtempo (100-115 BPM)**: mixed styles
- **house (115+ BPM)**: longer intros (64+ beats), drops ~192 beats apart

## ABSTENTION
Set abstain=true ONLY if drops are genuinely unclear (flat dynamics, no clear kicks)."""

OPENAI_JSON_SCHEMA = {
    "name": "cue_prediction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "cue1_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 1 (intro), or null",
            },
            "cue2_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 2 (pre-vocal), or null",
            },
            "cue4_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 4 (FIRST DROP), or null",
            },
            "cue6_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 6 (LAST DROP), or null",
            },
            "cue7_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 7 (mix-out cue6+32/64), or null",
            },
            "cue8_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 8 (last call cue6+64/96), or null",
            },
            "cue7_midsong": {
                "type": "boolean",
                "description": "True if cue7 is mid-song (rare)",
            },
            "abstain": {
                "type": "boolean",
                "description": "True if drops are unclear",
            },
            "rationale": {
                "type": "string",
                "description": "Brief reasoning",
            },
        },
        "required": [
            "cue1_beat", "cue2_beat", "cue4_beat", "cue6_beat",
            "cue7_beat", "cue8_beat", "cue7_midsong", "abstain", "rationale",
        ],
        "additionalProperties": False,
    },
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


@dataclass
class FewShotExample:
    """A gold-labeled example for few-shot learning."""
    name: str
    genre_bucket: str
    bpm: float
    total_beats: int
    phrase_table: str  # Full phrase table text
    cues: dict[int, int]  # slot (0-7) -> beat


def predict_cues_llm(
    features: TrackFeatures,
    *,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    genre_bucket: str | None = None,
    examples: list[FewShotExample] | None = None,
) -> LLMPrediction:
    """Use LLM to predict all cue positions with model judgment.

    Args:
        features: Extracted audio features
        model: Model name
        reasoning_effort: Reasoning effort for reasoning models
        genre_bucket: Genre hint (e.g., "dubstep/bass", "dnb", "house/dance")
        examples: Few-shot examples with full phrase tables (leave-one-out)

    Returns:
        LLMPrediction with all cue positions

    Raises:
        LLMAPIError: For API/auth/HTTP errors (should cause immediate failure)
        CueAbstainError: When model abstains (legitimate abstention)
    """
    phrase_table = format_phrase_table(features)

    messages: list[dict[str, str]] = []

    static_content = STATIC_RULES
    if examples:
        static_content += "\n\n# FEW-SHOT EXAMPLES\n"
        static_content += "Here are correctly-labeled tracks from the same genre:\n"
        for i, ex in enumerate(examples[:5], 1):
            static_content += f"\n## Example {i}: {ex.name}\n"
            static_content += f"Genre: {ex.genre_bucket}, BPM: {ex.bpm:.1f}, "
            static_content += f"Total beats: {ex.total_beats}\n\n"
            static_content += "### Phrase Table\n"
            static_content += ex.phrase_table + "\n\n"
            static_content += "### Gold Cues (beats)\n"
            cue_strs = [f"cue{s+1}={b}" for s, b in sorted(ex.cues.items())]
            static_content += ", ".join(cue_strs) + "\n"

    messages.append({"role": "system", "content": static_content})

    user_parts = ["# Track to Analyze\n"]

    if genre_bucket:
        user_parts.append(f"**Genre**: {genre_bucket}")

    user_parts.append(f"**BPM**: {features.bpm:.1f}")
    user_parts.append(f"**First beat**: {features.first_beat_s:.3f}s")
    user_parts.append(f"**Total beats**: {features.total_beats}")
    user_parts.append("")
    user_parts.append("## Phrase Table")
    user_parts.append(phrase_table)
    user_parts.append("")
    end_beat = features.total_beats
    user_parts.append(
        f"Track ends at beat {end_beat}. Place cue8 ~32-48 beats before end, "
        f"on cue6's 32-beat lattice."
    )
    user_parts.append("")
    user_parts.append("Return your cue predictions in JSON format.")

    messages.append({"role": "user", "content": "\n".join(user_parts)})

    try:
        api_key = get_api_key()
    except LLMAPIError:
        raise

    is_reasoning_model = any(model.startswith(rm) for rm in REASONING_MODELS)

    request_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": OPENAI_JSON_SCHEMA,
        },
    }

    if is_reasoning_model:
        request_body["max_completion_tokens"] = 4096
        if reasoning_effort in ("low", "medium", "high"):
            request_body["reasoning_effort"] = reasoning_effort
    else:
        request_body["temperature"] = 0
        request_body["max_tokens"] = 2048

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
            raise LLMAPIError("OpenAI API authentication failed (401): check OPENAI_API_KEY") from e
        elif e.response.status_code == 429:
            raise LLMAPIError("OpenAI API rate limited (429)") from e
        else:
            status = e.response.status_code
            text = e.response.text[:200]
            raise LLMAPIError(f"OpenAI API HTTP error {status}: {text}") from e
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
        msg = f"Failed to parse LLM response as JSON: {e}"
        raise LLMAPIError(f"{msg}\nResponse: {content[:200]}") from e

    if data.get("abstain", False):
        raise CueAbstainError(f"LLM abstained: {data.get('rationale', 'no reason given')}")

    cue4 = data.get("cue4_beat")
    cue6 = data.get("cue6_beat")

    if cue4 is None or cue6 is None:
        rationale = data.get("rationale", "")
        raise CueAbstainError(f"LLM null cue4/cue6 (abstain): {rationale}")

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

    features.total_beats // 3
    2 * features.total_beats // 3

    half = features.total_beats // 2
    first_half_candidates = [b for b in sorted_by_score if b < half and b >= 64]
    second_half_candidates = [b for b in sorted_by_score if b >= half]

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
    cue6 - 32

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
