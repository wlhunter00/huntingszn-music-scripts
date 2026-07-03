"""Strip Serato hot cue points from embedded audio metadata.

Close Serato DJ before running — it can write in-memory cues back to files on exit.
After running, rescan or re-import affected tracks in Serato so the library matches file tags.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

from serato_tools.track_cues_v2 import TrackCuesV2

from config.paths import DJ_SOUNDCLOUD_NUKE

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg", ".aiff", ".aif"}
SERATO_EXTENSIONS = {".mp3", ".aiff", ".aif"}


def clear_cues_rule(track: TrackCuesV2.TrackCuesInfo) -> TrackCuesV2.TrackCuesInfo | None:
    """Return a copy with empty cues, or None if already cue-free."""
    if not track.cues:
        return None
    return dataclasses.replace(track, cues=[])


def iter_audio_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            yield path


def count_cues(tags: TrackCuesV2) -> int:
    return sum(1 for entry in tags.entries if isinstance(entry, TrackCuesV2.CueEntry))


def process_file(path: Path, *, dry_run: bool) -> str:
    """Process one file. Returns 'cleared', 'skipped', or 'error'."""
    if path.suffix.lower() not in SERATO_EXTENSIONS:
        return "skipped"

    try:
        tags = TrackCuesV2(str(path))
    except Exception as exc:
        print(f"error reading {path}: {exc}")
        return "error"

    cue_count = count_cues(tags)
    if cue_count == 0:
        return "skipped"

    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}{cue_count} cue(s) cleared: {path}")

    if dry_run:
        return "cleared"

    try:
        tags.modify_entries(clear_cues_rule, delete_tags_v1=True)
        tags.save()
    except Exception as exc:
        print(f"error saving {path}: {exc}")
        return "error"

    return "cleared"


def process_folder(root: Path, *, dry_run: bool) -> tuple[int, int, int]:
    cleared = skipped = errors = 0
    for path in iter_audio_files(root):
        result = process_file(path, dry_run=dry_run)
        if result == "cleared":
            cleared += 1
        elif result == "error":
            errors += 1
        else:
            skipped += 1
    return cleared, skipped, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove Serato hot cue points from audio files (keeps loops and beatgrid)."
    )
    parser.add_argument("--root", type=Path, default=DJ_SOUNDCLOUD_NUKE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")

    cleared, skipped, errors = process_folder(args.root, dry_run=args.dry_run)
    label = "Would clear" if args.dry_run else "Cleared"
    print(f"{label} {cleared} file(s), skipped {skipped}, errors {errors}.")


if __name__ == "__main__":
    main()
