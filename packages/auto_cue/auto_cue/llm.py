"""LLM-based cue picker for selecting drop positions.

Uses a Haiku-class model to pick cue4 (first drop) and cue6 (last drop)
from the drop candidates, then derives the other cues deterministically.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from auto_cue.features import TrackFeatures, format_phrase_table
from auto_cue.validate import CueSet, build_cues_deterministic

RULE_CARD = """
# Will's Serato cue system

You are helping set 8 hot cues for a DJ track. The cues mark structural points:

## Slot meanings
- Cue 4: FIRST DROP (the main drop, set first)
- Cue 3: Buildup start (cue4 - 32 beats)
- Cue 2: Transition end point, often before vocals (cue3 - 32, 64, or 96 beats)
- Cue 1: Intro/cue-in point near the start (usually beat 0 or first 32-beat boundary)
- Cue 6: LAST DROP (hardest call - may be same as cue4 for single-drop tracks)
- Cue 5: Build into last drop (cue6 - 32 beats)
- Cue 7: First mix-out point (usually cue6 + 32, but can be mid-song if short outro)
- Cue 8: "Last call" (~32-48 beats before track ends)

## Rules
- Cues 1-4 sit on a 32-beat lattice anchored at cue4
- Cues 5-8 sit on a 32-beat lattice anchored at cue6
- Cue6 - cue4 is NOT always a multiple of 32
- Pick drops by energy increase: look for delta_rms and delta_low jumps after buildups
- Bass music (dubstep, DnB, trap ~70-87 BPM) has tighter structure: cue4→cue6 ≈ 96 beats
- House/pop (~126 BPM) has wider gaps: cue4→cue6 ≈ 192 beats
- If uncertain, ABSTAIN rather than guess wrong

## Output format
Return JSON only:
{
  "cue4_beat": <int>,
  "cue6_beat": <int>,
  "cue2_offset": 32 | 64 | 96,
  "cue1_at_start": true | false,
  "cue7_midsong": false,
  "confidence_cue4": 0.0-1.0,
  "confidence_cue6": 0.0-1.0,
  "rationale": "<1 line>"
}
"""


@dataclass
class LLMPrediction:
    """Result from LLM cue prediction."""
    cue4_beat: int
    cue6_beat: int
    cue2_offset: int
    cue1_at_start: bool
    cue7_midsong: bool
    confidence_cue4: float
    confidence_cue6: float
    rationale: str
    raw_response: str = ""


def get_api_key() -> str:
    """Get Anthropic API key from environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return key


def predict_cues_llm(
    features: TrackFeatures,
    *,
    model: str = "claude-3-haiku-20240307",
    style: str | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> LLMPrediction:
    """Use LLM to predict cue4 and cue6 positions.
    
    Args:
        features: Extracted audio features
        model: Model name (default Haiku)
        style: Track style hint (e.g., "dubstep", "house")
        examples: Few-shot examples from gold tracks
    
    Returns:
        LLMPrediction with cue positions and confidence
    """
    phrase_table = format_phrase_table(features)
    
    prompt_parts = [RULE_CARD, "", "## This track", ""]
    
    if style:
        prompt_parts.append(f"Style: {style}")
    
    prompt_parts.append(phrase_table)
    
    if examples:
        prompt_parts.append("")
        prompt_parts.append("## Similar gold tracks (for reference)")
        for ex in examples[:3]:
            prompt_parts.append(f"- {ex.get('name', 'track')}: cue4={ex.get('cue4')}, cue6={ex.get('cue6')}")
    
    prompt_parts.append("")
    prompt_parts.append("Pick cue4 and cue6 from the drop candidates. Return JSON only.")
    
    user_prompt = "\n".join(prompt_parts)
    
    api_key = get_api_key()
    
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 512,
                "temperature": 0,
                "messages": [
                    {"role": "user", "content": user_prompt}
                ],
            },
        )
        response.raise_for_status()
        result = response.json()
    
    content = result["content"][0]["text"]
    
    return _parse_llm_response(content, features)


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
    
    cue4 = data.get("cue4_beat")
    cue6 = data.get("cue6_beat")
    
    if cue4 is None or cue6 is None:
        raise ValueError("LLM response missing cue4_beat or cue6_beat")
    
    return LLMPrediction(
        cue4_beat=int(cue4),
        cue6_beat=int(cue6),
        cue2_offset=int(data.get("cue2_offset", 32)),
        cue1_at_start=bool(data.get("cue1_at_start", True)),
        cue7_midsong=bool(data.get("cue7_midsong", False)),
        confidence_cue4=float(data.get("confidence_cue4", 0.8)),
        confidence_cue6=float(data.get("confidence_cue6", 0.8)),
        rationale=str(data.get("rationale", "")),
        raw_response=content,
    )


def predict_cues_rules(features: TrackFeatures) -> LLMPrediction:
    """Rule-based fallback when LLM is not available.
    
    Simple heuristic:
    - cue4 = highest scoring drop candidate in first half
    - cue6 = highest scoring drop candidate in second half (or last overall)
    """
    if not features.drop_candidates:
        raise ValueError("No drop candidates found")
    
    mid = features.total_beats // 2
    
    first_half = [b for b in features.drop_candidates if b < mid]
    second_half = [b for b in features.drop_candidates if b >= mid]
    
    if first_half:
        cue4 = first_half[0]
    else:
        cue4 = features.drop_candidates[0]
    
    if second_half:
        cue6 = second_half[0]
    else:
        cue6 = features.drop_candidates[-1] if len(features.drop_candidates) > 1 else cue4
    
    if cue6 < cue4:
        cue6 = cue4
    
    is_bass_music = features.bpm < 100
    
    return LLMPrediction(
        cue4_beat=cue4,
        cue6_beat=cue6,
        cue2_offset=32 if is_bass_music else 64,
        cue1_at_start=is_bass_music,
        cue7_midsong=False,
        confidence_cue4=0.7,
        confidence_cue6=0.6,
        rationale="rule-based: top drop candidates by energy delta",
        raw_response="",
    )


def prediction_to_cue_set(
    prediction: LLMPrediction,
    total_beats: int,
) -> CueSet:
    """Convert LLM prediction to a complete CueSet."""
    cues = build_cues_deterministic(
        cue4=prediction.cue4_beat,
        cue6=prediction.cue6_beat,
        total_beats=total_beats,
        cue1_at_start=prediction.cue1_at_start,
        cue2_offset=prediction.cue2_offset,
        cue7_midsong=prediction.cue7_midsong,
    )
    
    cues.confidences = {
        4: prediction.confidence_cue4,
        6: prediction.confidence_cue6,
        1: 0.9,
        2: 0.8,
        3: 0.95,
        5: 0.95,
        7: 0.8,
        8: 0.8,
    }
    
    return cues
