"""LLM-based cue picker for selecting all cue positions.

Uses an OpenAI model to pick all 8 cues with model judgment on each one:
- Cue 4 and 6 (drops) are primary picks
- Cues 1, 2, 7, 8 are also model-chosen from valid candidates (not just derived)
- Cues 3 and 5 are 16 or 32 beats before cue4/cue6 (run-up marker)
- Cue 4 anchors the intro lattice (16-beat); cue 6 anchors the outro lattice (32-beat)

Per-cue abstention: model may return null/unknown for any cue with confidence.
Dependencies: cue4 unknown -> cues 1-3 unknown; cue6 unknown -> cue5/7/8 unknown.
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
    """Raised when the predictor decides to abstain entirely (grid uncertainty only)."""
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

You are placing 8 hot cues on a DJ track. You may leave any cue as null/unknown 
if you're not confident - Will would rather have 3 good cues than 8 questionable ones.

## DROP DETECTION (PRIMARY TASK)
- **Cue 4** = FIRST DROP: Biggest energy jump. Look for highest kick density jump \
(Δkick) and contrast score. Usually beat 64-128.
- **Cue 6** = LAST DROP: Final big energy moment. Often the last high-scoring drop, \
96-192 beats after cue4. Single-drop tracks: cue6=cue4.

## RUN-UP CUES (16 or 32 beats before drop)
- **Cue 3** = cue4 - 16 OR cue4 - 32 (run-up before first drop). Use 16 for short \
buildups, 32 for longer ones.
- **Cue 5** = cue6 - 16 OR cue6 - 32 (run-up before last drop). Same logic.

## LATTICE RULES (CRITICAL)
- Cue 4 anchors the INTRO lattice (16-beat grid for cues 1, 2)
- Cue 6 anchors the OUTRO lattice (32-beat grid for cues 7, 8)
- **Cue 2**: Any multiple of 16 beats before cue3. Look for vocal entry or section start.
- **Cue 1**: At 0 OR same position as cue2 OR any 16-beat point before cue2. cue1 <= cue2.
- **Cue 7** = cue6 + 32 (preferred) or cue6 + 64. Look for outro/vocal fade.
- **Cue 8** = cue6 + 64 or cue6 + 96 (must be 32+ beats before track end)

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

## CRITICAL: TRANSITION vs SUSTAINED DROP POSITION
- **Transition point**: Where energy JUMPS (high Δkick, high Δlow) - this is the BUILD PEAK
- **Sustained point**: 16 beats AFTER transition where energy is HIGH but STEADY (low |Δlow|)
- **ALWAYS PREFER the SUSTAINED position** - that's where you mix IN
- If you see two candidates 16 beats apart, pick the LATER one with steady high energy
- Example: If beat 64 has Δlow=+10 and beat 80 has low=-20/Δlow=+2, pick beat 80

## BPM-BASED PATTERNS
- **bass (<80 BPM)**: cue1 at 0, drops ~64-96 beats apart, heavy kick patterns
- **dnb (80-100 BPM)**: cue1 at 0, drops ~96 beats apart, fast breaks
- **midtempo (100-115 BPM)**: mixed styles
- **house (115+ BPM)**: longer intros (64+ beats), drops ~192 beats apart

## PER-CUE CONFIDENCE
For each cue, report a confidence score (0.0-1.0):
- 0.9+ = very confident
- 0.7-0.9 = reasonably confident
- 0.5-0.7 = uncertain
- <0.5 = return null instead

If cue4 is null/unknown, cues 1-3 should also be null (they depend on cue4's lattice).
If cue6 is null/unknown, cue5 should also be null (and cue7/8 if anchored on cue6)."""

OPENAI_JSON_SCHEMA = {
    "name": "cue_prediction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "cue1_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 1 (intro), or null if uncertain",
            },
            "cue1_confidence": {
                "type": "number",
                "description": "Confidence for cue1 (0.0-1.0)",
            },
            "cue2_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 2 (pre-vocal), or null if uncertain",
            },
            "cue2_confidence": {
                "type": "number",
                "description": "Confidence for cue2 (0.0-1.0)",
            },
            "cue4_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 4 (FIRST DROP), or null if uncertain",
            },
            "cue4_confidence": {
                "type": "number",
                "description": "Confidence for cue4 (0.0-1.0)",
            },
            "cue6_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 6 (LAST DROP), or null if uncertain",
            },
            "cue6_confidence": {
                "type": "number",
                "description": "Confidence for cue6 (0.0-1.0)",
            },
            "cue7_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 7 (mix-out cue6+32/64), or null if uncertain",
            },
            "cue7_confidence": {
                "type": "number",
                "description": "Confidence for cue7 (0.0-1.0)",
            },
            "cue8_beat": {
                "type": ["integer", "null"],
                "description": "Beat for cue 8 (last call cue6+64/96), or null if uncertain",
            },
            "cue8_confidence": {
                "type": "number",
                "description": "Confidence for cue8 (0.0-1.0)",
            },
            "cue7_midsong": {
                "type": "boolean",
                "description": "True if cue7 is mid-song (rare)",
            },
            "rationale": {
                "type": "string",
                "description": "Brief reasoning for cue placement and any null cues",
            },
        },
        "required": [
            "cue1_beat", "cue1_confidence",
            "cue2_beat", "cue2_confidence",
            "cue4_beat", "cue4_confidence",
            "cue6_beat", "cue6_confidence",
            "cue7_beat", "cue7_confidence",
            "cue8_beat", "cue8_confidence",
            "cue7_midsong", "rationale",
        ],
        "additionalProperties": False,
    },
}


@dataclass
class CueConfidence:
    """Per-cue confidence and reason if unknown."""
    beat: int | None
    confidence: float
    reason: str = ""


@dataclass
class LLMPrediction:
    """Result from LLM cue prediction with per-cue confidence."""
    cue1: CueConfidence
    cue2: CueConfidence
    cue4: CueConfidence
    cue6: CueConfidence
    cue7: CueConfidence
    cue8: CueConfidence
    cue7_midsong: bool
    rationale: str
    raw_response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0

    @property
    def cue1_beat(self) -> int | None:
        return self.cue1.beat

    @property
    def cue2_beat(self) -> int | None:
        return self.cue2.beat

    @property
    def cue4_beat(self) -> int | None:
        return self.cue4.beat

    @property
    def cue6_beat(self) -> int | None:
        return self.cue6.beat

    @property
    def cue7_beat(self) -> int | None:
        return self.cue7.beat

    @property
    def cue8_beat(self) -> int | None:
        return self.cue8.beat

    @property
    def has_cue4(self) -> bool:
        return self.cue4.beat is not None

    @property
    def has_cue6(self) -> bool:
        return self.cue6.beat is not None


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
        LLMPrediction with all cue positions and per-cue confidence

    Raises:
        LLMAPIError: For API/auth/HTTP errors (should cause immediate failure)
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
    user_parts.append("Return your cue predictions in JSON format with per-cue confidence scores.")

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
    """Parse LLM JSON response with per-cue confidence.

    Raises:
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

    def parse_cue(slot: int) -> CueConfidence:
        beat_key = f"cue{slot}_beat"
        conf_key = f"cue{slot}_confidence"
        beat = data.get(beat_key)
        conf = float(data.get(conf_key, 0.5))
        return CueConfidence(
            beat=int(beat) if beat is not None else None,
            confidence=conf,
            reason="" if beat is not None else "model returned null",
        )

    return LLMPrediction(
        cue1=parse_cue(1),
        cue2=parse_cue(2),
        cue4=parse_cue(4),
        cue6=parse_cue(6),
        cue7=parse_cue(7),
        cue8=parse_cue(8),
        cue7_midsong=bool(data.get("cue7_midsong", False)),
        rationale=str(data.get("rationale", "")),
        raw_response=content,
    )


def _assess_drop_confidence(features: TrackFeatures) -> AbstainDecision:
    """Assess confidence in drop detection from audio features.

    Only used for GRID uncertainty (whole-song skip).
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

    if max_score < 1.0:
        decision.should_abstain = True
        decision.add_reason(f"very weak drop evidence (max_score={max_score:.1f} < 1.0)", 0.3)
        return decision

    return decision


def predict_cues_rules(features: TrackFeatures) -> LLMPrediction:
    """Rule-based fallback when LLM is not available.

    Returns prediction with per-cue confidence.
    """
    confidence_check = _assess_drop_confidence(features)

    if confidence_check.should_abstain:
        reasons = "; ".join(confidence_check.reasons)
        return LLMPrediction(
            cue1=CueConfidence(None, 0.0, reasons),
            cue2=CueConfidence(None, 0.0, reasons),
            cue4=CueConfidence(None, 0.0, reasons),
            cue6=CueConfidence(None, 0.0, reasons),
            cue7=CueConfidence(None, 0.0, reasons),
            cue8=CueConfidence(None, 0.0, reasons),
            cue7_midsong=False,
            rationale=f"abstained: {reasons}",
        )

    phrase_scores = {p.beat_start: p.drop_score for p in features.phrases if p.is_drop_candidate}
    max_score = max(phrase_scores.values()) if phrase_scores else 0

    candidates = [b for b in features.drop_candidates if b >= 64]
    if not candidates:
        candidates = features.drop_candidates

    if not candidates:
        return LLMPrediction(
            cue1=CueConfidence(None, 0.0, "no candidates"),
            cue2=CueConfidence(None, 0.0, "no candidates"),
            cue4=CueConfidence(None, 0.0, "no candidates"),
            cue6=CueConfidence(None, 0.0, "no candidates"),
            cue7=CueConfidence(None, 0.0, "no candidates"),
            cue8=CueConfidence(None, 0.0, "no candidates"),
            cue7_midsong=False,
            rationale="no valid drop candidates",
        )

    sorted_by_score = sorted(candidates, key=lambda b: phrase_scores.get(b, 0), reverse=True)

    half = features.total_beats // 2
    first_half_candidates = [b for b in sorted_by_score if b < half and b >= 64]
    second_half_candidates = [b for b in sorted_by_score if b >= half]

    if first_half_candidates:
        cue4 = first_half_candidates[0]
    elif sorted_by_score:
        cue4 = sorted_by_score[0]
    else:
        cue4 = None

    if second_half_candidates:
        cue6 = second_half_candidates[0]
    elif cue4:
        later_candidates = [b for b in sorted_by_score if b > cue4]
        cue6 = later_candidates[0] if later_candidates else cue4
    else:
        cue6 = None

    cue4_score = phrase_scores.get(cue4, 0) if cue4 else 0
    cue6_score = phrase_scores.get(cue6, 0) if cue6 else 0

    cue4_conf = min(0.9, cue4_score / max_score) if max_score > 0 and cue4 else 0.3
    cue6_conf = min(0.9, cue6_score / max_score) if max_score > 0 and cue6 else 0.3

    if cue4 is None:
        return LLMPrediction(
            cue1=CueConfidence(None, 0.0, "no cue4"),
            cue2=CueConfidence(None, 0.0, "no cue4"),
            cue4=CueConfidence(None, 0.0, "no first drop candidate"),
            cue6=CueConfidence(cue6, cue6_conf) if cue6 else CueConfidence(None, 0.0, "no drop"),
            cue7=CueConfidence(None, 0.0, "no cue6") if not cue6 else CueConfidence(cue6 + 32, 0.6),
            cue8=CueConfidence(None, 0.0, "no cue6") if not cue6 else CueConfidence(cue6 + 64, 0.6),
            cue7_midsong=False,
            rationale="no first drop candidate",
        )

    if cue6 is not None and cue6 < cue4:
        cue6 = cue4

    is_bass_music = features.bpm < 100

    cue3 = cue4 - 32
    cue5 = cue6 - 32 if cue6 else None

    if is_bass_music:
        cue2 = cue3 - 16
        cue1 = 0
    else:
        cue2 = cue3 - 48
        if cue2 < 16:
            cue2 = cue3 - 16
        cue1 = cue4 - 128
        if cue1 < 0:
            cue1 = cue4 - 64
        if cue1 < 0:
            cue1 = 0

    if cue1 > cue2:
        cue1 = max(0, cue2 - 16)
    if cue1 > cue2:
        cue1 = cue2
    if cue2 <= 0:
        cue2 = cue3
        cue1 = cue2

    if cue2 > cue3:
        cue2 = cue3
        if cue1 > cue2:
            cue1 = cue2

    cue7 = cue6 + 32 if cue6 else None
    cue8 = cue6 + 64 if cue6 else None

    if cue8 and cue8 > features.total_beats - 8:
        cue8 = cue6 + 32 if cue6 else None

    return LLMPrediction(
        cue1=CueConfidence(cue1, 0.7),
        cue2=CueConfidence(cue2, 0.7),
        cue4=CueConfidence(cue4, cue4_conf),
        cue6=CueConfidence(cue6, cue6_conf) if cue6 else CueConfidence(None, 0.0, "single drop"),
        cue7=CueConfidence(cue7, 0.6) if cue7 else CueConfidence(None, 0.0, "no cue6"),
        cue8=CueConfidence(cue8, 0.6) if cue8 else CueConfidence(None, 0.0, "no cue6"),
        cue7_midsong=False,
        rationale="rule-based",
    )


def prediction_to_cue_set(
    prediction: LLMPrediction,
    total_beats: int,
    *,
    cue4_threshold: float = 0.5,
    cue6_threshold: float = 0.5,
    other_threshold: float = 0.4,
) -> CueSet:
    """Convert LLM prediction to a CueSet, applying confidence thresholds.

    Per-cue abstention:
    - If cue4 is below threshold or null, cues 1-3 also become null
    - If cue6 is below threshold or null, cue5 becomes null; cue7/8 if anchored on cue6

    Lattice rules applied for derived cues (cue3, cue5).

    Args:
        prediction: LLM prediction with per-cue confidence
        total_beats: Total beats in track
        cue4_threshold: Confidence threshold for cue4 (default 0.5)
        cue6_threshold: Confidence threshold for cue6 (default 0.5)
        other_threshold: Confidence threshold for other cues (default 0.4)

    Returns:
        CueSet with only confident cues filled, others None
    """
    cues = CueSet(total_beats=total_beats, cue7_midsong=prediction.cue7_midsong)
    cues.confidences = {}

    # Process cue4 first (anchor for cues 1-3)
    cue4_valid = (
        prediction.cue4.beat is not None
        and prediction.cue4.confidence >= cue4_threshold
    )

    if cue4_valid:
        cues.cue4 = prediction.cue4.beat
        cues.confidences[4] = prediction.cue4.confidence

        # Derive cue3 from cue4
        if prediction.cue4.beat >= 32:
            cues.cue3 = prediction.cue4.beat - 32
        elif prediction.cue4.beat >= 16:
            cues.cue3 = prediction.cue4.beat - 16
        else:
            cues.cue3 = prediction.cue4.beat
        cues.confidences[3] = prediction.cue4.confidence * 0.95

        # Process cue2
        if prediction.cue2.beat is not None and prediction.cue2.confidence >= other_threshold:
            offset = (prediction.cue4.beat - prediction.cue2.beat) % 16
            if offset != 0:
                k = round((prediction.cue4.beat - prediction.cue2.beat) / 16)
                cues.cue2 = prediction.cue4.beat - k * 16
            else:
                cues.cue2 = prediction.cue2.beat
            if cues.cue2 < 0:
                cues.cue2 = 0
            if cues.cue2 > cues.cue3:
                cues.cue2 = cues.cue3
            cues.confidences[2] = prediction.cue2.confidence

        # Process cue1
        if prediction.cue1.beat is not None and prediction.cue1.confidence >= other_threshold:
            offset = (prediction.cue4.beat - prediction.cue1.beat) % 16
            if offset != 0:
                k = round((prediction.cue4.beat - prediction.cue1.beat) / 16)
                cues.cue1 = prediction.cue4.beat - k * 16
            else:
                cues.cue1 = prediction.cue1.beat
            if cues.cue1 < 0:
                cues.cue1 = 0
            if cues.cue2 is not None and cues.cue1 > cues.cue2:
                cues.cue1 = cues.cue2
            cues.confidences[1] = prediction.cue1.confidence

    # Process cue6 (anchor for cue5, and optionally cue7/8)
    cue6_valid = (
        prediction.cue6.beat is not None
        and prediction.cue6.confidence >= cue6_threshold
    )

    if cue6_valid:
        cues.cue6 = prediction.cue6.beat
        cues.confidences[6] = prediction.cue6.confidence

        # Ensure cue6 >= cue4
        if cues.cue4 is not None and cues.cue6 < cues.cue4:
            cues.cue6 = cues.cue4

        # Derive cue5 from cue6
        if prediction.cue6.beat >= 32:
            cues.cue5 = prediction.cue6.beat - 32
        elif prediction.cue6.beat >= 16:
            cues.cue5 = prediction.cue6.beat - 16
        else:
            cues.cue5 = prediction.cue6.beat
        cues.confidences[5] = prediction.cue6.confidence * 0.95

        # Check cue5 ordering: cue5 must be >= cue4
        if cues.cue4 is not None and cues.cue5 is not None and cues.cue5 < cues.cue4:
            # Try 16-beat gap instead
            if prediction.cue6.beat - 16 >= cues.cue4:
                cues.cue5 = prediction.cue6.beat - 16
            else:
                # Single drop - cue5 at same position or null
                cues.cue5 = None

        # Process cue7 (on cue6's lattice)
        if prediction.cue7.beat is not None and prediction.cue7.confidence >= other_threshold:
            cue7_offset = prediction.cue7.beat - prediction.cue6.beat
            if cue7_offset % 32 != 0:
                k = max(1, round(cue7_offset / 32))
                cues.cue7 = prediction.cue6.beat + k * 32
            else:
                cues.cue7 = prediction.cue7.beat
            cues.confidences[7] = prediction.cue7.confidence
        else:
            # Default: cue6 + 32
            cues.cue7 = cues.cue6 + 32
            cues.confidences[7] = prediction.cue6.confidence * 0.8

        # Process cue8 (on cue6's lattice)
        if prediction.cue8.beat is not None and prediction.cue8.confidence >= other_threshold:
            cue8_offset = prediction.cue8.beat - prediction.cue6.beat
            if cue8_offset % 32 != 0:
                k = max(1, round(cue8_offset / 32))
                cues.cue8 = prediction.cue6.beat + k * 32
            else:
                cues.cue8 = prediction.cue8.beat
            cues.confidences[8] = prediction.cue8.confidence
        else:
            # Default: cue6 + 64
            cues.cue8 = cues.cue6 + 64
            cues.confidences[8] = prediction.cue6.confidence * 0.7

        # Ensure cue8 not too close to end
        if cues.cue8 > total_beats - 8:
            max_cue8 = total_beats - 8
            k = max(1, (max_cue8 - cues.cue6) // 32)
            cues.cue8 = cues.cue6 + k * 32

        if cues.cue8 <= cues.cue7:
            cues.cue8 = cues.cue7

    return cues
