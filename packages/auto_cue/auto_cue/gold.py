"""Gold data loader for few-shot learning and evaluation.

Loads gold-labeled tracks from gold.csv and provides:
- Leave-one-out example selection
- Genre-based example grouping
- Full phrase table generation for examples
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_cue.llm import FewShotExample


@dataclass
class GoldTrack:
    """A gold-labeled track from gold.csv."""
    filename: str
    genre_bucket: str
    bpm: float
    first_beat_s: float
    total_beats: int = 0
    cues: dict[int, float] = field(default_factory=dict)  # slot (0-7) -> beat
    quirks: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Short display name."""
        return self.filename.replace(".mp3", "")


def load_gold_csv(csv_path: Path) -> dict[str, GoldTrack]:
    """Load gold tracks from gold.csv.

    Returns:
        Dict mapping filename -> GoldTrack
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
                genre_bucket=row.get("genre_bucket", ""),
                bpm=bpm,
                first_beat_s=first_beat_s,
                total_beats=total_beats,
                cues=cues,
                quirks=quirks,
            )
            tracks[filename] = track

    return tracks


def get_fewshot_examples(
    gold_tracks: dict[str, GoldTrack],
    exclude_filename: str,
    genre_bucket: str,
    audio_dir: Path,
    max_examples: int = 5,
) -> list[FewShotExample]:
    """Get few-shot examples for a track, excluding it (leave-one-out).

    Args:
        gold_tracks: Dict of all gold tracks
        exclude_filename: Filename to exclude (the track being evaluated)
        genre_bucket: Genre to match
        audio_dir: Directory containing audio files
        max_examples: Maximum number of examples to return

    Returns:
        List of FewShotExample with full phrase tables
    """
    from auto_cue.features import extract_features, format_phrase_table
    from auto_cue.llm import FewShotExample

    candidates = [
        t for fn, t in gold_tracks.items()
        if fn != exclude_filename and t.genre_bucket == genre_bucket
    ]

    if len(candidates) < max_examples:
        other_genres = [
            t for fn, t in gold_tracks.items()
            if fn != exclude_filename and t.genre_bucket != genre_bucket
        ]
        candidates.extend(other_genres[:max_examples - len(candidates)])

    examples: list[FewShotExample] = []
    for track in candidates[:max_examples]:
        audio_path = audio_dir / track.filename
        if not audio_path.exists():
            continue

        try:
            features = extract_features(
                audio_path,
                track.bpm,
                track.first_beat_s,
                genre_bucket=track.genre_bucket,
            )
            phrase_table = format_phrase_table(features)

            cues_int = {s: int(round(b)) for s, b in track.cues.items()}

            example = FewShotExample(
                name=track.name,
                genre_bucket=track.genre_bucket,
                bpm=track.bpm,
                total_beats=features.total_beats,
                phrase_table=phrase_table,
                cues=cues_int,
            )
            examples.append(example)
        except Exception:
            continue

    return examples


def infer_genre_bucket(bpm: float) -> str:
    """Infer genre bucket from BPM when not provided."""
    if bpm < 80:
        return "dubstep/bass"
    elif bpm < 100:
        return "dnb"
    else:
        return "house/dance"
