"""Clear Mixed In Key / Platinum Notes cue points written into Serato tags.

MIK stores phrase markers as Serato hot cues named like ``Energy 7``, plus a
``CuePoints`` GEOB frame. Key, energy level, beatgrid, and loops are left alone.

Close Serato DJ before running. MP3/AIFF only for Serato Markers2.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError
from serato_tools.track_cues_v2 import TrackCuesV2

from library_tools.serato_clear_cues import SERATO_EXTENSIONS, iter_audio_files

MIK_CUE_NAME = re.compile(r"^Energy\s+\d+$", re.IGNORECASE)
CUEPOINTS_GEOB = "CuePoints"


def is_mik_cue_name(name: str) -> bool:
    return bool(MIK_CUE_NAME.match((name or "").strip()))


def clear_mik_cues_rule(track: TrackCuesV2.TrackCuesInfo) -> TrackCuesV2.TrackCuesInfo | None:
    """Drop Energy-named hot cues; keep other cues, loops, and flips."""
    kept = [cue for cue in track.cues if not is_mik_cue_name(cue.name)]
    if len(kept) == len(track.cues):
        return None
    return dataclasses.replace(track, cues=kept)


def count_mik_cues(tags: TrackCuesV2) -> int:
    return sum(
        1
        for entry in tags.entries
        if isinstance(entry, TrackCuesV2.CueEntry) and is_mik_cue_name(entry.name)
    )


def has_cuepoints_geob(path: Path) -> bool:
    try:
        id3 = ID3(path)
    except (ID3NoHeaderError, Exception):
        return False
    return any((frame.desc or "") == CUEPOINTS_GEOB for frame in id3.getall("GEOB"))


def strip_cuepoints_geob(path: Path) -> bool:
    """Remove the Platinum Notes/MIK CuePoints GEOB. Returns True if a frame was dropped."""
    try:
        id3 = ID3(path)
    except (ID3NoHeaderError, Exception):
        return False
    geobs = list(id3.getall("GEOB"))
    kept = [frame for frame in geobs if (frame.desc or "") != CUEPOINTS_GEOB]
    if len(kept) == len(geobs):
        return False
    id3.delall("GEOB")
    for frame in kept:
        id3.add(frame)
    id3.save(path)
    return True


def process_file(path: Path, *, dry_run: bool) -> str:
    """Process one file. Returns 'cleared', 'skipped', or 'error'."""
    if path.name.startswith("._"):
        return "skipped"
    if path.suffix.lower() not in SERATO_EXTENSIONS:
        return "skipped"

    mik_cues = 0
    try:
        tags = TrackCuesV2(str(path))
        mik_cues = count_mik_cues(tags)
    except Exception as exc:
        print(f"error reading {path}: {exc}")
        return "error"

    geob = has_cuepoints_geob(path)
    if mik_cues == 0 and not geob:
        return "skipped"

    prefix = "[dry-run] " if dry_run else ""
    bits = []
    if mik_cues:
        bits.append(f"{mik_cues} Mixed In Key cue(s)")
    if geob:
        bits.append("CuePoints GEOB")
    print(f"{prefix}cleared {', '.join(bits)}: {path}")

    if dry_run:
        return "cleared"

    try:
        if mik_cues:
            tags.modify_entries(clear_mik_cues_rule, delete_tags_v1=True)
            tags.save()
        if geob:
            strip_cuepoints_geob(path)
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
        description=(
            "Remove Mixed In Key / Platinum Notes cue points (Energy-named Serato "
            "hot cues + CuePoints GEOB). Keeps key, energy level, beatgrid, and loops."
        )
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Folder to process (required). Only this directory tree is touched.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")
    cleared, skipped, errors = process_folder(args.root, dry_run=args.dry_run)
    label = "Would clear" if args.dry_run else "Cleared"
    print(f"{label} {cleared} file(s), skipped {skipped}, errors {errors}.")


if __name__ == "__main__":
    main()
