"""Embed chosen release artwork into HuntingSzn MP3s.

Looks for images named ``final`` (or ending in ``-final`` / ``_final``) under
``Thumbnails/Releases``, matches each release folder to MP3s in
``DJ Music/HuntingSzn``, and writes an ID3 APIC front cover.

Picking the image is still a human step. This only attaches files you already
marked as final.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import APIC, ID3, ID3NoHeaderError

from config.paths import DJ_HUNTINGSZN, THUMBNAILS_RELEASES

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
AUDIO_EXTS = {".mp3"}
STOP_WORDS = {
    "a",
    "and",
    "at",
    "edit",
    "flip",
    "for",
    "huntingszn",
    "in",
    "is",
    "it",
    "levity",
    "mashup",
    "of",
    "remix",
    "the",
    "this",
    "to",
    "x",
}
MIN_MATCH_RATIO = 0.5
MIN_OVERLAP = 2


@dataclass(frozen=True)
class EmbedJob:
    mp3: Path
    image: Path
    folder: str


@dataclass
class EmbedPlan:
    jobs: list[EmbedJob]
    unmatched_finals: list[Path]
    leftover_mp3s: list[Path]
    ambiguous_folders: list[str]


def tokens(text: str) -> set[str]:
    text = text.lower().replace("&", " and ")
    parts = re.sub(r"[^a-z0-9]+", " ", text).split()
    return {
        part
        for part in parts
        if part and part not in STOP_WORDS and not re.fullmatch(r"v\d+", part)
    }


def is_final_stem(stem: str) -> bool:
    name = stem.lower().strip()
    return name == "final" or name.endswith(("-final", "_final", " final"))


def is_final_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS and is_final_stem(path.stem)


def mime_for_image(path: Path) -> str:
    return MIME_BY_EXT[path.suffix.lower()]


def iter_mp3s(music: Path) -> list[Path]:
    files = [
        path
        for path in music.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS and not path.name.startswith("._")
    ]
    files.sort(key=lambda path: path.name.lower())
    return files


def iter_final_images(releases: Path) -> list[Path]:
    files = [path for path in releases.rglob("*") if path.is_file() and is_final_image(path)]
    files.sort(key=lambda path: str(path).lower())
    return files


def release_name(image: Path, releases: Path) -> str:
    rel = image.resolve().relative_to(releases.resolve())
    return rel.parts[0]


def match_folder_to_mp3s(folder_name: str, mp3s: list[Path]) -> list[Path]:
    folder_toks = tokens(folder_name)
    if not folder_toks:
        return []
    scored: list[tuple[int, float, Path]] = []
    for mp3 in mp3s:
        overlap = folder_toks & tokens(mp3.stem)
        ratio = len(overlap) / len(folder_toks)
        scored.append((len(overlap), ratio, mp3))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    if not scored or scored[0][0] == 0:
        return []
    best_overlap, best_ratio, _ = scored[0]
    if best_ratio < MIN_MATCH_RATIO and best_overlap < MIN_OVERLAP:
        return []
    chosen: list[Path] = []
    seen: set[Path] = set()
    for overlap, ratio, mp3 in scored:
        if overlap == best_overlap and ratio >= MIN_MATCH_RATIO and mp3 not in seen:
            seen.add(mp3)
            chosen.append(mp3)
    return chosen


def pick_image_for_folder(images: list[Path]) -> Path:
    exact = [path for path in images if path.stem.lower() == "final"]
    pool = exact or images
    return sorted(pool, key=lambda path: path.name.lower())[0]


def plan_embeds(music: Path, releases: Path) -> EmbedPlan:
    mp3s = iter_mp3s(music)
    finals = iter_final_images(releases)
    by_folder: dict[str, list[Path]] = {}
    for image in finals:
        by_folder.setdefault(release_name(image, releases), []).append(image)

    jobs: list[EmbedJob] = []
    unmatched: list[Path] = []
    used: set[Path] = set()
    ambiguous: list[str] = []
    for folder, images in sorted(by_folder.items()):
        image = pick_image_for_folder(images)
        if len(images) > 1:
            ambiguous.append(folder)
        hits = match_folder_to_mp3s(folder, mp3s)
        if not hits:
            unmatched.append(image)
            continue
        for mp3 in hits:
            used.add(mp3)
            jobs.append(EmbedJob(mp3=mp3, image=image, folder=folder))
    leftover = [mp3 for mp3 in mp3s if mp3 not in used]
    return EmbedPlan(
        jobs=jobs,
        unmatched_finals=unmatched,
        leftover_mp3s=leftover,
        ambiguous_folders=ambiguous,
    )


def existing_cover_bytes(mp3: Path) -> bytes | None:
    try:
        tags = ID3(mp3)
    except ID3NoHeaderError:
        return None
    apics = tags.getall("APIC")
    if not apics:
        return None
    return bytes(apics[0].data)


def embed_cover(mp3: Path, image: Path) -> None:
    data = image.read_bytes()
    try:
        tags = ID3(mp3)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.add(
        APIC(
            encoding=3,
            mime=mime_for_image(image),
            type=3,
            desc="Cover",
            data=data,
        )
    )
    tags.save(mp3, v2_version=3)


def apply_jobs(
    jobs: list[EmbedJob],
    *,
    dry_run: bool,
    skip_existing: bool,
) -> dict[str, int]:
    stats = {"embedded": 0, "already_ok": 0, "skipped": 0}
    for job in jobs:
        current = existing_cover_bytes(job.mp3)
        image_bytes = job.image.read_bytes()
        if skip_existing and current is not None:
            print(f"skip existing: {job.mp3.name}")
            stats["skipped"] += 1
            continue
        if current == image_bytes:
            print(f"already_ok: {job.mp3.name}")
            stats["already_ok"] += 1
            continue
        prefix = "[dry-run] " if dry_run else ""
        print(f"{prefix}embed: {job.folder} -> {job.mp3.name}")
        if not dry_run:
            embed_cover(job.mp3, job.image)
        stats["embedded"] += 1
    return stats


def _print_plan(plan: EmbedPlan) -> None:
    for image in plan.unmatched_finals:
        print(f"no match: {image}")
    for mp3 in plan.leftover_mp3s:
        print(f"no cover: {mp3.name}")
    for folder in plan.ambiguous_folders:
        print(f"multiple finals: {folder} (using exact final.* if present)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Embed Thumbnails/Releases final images into DJ Music/HuntingSzn MP3s. "
            "Rename the chosen artwork to final.png (or *-final.png) first."
        )
    )
    parser.add_argument(
        "--music",
        type=Path,
        default=DJ_HUNTINGSZN,
        help="Folder of MP3s (default: DJ Music/HuntingSzn)",
    )
    parser.add_argument(
        "--releases",
        type=Path,
        default=THUMBNAILS_RELEASES,
        help="Release artwork root (default: Thumbnails/Releases)",
    )
    parser.add_argument(
        "--mp3",
        type=Path,
        action="append",
        default=[],
        help="Explicit MP3 (repeatable)",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Explicit image; requires --mp3",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Leave MP3s that already have any embedded cover",
    )
    args = parser.parse_args(argv)

    if args.image and not args.mp3:
        parser.error("--image requires --mp3")
    if args.mp3 and not args.image:
        parser.error("--mp3 requires --image")

    if args.mp3:
        image = args.image
        if not image.is_file():
            raise SystemExit(f"Not a file: {image}")
        jobs = []
        for mp3 in args.mp3:
            if not mp3.is_file():
                raise SystemExit(f"Not a file: {mp3}")
            jobs.append(EmbedJob(mp3=mp3, image=image, folder=image.parent.name))
        stats = apply_jobs(jobs, dry_run=args.dry_run, skip_existing=args.skip_existing)
        print(
            f"embedded={stats['embedded']} already_ok={stats['already_ok']} "
            f"skipped={stats['skipped']}"
        )
        return 0

    if not args.music.is_dir():
        raise SystemExit(f"Not a directory: {args.music}")
    if not args.releases.is_dir():
        raise SystemExit(f"Not a directory: {args.releases}")

    plan = plan_embeds(args.music, args.releases)
    _print_plan(plan)
    stats = apply_jobs(plan.jobs, dry_run=args.dry_run, skip_existing=args.skip_existing)
    print(
        f"embedded={stats['embedded']} already_ok={stats['already_ok']} "
        f"skipped={stats['skipped']} unmatched={len(plan.unmatched_finals)} "
        f"leftover={len(plan.leftover_mp3s)}"
    )
    return 1 if plan.unmatched_finals else 0


if __name__ == "__main__":
    raise SystemExit(main())
