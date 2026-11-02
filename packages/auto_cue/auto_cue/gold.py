"""Gold data loader for few-shot learning and evaluation.

Loads gold-labeled tracks from gold.csv and provides:
- Leave-one-out example selection
- BPM/length-based similarity matching (no genre metadata)
- Full phrase table generation for examples
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_cue.features import TrackFeatures
    from auto_cue.llm import FewShotExample

EXCLUDED_TRACKS = {"qa06.mp3", "qa25.mp3", "qa32.mp3"}


@dataclass
class GoldTrack:
    """A gold-labeled track from gold.csv."""
    filename: str
    bpm: float
    first_beat_s: float
    total_beats: int = 0
    duration_s: float = 0.0
    cues: dict[int, float] = field(default_factory=dict)  # slot (0-7) -> beat
    quirks: list[str] = field(default_factory=list)
    excluded: bool = False  # True for tracks with bad tags

    @property
    def name(self) -> str:
        """Short display name."""
        return self.filename.replace(".mp3", "")

    @property
    def bpm_band(self) -> str:
        """BPM-based genre proxy."""
        if self.bpm < 80:
            return "bass (<80)"
        elif self.bpm < 100:
            return "dnb (80-100)"
        elif self.bpm < 115:
            return "midtempo (100-115)"
        else:
            return "house (115+)"


def load_gold_csv(
    csv_path: Path,
    exclude_bad: bool = True,
) -> dict[str, GoldTrack]:
    """Load gold tracks from gold.csv.

    Args:
        csv_path: Path to gold.csv
        exclude_bad: If True, exclude tracks with known bad tags

    Returns:
        Dict mapping filename -> GoldTrack (excludes bad tracks if exclude_bad)
    """
    tracks: dict[str, GoldTrack] = {}

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row["small_file"]
            bpm = float(row["serato_bpm"])
            first_beat_s = float(row["first_beat_s"])

            cues: dict[int, float] = {}
            for slot in range(8):
                col = f"cue{slot+1}_beat"
                if col in row and row[col]:
                    try:
                        cues[slot] = float(row[col])
                    except ValueError:
                        pass

            quirks: list[str] = []
            excluded = filename in EXCLUDED_TRACKS
            if filename == "qa06.mp3":
                quirks.append("off-grid cues (.58 beats)")
            elif filename == "qa25.mp3":
                quirks.append("cue4 at beat 0")
            elif filename == "qa32.mp3":
                quirks.append("single drop (cue4==cue6)")
            elif filename in ("qa09.mp3", "qa13.mp3"):
                quirks.append("early last drop")
            elif filename == "qa38.mp3":
                quirks.append("Will's own production")

            dur_s = float(row.get("dur_small_s", 0) or row.get("dur_orig_s", 0))
            total_beats = int((dur_s - first_beat_s) * bpm / 60) if dur_s > 0 else 0

            track = GoldTrack(
                filename=filename,
                bpm=bpm,
                first_beat_s=first_beat_s,
                total_beats=total_beats,
                duration_s=dur_s,
                cues=cues,
                quirks=quirks,
                excluded=excluded,
            )

            if exclude_bad and excluded:
                continue

            tracks[filename] = track

    return tracks


def compute_track_similarity(
    target_bpm: float,
    target_beats: int,
    candidate: GoldTrack,
) -> float:
    """Compute similarity score between target and candidate track.

    Uses BPM (primary) and length (secondary) as matching criteria.
    Lower score = more similar.
    """
    bpm_diff = abs(target_bpm - candidate.bpm)
    bpm_score = bpm_diff / 10.0  # 10 BPM diff = 1.0 penalty

    beats_diff = abs(target_beats - candidate.total_beats)
    beats_score = beats_diff / 100.0  # 100 beat diff = 1.0 penalty

    return bpm_score + 0.3 * beats_score


def get_fewshot_examples_by_similarity(
    gold_tracks: dict[str, GoldTrack],
    exclude_filename: str,
    target_bpm: float,
    target_beats: int,
    audio_dir: Path,
    max_examples: int = 5,
    features_cache: dict[str, TrackFeatures] | None = None,
) -> list[FewShotExample]:
    """Get k-nearest few-shot examples by BPM/length similarity.

    Args:
        gold_tracks: Dict of all gold tracks
        exclude_filename: Filename to exclude (leave-one-out)
        target_bpm: BPM of target track
        target_beats: Total beats of target track
        audio_dir: Directory containing audio files
        max_examples: Maximum number of examples to return
        features_cache: Optional cache for extracted features

    Returns:
        List of FewShotExample sorted by similarity (most similar first)
    """
    from auto_cue.features import extract_features, format_phrase_table
    from auto_cue.llm import FewShotExample

    if features_cache is None:
        features_cache = {}

    candidates = [
        (fn, t, compute_track_similarity(target_bpm, target_beats, t))
        for fn, t in gold_tracks.items()
        if fn != exclude_filename and not t.excluded
    ]

    candidates.sort(key=lambda x: x[2])

    examples: list[FewShotExample] = []
    for filename, track, _score in candidates[:max_examples * 2]:
        if len(examples) >= max_examples:
            break

        audio_path = audio_dir / track.filename
        if not audio_path.exists():
            continue

        try:
            if filename in features_cache:
                features = features_cache[filename]
            else:
                features = extract_features(
                    audio_path,
                    track.bpm,
                    track.first_beat_s,
                )
                features_cache[filename] = features

            phrase_table = format_phrase_table(features)
            cues_int = {s: int(round(b)) for s, b in track.cues.items()}

            example = FewShotExample(
                name=track.name,
                genre_bucket=track.bpm_band,
                bpm=track.bpm,
                total_beats=features.total_beats,
                phrase_table=phrase_table,
                cues=cues_int,
            )
            examples.append(example)
        except Exception:
            continue

    return examples


def get_fewshot_examples(
    gold_tracks: dict[str, GoldTrack],
    exclude_filename: str,
    target_bpm: float,
    target_beats: int,
    audio_dir: Path,
    max_examples: int = 5,
    features_cache: dict[str, TrackFeatures] | None = None,
) -> list[FewShotExample]:
    """Alias for get_fewshot_examples_by_similarity."""
    return get_fewshot_examples_by_similarity(
        gold_tracks=gold_tracks,
        exclude_filename=exclude_filename,
        target_bpm=target_bpm,
        target_beats=target_beats,
        audio_dir=audio_dir,
        max_examples=max_examples,
        features_cache=features_cache,
    )
