"""Find and remove duplicate audio files in the DJ Spotify library.

Detects:
1. (1)/(2) filename copies and same-basename/different-extension pairs
2. Exact normalized title+artist matches (different filenames)
3. Fuzzy title+artist matches when ``--fuzzy`` is passed (off by default)

Original and remix/edit versions are never treated as duplicates of each other.
When duplicates are found, the oldest file is kept and newer copies are deleted.
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from mutagen import File

from config.paths import DJ_SPOTIFY

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg"}
EXT_KEEP_PRIORITY = {".flac": 0, ".wav": 1, ".m4a": 2, ".aac": 3, ".ogg": 4, ".mp3": 5}
DEFAULT_FUZZY_THRESHOLD = 0.85
VERSION_QUALIFIER = re.compile(
    r"\b(remix|edit|flip|bootleg|vip|extended|mix|version|rework|mashup|dub)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SongTags:
    artist: str
    title: str


@dataclass(frozen=True)
class DuplicateCandidate:
    keep: Path
    dup: Path
    reason: str


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Path, Path] = {}

    def add(self, item: Path) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: Path) -> Path:
        self.add(item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: Path, right: Path) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def collect_audio_files(library: Path) -> dict[str, Path]:
    """Map basename -> full path for all audio files under library."""
    files: dict[str, Path] = {}
    for dirpath, _, filenames in os.walk(library):
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            files[name] = Path(dirpath) / name
    return files


def collect_all_audio_paths(library: Path) -> list[Path]:
    paths: list[Path] = []
    for dirpath, _, filenames in os.walk(library):
        for name in filenames:
            if Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            paths.append(Path(dirpath) / name)
    return paths


def has_version_qualifier(value: str) -> bool:
    return bool(VERSION_QUALIFIER.search(value))


def normalize_token(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^\w\s]+", " ", text)
    return " ".join(text.split())


def base_title(value: str) -> str:
    """Title with bracketed/parenthetical segments removed for base-song comparison."""
    text = value
    text = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", text)
    if " - " in text:
        left, right = text.rsplit(" - ", 1)
        if has_version_qualifier(right):
            text = left
    return normalize_token(text)


def extract_version_signature(*sources: str) -> str:
    """Normalized remix/edit label, or empty string for the original version."""
    signatures: list[str] = []
    for source in sources:
        for match in re.finditer(r"[\[\(]([^\]\)]+)[\]\)]", source, flags=re.IGNORECASE):
            segment = match.group(1)
            if has_version_qualifier(segment):
                signatures.append(normalize_token(segment))

        if signatures:
            break

        if has_version_qualifier(source):
            if " - " in source:
                suffix = source.rsplit(" - ", 1)[-1]
                if has_version_qualifier(suffix):
                    signatures.append(normalize_token(suffix))
                    break
            signatures.append(normalize_token(source))
            break

    return " ".join(signatures)


def version_signature_for_path(path: Path, tags: SongTags | None) -> str:
    sources = [path.stem]
    if tags is not None:
        sources.append(tags.title)
    return extract_version_signature(*sources)


def fuzzy_ratio(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def get_tags(path: Path) -> SongTags | None:
    try:
        audio = File(path, easy=True)
        if audio is None:
            return None
        artist = (audio.get("artist") or [None])[0]
        title = (audio.get("title") or [None])[0]
        if not artist or not title:
            return None
        return SongTags(artist=artist.strip(), title=title.strip())
    except Exception as exc:
        print(f"Error reading tags from {path}: {exc}")
        return None


def load_tags_cache(paths: list[Path]) -> dict[Path, SongTags]:
    cache: dict[Path, SongTags] = {}
    for path in paths:
        tags = get_tags(path)
        if tags is not None:
            cache[path] = tags
    return cache


def same_version(path_a: Path, path_b: Path, tags_cache: dict[Path, SongTags]) -> bool:
    sig_a = version_signature_for_path(path_a, tags_cache.get(path_a))
    sig_b = version_signature_for_path(path_b, tags_cache.get(path_b))
    return sig_a == sig_b


def tags_match_exact(
    left: SongTags,
    right: SongTags,
    *,
    left_path: Path,
    right_path: Path,
) -> bool:
    if not same_version(left_path, right_path, {left_path: left, right_path: right}):
        return False
    return (
        normalize_token(left.artist) == normalize_token(right.artist)
        and base_title(left.title) == base_title(right.title)
    )


def tags_match_fuzzy(
    left: SongTags,
    right: SongTags,
    *,
    left_path: Path,
    right_path: Path,
    threshold: float,
) -> bool:
    if not same_version(left_path, right_path, {left_path: left, right_path: right}):
        return False

    artist_ratio = fuzzy_ratio(normalize_token(left.artist), normalize_token(right.artist))
    title_ratio = fuzzy_ratio(base_title(left.title), base_title(right.title))
    return artist_ratio >= threshold and title_ratio >= threshold


def tracks_are_duplicates(
    left: Path,
    right: Path,
    tags_cache: dict[Path, SongTags],
    *,
    threshold: float,
) -> bool:
    if not same_version(left, right, tags_cache):
        return False

    left_tags = tags_cache.get(left)
    right_tags = tags_cache.get(right)
    if left_tags is None or right_tags is None:
        return False
    if tags_match_exact(left_tags, right_tags, left_path=left, right_path=right):
        return True
    return tags_match_fuzzy(
        left_tags,
        right_tags,
        left_path=left,
        right_path=right,
        threshold=threshold,
    )


def confirm_duplicate(
    keep: Path,
    dup: Path,
    tags_cache: dict[Path, SongTags],
    *,
    threshold: float,
    allow_fuzzy: bool,
) -> tuple[bool, str]:
    if not same_version(keep, dup, tags_cache):
        return False, "different version (original vs remix/edit)"
    left = tags_cache.get(keep)
    right = tags_cache.get(dup)
    if left is None or right is None:
        return False, "missing tags"
    if tags_match_exact(left, right, left_path=keep, right_path=dup):
        return True, "exact tags"
    if allow_fuzzy and tags_match_fuzzy(
        left, right, left_path=keep, right_path=dup, threshold=threshold
    ):
        artist_ratio = fuzzy_ratio(normalize_token(left.artist), normalize_token(right.artist))
        title_ratio = fuzzy_ratio(base_title(left.title), base_title(right.title))
        return (
            True,
            f"fuzzy tags (artist={artist_ratio:.2f}, title={title_ratio:.2f})",
        )
    return False, "tag mismatch"


def file_mtime(path: Path) -> float:
    return path.stat().st_mtime


def _keep_sort_key(path: Path) -> tuple[float, int, int, str]:
    """Lower key = older file, which is the one we keep."""
    numbered = 1 if "(1)" in path.name or "(2)" in path.name else 0
    ext_rank = EXT_KEEP_PRIORITY.get(path.suffix.lower(), 99)
    return (file_mtime(path), numbered, ext_rank, path.name.lower())


def choose_keep(paths: list[Path]) -> Path:
    return min(paths, key=_keep_sort_key)


def choose_keep_pair(left: Path, right: Path) -> tuple[Path, Path]:
    keep = choose_keep([left, right])
    dup = right if keep == left else left
    return keep, dup


def metadata_group_key(path: Path, tags: SongTags) -> tuple[str, str, str]:
    return (
        normalize_token(tags.artist),
        base_title(tags.title),
        version_signature_for_path(path, tags),
    )


def consolidate_candidates(candidates: list[DuplicateCandidate]) -> list[DuplicateCandidate]:
    """Merge pairwise hits into one keeper per duplicate cluster."""
    if not candidates:
        return []

    uf = UnionFind()
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        uf.union(candidate.keep, candidate.dup)
        key = (
            str(candidate.keep) if str(candidate.keep) < str(candidate.dup) else str(candidate.dup),
            str(candidate.dup) if str(candidate.keep) < str(candidate.dup) else str(candidate.keep),
        )
        reasons[key].add(candidate.reason)

    groups: dict[Path, list[Path]] = defaultdict(list)
    for path in uf.parent:
        groups[uf.find(path)].append(path)

    consolidated: list[DuplicateCandidate] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        keep = choose_keep(group)
        for path in group:
            if path == keep:
                continue
            pair = (
                (str(keep), str(path)) if str(keep) < str(path) else (str(path), str(keep))
            )
            reason = _primary_reason(reasons.get(pair, {"metadata"}))
            consolidated.append(DuplicateCandidate(keep=keep, dup=path, reason=reason))
    return consolidated


def _primary_reason(reasons: set[str]) -> str:
    """Pick the strongest match label when multiple passes flagged the same pair."""
    if "metadata-exact" in reasons:
        return "metadata-exact"
    if "metadata-fuzzy" in reasons:
        return "metadata-fuzzy"
    if len(reasons) == 1:
        return next(iter(reasons))
    return "+".join(sorted(reasons))


def find_numbered_copy_duplicates(files: dict[str, Path]) -> list[tuple[Path, Path]]:
    """Find (1)/(2) copies where the base filename also exists."""
    pairs: list[tuple[Path, Path]] = []
    names = set(files)
    for name, dup_path in files.items():
        if "(1)" not in name and "(2)" not in name:
            continue
        existing_name = name.replace("(2)", "").replace("(1)", "")
        if existing_name in names:
            keep, dup = choose_keep_pair(files[existing_name], dup_path)
            pairs.append((keep, dup))
    return pairs


def find_extension_duplicates(files: dict[str, Path]) -> list[tuple[Path, Path]]:
    """Find same basename with different extensions."""
    by_stem: dict[str, list[Path]] = defaultdict(list)
    for path in files.values():
        by_stem[os.path.splitext(path.name)[0]].append(path)

    pairs: list[tuple[Path, Path]] = []
    for group in by_stem.values():
        by_extension = {path.suffix.lower(): path for path in group}
        if len(by_extension) < 2:
            continue
        paths = list(by_extension.values())
        keep = choose_keep(paths)
        for path in paths:
            if path != keep:
                pairs.append((keep, path))
    return pairs


def find_exact_metadata_duplicates(
    paths: list[Path],
    tags_cache: dict[Path, SongTags],
) -> list[tuple[Path, Path]]:
    groups: dict[tuple[str, str, str], list[Path]] = defaultdict(list)
    for path in paths:
        tags = tags_cache.get(path)
        if tags is None:
            continue
        groups[metadata_group_key(path, tags)].append(path)

    pairs: list[tuple[Path, Path]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                pairs.append((left, right))
    return pairs


def find_fuzzy_metadata_duplicates(
    paths: list[Path],
    tags_cache: dict[Path, SongTags],
    *,
    threshold: float,
) -> list[tuple[Path, Path]]:
    buckets: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for path in paths:
        tags = tags_cache.get(path)
        if tags is None:
            continue
        buckets[(base_title(tags.title)[:8], version_signature_for_path(path, tags))].append(path)

    pairs: list[tuple[Path, Path]] = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        for index, left in enumerate(bucket):
            for right in bucket[index + 1 :]:
                if tracks_are_duplicates(left, right, tags_cache, threshold=threshold):
                    pairs.append((left, right))
    return pairs


def pairs_to_candidates(pairs: list[tuple[Path, Path]], reason: str) -> list[DuplicateCandidate]:
    return [DuplicateCandidate(keep=left, dup=right, reason=reason) for left, right in pairs]


def find_duplicates(
    library: Path,
    *,
    fuzzy_threshold: float,
    include_metadata: bool,
    include_fuzzy: bool,
) -> tuple[list[DuplicateCandidate], dict[Path, SongTags]]:
    files = collect_audio_files(library)
    all_paths = collect_all_audio_paths(library)
    tags_cache = load_tags_cache(all_paths)

    pair_candidates: list[DuplicateCandidate] = []

    for keep, dup in find_numbered_copy_duplicates(files):
        pair_candidates.append(DuplicateCandidate(keep=keep, dup=dup, reason="filename-numbered"))

    for keep, dup in find_extension_duplicates(files):
        pair_candidates.append(DuplicateCandidate(keep=keep, dup=dup, reason="filename-extension"))

    if include_metadata:
        exact_pairs = find_exact_metadata_duplicates(all_paths, tags_cache)
        pair_candidates.extend(pairs_to_candidates(exact_pairs, "metadata-exact"))

        if include_fuzzy:
            fuzzy_pairs = find_fuzzy_metadata_duplicates(
                all_paths,
                tags_cache,
                threshold=fuzzy_threshold,
            )
            pair_candidates.extend(pairs_to_candidates(fuzzy_pairs, "metadata-fuzzy"))

    return consolidate_candidates(pair_candidates), tags_cache


def format_song_label(path: Path, tags_cache: dict[Path, SongTags]) -> str | None:
    tags = tags_cache.get(path)
    if tags is None:
        return None
    label = f"{tags.artist} - {tags.title}"
    version = version_signature_for_path(path, tags)
    if version:
        label = f"{label} (version: {version})"
    return label


def describe_duplicate_match(
    candidate: DuplicateCandidate,
    tags_cache: dict[Path, SongTags],
    *,
    threshold: float,
    allow_fuzzy: bool,
) -> tuple[bool, str]:
    if "filename" in candidate.reason:
        confirmed, detail = confirm_duplicate(
            candidate.keep,
            candidate.dup,
            tags_cache,
            threshold=threshold,
            allow_fuzzy=allow_fuzzy,
        )
        if not confirmed:
            return False, detail
        song = format_song_label(candidate.keep, tags_cache)
        if song:
            if "fuzzy" in detail:
                return True, f"matched on: {song} ({detail})"
            return True, f"matched on: {song}"
        return True, detail

    song = format_song_label(candidate.keep, tags_cache)
    if song:
        return True, f"matched on: {song}"
    return True, candidate.reason


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate files in DJ library (filename + metadata matching)."
    )
    parser.add_argument("--library", type=Path, default=DJ_SPOTIFY)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fuzzy",
        action="store_true",
        help="Also match near-miss artist/title tags (default: exact metadata only).",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=DEFAULT_FUZZY_THRESHOLD,
        help="Min similarity ratio (0-1) when --fuzzy is set (default: 0.85).",
    )
    parser.add_argument(
        "--filename-only",
        action="store_true",
        help="Only use filename/extension rules; skip metadata duplicate scan.",
    )
    args = parser.parse_args()
    if not args.library.is_dir():
        raise SystemExit(f"Not a directory: {args.library}")

    print(f"Scanning {args.library} ...")
    candidates, tags_cache = find_duplicates(
        args.library,
        fuzzy_threshold=args.fuzzy_threshold,
        include_metadata=not args.filename_only,
        include_fuzzy=args.fuzzy,
    )
    if not candidates:
        print("No duplicate candidates found.")
        return

    print(f"Found {len(candidates)} file(s) to remove across duplicate group(s).\n")

    removed = 0
    for candidate in candidates:
        confirmed, match_note = describe_duplicate_match(
            candidate,
            tags_cache,
            threshold=args.fuzzy_threshold,
            allow_fuzzy=args.fuzzy,
        )
        if not confirmed:
            print(
                f"skip [{candidate.reason}]: keep {candidate.keep.name}, "
                f"skip {candidate.dup.name} ({match_note})"
            )
            continue

        print(f"duplicate [{candidate.reason}]:")
        if match_note.startswith("matched on: "):
            print(f"  matched: {match_note.removeprefix('matched on: ')}")
        else:
            print(f"  matched: {match_note} (filename rule)")
        print(f"  keep:   {candidate.keep}")
        print(f"  delete: {candidate.dup}")
        print(f"  {'[dry-run] ' if args.dry_run else ''}delete {candidate.dup.name}")
        if not args.dry_run:
            candidate.dup.unlink()
        removed += 1
        print()

    print(f"{'Would remove' if args.dry_run else 'Removed'} {removed} file(s).")


if __name__ == "__main__":
    main()
