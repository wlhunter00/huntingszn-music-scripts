"""Clear Mixed In Key / Platinum Notes cue points written into Serato tags.

MIK stores phrase markers as Serato hot cues named like ``Energy 7``, plus a
``CuePoints`` GEOB frame and comments like ``9A - Energy 8``. Key, energy
level, beatgrid, and loops are left alone.

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
MIK_COMMENT = re.compile(r"^\d{1,2}[A-Ba-b]\s*-\s*Energy\s+\d+$", re.IGNORECASE)
CUEPOINTS_GEOB = "CuePoints"


def is_mik_cue_name(name: str) -> bool:
    return bool(MIK_CUE_NAME.match((name or "").strip()))


def is_mik_comment(text: str) -> bool:
    return bool(MIK_COMMENT.match((text or "").strip()))


def comment_text(frame) -> str:
    return " ".join(str(part) for part in (frame.text or [])).strip()


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


def mik_id3_extras(path: Path) -> tuple[bool, int]:
    """Return (has CuePoints GEOB, count of Mixed In Key comment frames)."""
    try:
        id3 = ID3(path)
    except (ID3NoHeaderError, Exception):
        return False, 0
    geob = any((frame.desc or "") == CUEPOINTS_GEOB for frame in id3.getall("GEOB"))
    comments = sum(1 for frame in id3.getall("COMM") if is_mik_comment(comment_text(frame)))
    return geob, comments


def strip_mik_id3_extras(path: Path) -> None:
    """Remove CuePoints GEOB and Mixed In Key comment frames in one save."""
    try:
        id3 = ID3(path)
    except (ID3NoHeaderError, Exception):
        return

    geobs = list(id3.getall("GEOB"))
    kept_geob = [frame for frame in geobs if (frame.desc or "") != CUEPOINTS_GEOB]
    comms = list(id3.getall("COMM"))
    kept_comm = [frame for frame in comms if not is_mik_comment(comment_text(frame))]

    changed = len(kept_geob) != len(geobs) or len(kept_comm) != len(comms)
    if not changed:
        return

    if len(kept_geob) != len(geobs):
        id3.delall("GEOB")
        for frame in kept_geob:
            id3.add(frame)
    if len(kept_comm) != len(comms):
        id3.delall("COMM")
        for frame in kept_comm:
            id3.add(frame)
    id3.save(path, v1=0)


def process_file(path: Path, *, dry_run: bool) -> str:
    """Process one file. Returns 'cleared', 'skipped', or 'error'."""
    if path.name.startswith("._"):
        return "skipped"
    if path.suffix.lower() not in SERATO_EXTENSIONS:
        return "skipped"

    mik_cues = 0
    tags = None
    try:
        tags = TrackCuesV2(str(path))
        mik_cues = count_mik_cues(tags)
    except Exception as exc:
        print(f"warning: Serato cues unread ({path}): {exc}")

    geob, comments = mik_id3_extras(path)
    if mik_cues == 0 and not geob and comments == 0:
        return "skipped"

    prefix = "[dry-run] " if dry_run else ""
    bits = []
    if mik_cues:
        bits.append(f"{mik_cues} Mixed In Key cue(s)")
    if geob:
        bits.append("CuePoints GEOB")
    if comments:
        bits.append(f"{comments} comment(s)")
    print(f"{prefix}cleared {', '.join(bits)}: {path}")

    if dry_run:
        return "cleared"

    try:
        if mik_cues and tags is not None:
            tags.modify_entries(clear_mik_cues_rule, delete_tags_v1=True)
            tags.save()
        if geob or comments:
            strip_mik_id3_extras(path)
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
            "hot cues, CuePoints GEOB, and '8A - Energy 7' comments). "
            "Keeps key, energy level, beatgrid, and loops."
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
