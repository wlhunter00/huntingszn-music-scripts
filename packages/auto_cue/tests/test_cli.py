"""End-to-end CLI tests.

Tests:
- Dry-run mode doesn't modify files
- --write mode creates backups and writes cues
- Tag dumps before/after
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from auto_cue.cli import process_track
from auto_cue.tags import Markers2Data, cues_to_beats, read_track_tags, write_track_markers2


class TestCLIDryRun:
    """Test dry-run behavior."""

    def test_dryrun_does_not_modify(self, sample_mp3: Path):
        """Dry-run should not modify files."""
        original_bytes = sample_mp3.read_bytes()

        result = process_track(sample_mp3, write=False, use_llm=False)

        new_bytes = sample_mp3.read_bytes()
        assert original_bytes == new_bytes
        assert result.action != "write"

    def test_skip_on_human_cues(self, sample_mp3: Path):
        """Should skip files with human cues."""
        from auto_cue.tags import CuePoint, Markers2Data, write_track_beatgrid, write_track_markers2
        from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker

        markers = Markers2Data(
            cues=[CuePoint(index=0, position_ms=1000, name="")]
        )
        write_track_markers2(sample_mp3, markers)

        grid = BeatGrid(markers=(TerminalMarker(position_s=0.1, bpm=128.0),))
        write_track_beatgrid(sample_mp3, grid)

        result = process_track(sample_mp3, write=False, use_llm=False)

        assert result.action.startswith("skip")


class TestCLIWriteMode:
    """Test write mode behavior."""

    def test_write_creates_backup(self, sample_mp3: Path, temp_dir: Path):
        """Write mode should create backups."""
        from auto_cue.tags import write_track_beatgrid
        from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker

        grid = BeatGrid(markers=(TerminalMarker(position_s=0.1, bpm=128.0),))
        write_track_beatgrid(sample_mp3, grid)

        backup_dir = temp_dir / "backups"

        result = process_track(
            sample_mp3,
            write=True,
            use_llm=False,
            backup_root=backup_dir,
        )

        if result.action == "write":
            backups = list(backup_dir.rglob("*.mp3"))
            assert len(backups) > 0, "Backup should be created"


class TestTagDumps:
    """Test tag dump functionality for QA."""

    def test_dump_qa_tags(self, qa_songs_dir: Path | None, temp_dir: Path):
        """Dump tags from QA songs for inspection."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")

        dump_path = temp_dir / "tag_dumps.json"
        dumps = []

        for mp3 in sorted(qa_songs_dir.glob("*.mp3")):
            tags = read_track_tags(mp3)

            dump = {
                "file": mp3.name,
                "format": tags.format,
                "error": tags.error,
                "has_grid": tags.has_grid,
                "bpm": tags.bpm,
                "first_beat_s": tags.first_beat_s,
            }

            if tags.markers2:
                dump["cues"] = [
                    {
                        "index": c.index,
                        "position_ms": c.position_ms,
                        "name": c.name,
                        "color": c.color_hex,
                    }
                    for c in tags.markers2.cues
                ]
                dump["bpm_lock"] = tags.markers2.bpm_lock
                dump["loops"] = len(tags.markers2.loops)
                dump["flips"] = len(tags.markers2.flip_entries)

                if tags.beatgrid:
                    dump["cue_beats"] = cues_to_beats(tags.markers2, tags.beatgrid)

            if tags.beatgrid:
                dump["grid_constant"] = tags.beatgrid.is_constant
                dump["grid_dynamic"] = tags.beatgrid.is_dynamic

            dumps.append(dump)

            print(f"\n=== {mp3.name} ===")
            print(f"BPM: {tags.bpm}, First beat: {tags.first_beat_s:.3f}s")
            if tags.markers2:
                print(f"Cues: {len(tags.markers2.cues)}, Loops: {len(tags.markers2.loops)}")
                for c in tags.markers2.cues:
                    beat = None
                    if tags.beatgrid and tags.bpm:
                        beat = (c.position_ms - tags.first_beat_s * 1000) / (60000.0 / tags.bpm)
                    beat_str = f" ({beat:.1f} beats)" if beat is not None else ""
                    print(f"  Cue {c.index+1}: {c.position_ms}ms{beat_str} name=\"{c.name}\"")

        with open(dump_path, "w") as f:
            json.dump(dumps, f, indent=2)

        print(f"\nTag dumps written to: {dump_path}")

    def test_blind_prediction_with_dump(
        self,
        qa_songs_dir: Path | None,
        temp_dir: Path,
    ):
        """Run blind prediction and dump before/after tags."""
        if qa_songs_dir is None:
            pytest.skip("QA songs not available")

        results = []

        for mp3 in sorted(qa_songs_dir.glob("*.mp3")):
            copy_path = temp_dir / mp3.name
            shutil.copy2(mp3, copy_path)

            before_tags = read_track_tags(copy_path)

            before = {
                "file": mp3.name,
                "cues": [],
            }
            if before_tags.markers2 and before_tags.beatgrid:
                first_beat_ms = before_tags.first_beat_s * 1000
                ms_per_beat = 60000.0 / before_tags.bpm
                before["cues"] = [
                    {
                        "index": c.index,
                        "beat": round((c.position_ms - first_beat_ms) / ms_per_beat, 1),
                        "name": c.name,
                    }
                    for c in before_tags.markers2.cues
                ]

            empty_markers = Markers2Data()
            write_track_markers2(copy_path, empty_markers)

            result = process_track(
                copy_path,
                write=True,
                use_llm=False,
                backup_root=temp_dir / "backups",
            )

            after_tags = read_track_tags(copy_path)

            after = {
                "file": mp3.name,
                "action": result.action,
                "cues": [],
            }
            if after_tags.markers2 and after_tags.beatgrid:
                first_beat_ms = after_tags.first_beat_s * 1000
                ms_per_beat = 60000.0 / after_tags.bpm
                after["cues"] = [
                    {
                        "index": c.index,
                        "beat": round((c.position_ms - first_beat_ms) / ms_per_beat, 1),
                    }
                    for c in after_tags.markers2.cues
                ]

            results.append({
                "file": mp3.name,
                "action": result.action,
                "before": before["cues"],
                "after": after["cues"],
                "predicted_beats": result.cues_set,
            })

            print(f"\n=== {mp3.name} ===")
            print(f"Action: {result.action}")
            print(f"Before (gold): {before['cues']}")
            print(f"After (predicted): {after['cues']}")
            if result.cues_set:
                print(f"Predicted beats: {result.cues_set}")

        dump_path = temp_dir / "before_after.json"
        with open(dump_path, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\nBefore/after dumps written to: {dump_path}")
