"""Library / Serato DB auto-detect and best-effort “is Serato running?” check."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERATO_DIR_NAME = "_Serato_"
DB_FILENAME = "database V2"
WILL_WINDOWS_HOME = Path(r"C:\Users\Will")

# Process-name needles. Do not match this CLI (serato-bpm-cleanup).
_SERATO_NAME_NEEDLES = (
    "serato dj pro",
    "serato dj lite",
    "serato dj.exe",
    "seratodj",
)


def _looks_like_serato_process(name: str) -> bool:
    lowered = name.lower()
    if "serato-bpm" in lowered or "serato_bpm" in lowered:
        return False
    if any(needle in lowered for needle in _SERATO_NAME_NEEDLES):
        return True
    stem = Path(name).stem.lower()
    return stem == "serato"


def serato_is_running() -> bool:
    """Best-effort: Serato DJ Pro / “Serato” on Windows. False if we cannot tell."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                return False
            for line in result.stdout.splitlines():
                # CSV: "Image Name","PID",...
                image = line.split(",", 1)[0].strip().strip('"')
                if _looks_like_serato_process(image):
                    return True
            return False
        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            if _looks_like_serato_process(line.strip()):
                return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def _drive_root() -> Path | None:
    try:
        from config.paths import DRIVE_ROOT

        return Path(DRIVE_ROOT)
    except Exception:
        raw = os.environ.get("MUSIC_DRIVE_ROOT")
        return Path(raw) if raw else None


def default_library_roots(explicit: Path | None = None) -> list[Path]:
    """Audio roots to scan. ``--library`` wins; else DJ Music / Will's Music."""
    if explicit is not None:
        return [explicit.expanduser()]

    roots: list[Path] = []
    try:
        from config.paths import DJ_MUSIC, PLATINUM_NOTES

        roots.extend([Path(DJ_MUSIC), Path(PLATINUM_NOTES)])
    except Exception:
        pass

    if sys.platform == "win32":
        roots.extend(
            [
                WILL_WINDOWS_HOME / "Music",
                Path(r"C:\Users\Will\Music"),
            ]
        )
    home_music = Path.home() / "Music"
    roots.append(home_music)

    drive = _drive_root()
    if drive is not None:
        roots.extend([drive / "DJ Music", drive / "Platnium Notes"])

    seen: set[Path] = set()
    existing: list[Path] = []
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        existing.append(resolved)
    return existing


def _db_candidates(library_roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "win32":
        candidates.append(WILL_WINDOWS_HOME / "Music" / SERATO_DIR_NAME / DB_FILENAME)
    candidates.append(Path.home() / "Music" / SERATO_DIR_NAME / DB_FILENAME)
    drive = _drive_root()
    if drive is not None:
        candidates.append(drive / SERATO_DIR_NAME / DB_FILENAME)
        candidates.append(drive / "DJ Music" / SERATO_DIR_NAME / DB_FILENAME)
    for root in library_roots:
        candidates.append(root / SERATO_DIR_NAME / DB_FILENAME)
        candidates.append(root.parent / SERATO_DIR_NAME / DB_FILENAME)
    return candidates


def default_database_path(
    explicit: Path | None = None, library_roots: list[Path] | None = None
) -> Path | None:
    if explicit is not None:
        return explicit.expanduser()
    env = os.environ.get("SERATO_DB")
    if env:
        return Path(env).expanduser()
    for candidate in _db_candidates(library_roots or []):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None
