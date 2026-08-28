"""Scan library, print reports, optionally write with backups."""

from __future__ import annotations

from pathlib import Path

from serato_bpm_cleanup import ACTION_FIX
from serato_bpm_cleanup.backup import backup_file
from serato_bpm_cleanup.classify import TrackReport, classify_track
from serato_bpm_cleanup.database import parse_database_tracks, save_database, update_database_bpm
from serato_bpm_cleanup.tags import (
    AUDIO_SUFFIXES,
    SERATO_WRITE_SUFFIXES,
    read_track,
    write_bpm_tags,
)

SKIP_NAMES = {".DS_Store"}


def iter_audio_files(root: Path):
    if root.is_file():
        if root.suffix.lower() in AUDIO_SUFFIXES:
            yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("._") or path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() in AUDIO_SUFFIXES:
            yield path


def _index_db_bpm(db_bytes: bytes | None) -> dict[str, float]:
    if not db_bytes:
        return {}
    out: dict[str, float] = {}
    for track in parse_database_tracks(db_bytes):
        if track.bpm is None:
            continue
        key = track.path.replace("\\", "/").lstrip("/").lower()
        out[key] = track.bpm
        out[Path(track.path).name.lower()] = track.bpm
    return out


def _lookup_db_bpm(path: Path, index: dict[str, float]) -> float | None:
    parts = path.as_posix().replace("\\", "/").lstrip("/").lower()
    if parts in index:
        return index[parts]
    name = path.name.lower()
    if name in index:
        return index[name]
    # Match by suffix path (database stores drive-relative paths).
    for key, bpm in index.items():
        if parts.endswith(key) or key.endswith(parts):
            return bpm
    return None


def inspect_library(
    roots: list[Path],
    *,
    db_bytes: bytes | None = None,
) -> list[TrackReport]:
    db_index = _index_db_bpm(db_bytes)
    reports: list[TrackReport] = []
    for root in roots:
        for path in iter_audio_files(root):
            try:
                data = read_track(path)
                db_bpm = _lookup_db_bpm(path, db_index)
                reports.append(classify_track(data, db_bpm=db_bpm))
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                reports.append(
                    TrackReport(
                        path=path,
                        current_bpm=None,
                        proposed_bpm=None,
                        cue_count=0,
                        action="error",
                        error=str(exc),
                    )
                )
    return reports


def apply_fix(
    report: TrackReport,
    *,
    backup_root: Path | None,
    library_root: Path | None,
) -> list[str]:
    """Mutate one track. Returns stores written. No-ops if cues exist."""
    if report.action != ACTION_FIX or report.proposed_bpm is None:
        return []
    data = read_track(report.path)
    if data.cue_count > 0:
        return []
    if backup_root is not None:
        rel = report.path.name
        if library_root is not None:
            try:
                rel = str(report.path.resolve().relative_to(library_root.resolve()))
            except ValueError:
                rel = report.path.name
        backup_file(report.path, backup_root, relative=Path(rel))

    update_grid = bool(data.beatgrid is not None and data.beatgrid.is_constant)
    update_autotags = data.autotags is not None
    if report.path.suffix.lower() not in SERATO_WRITE_SUFFIXES:
        raise ValueError(f"unsupported format for write: {report.path.suffix}")
    return write_bpm_tags(
        report.path,
        bpm=report.proposed_bpm,
        beatgrid=data.beatgrid,
        autotags=data.autotags,
        update_beatgrid=update_grid,
        update_autotags=update_autotags,
    )


def apply_database_updates(
    db_path: Path,
    reports: list[TrackReport],
    *,
    backup_root: Path | None,
) -> int:
    """Update ``tbpm`` for fix-action tracks. Returns number of DB rows changed."""
    path_to_bpm: dict[str, int] = {}
    for report in reports:
        if report.action != ACTION_FIX or report.proposed_bpm is None:
            continue
        path_to_bpm[str(report.path)] = report.proposed_bpm
        path_to_bpm[report.path.name] = report.proposed_bpm
        path_to_bpm[report.path.as_posix()] = report.proposed_bpm
    if not path_to_bpm:
        return 0
    raw = db_path.read_bytes()
    new_raw, updated = update_database_bpm(raw, path_to_bpm)
    if updated == 0 or new_raw == raw:
        return 0
    if backup_root is not None:
        backup_file(db_path, backup_root, relative=Path(db_path.name))
    save_database(db_path, new_raw)
    return updated
