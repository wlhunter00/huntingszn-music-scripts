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
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, src.open("rb") as source:
            shutil.copyfileobj(source, target)
        shutil.copystat(src, temp)
        try:
            os.link(temp, dest)
        except OSError as e:
            if e.errno not in (errno.EPERM, errno.EACCES, errno.ENOSYS,
                               errno.EOPNOTSUPP, errno.EXDEV):
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
