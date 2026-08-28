"""Copy files we are about to mutate. Never deletes sources."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path


def timestamped_backup_root(base: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return base / stamp


def backup_file(src: Path, backup_root: Path, *, relative: Path | None = None) -> Path:
    """Copy ``src`` under ``backup_root`` without following a delete-on-error path."""
    rel = relative if relative is not None else Path(src.name)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest
