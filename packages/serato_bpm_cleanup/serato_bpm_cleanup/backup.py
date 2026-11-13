"""Copy files we are about to mutate. Never deletes sources."""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def timestamped_backup_root(base: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return base / stamp


def backup_file(src: Path, backup_root: Path, *, relative: Path | None = None) -> Path:
    """Copy ``src`` under ``backup_root`` without following a delete-on-error path."""
    rel = relative if relative is not None else Path(src.name)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("backup path must be library-relative")
    dest = backup_root / rel
    if dest.exists():
        raise FileExistsError(f"backup already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".backup-", suffix=".tmp", dir=dest.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, src.open("rb") as source:
            shutil.copyfileobj(source, target)
        shutil.copystat(src, temp)
        try:
            os.link(temp, dest)
        except OSError as e:
            # Windows volumes that cannot hardlink (exFAT and some external
            # drives) return EINVAL / WinError 1, "Incorrect function."
            unsupported = e.errno in (
                errno.EPERM,
                errno.EACCES,
                errno.ENOSYS,
                errno.EOPNOTSUPP,
                errno.EXDEV,
                errno.EINVAL,
            ) or getattr(e, "winerror", None) == 1
            if not unsupported:
                raise
            _copy_exclusive(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    return dest


def _copy_exclusive(src: Path, dest: Path) -> None:
    target = dest.open("xb")
    try:
        with target, src.open("rb") as source:
            shutil.copyfileobj(source, target)
        shutil.copystat(src, dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
