"""B2 / rclone operations for library sync.

B2 layout:
- Bucket root mirrors drive folders (DJ Music, Ableton, Stem Splitting,
  Thumbnails, etc.)
- metadata/library.sqlite — one-way UP (track catalog for queries)
- templates/mashup/ — one-way UP from Ableton/HuntingSzn Mashup Template Project
- Other agent-written prefixes (e.g. Thumbnails/) land 1:1 on the drive
  (``Thumbnails/Releases/...`` -> ``{DRIVE}/Thumbnails/Releases/...``)
- projects/<slug>/ — remapped DOWN to Ableton/Music Production Agent/<slug>/
  (excluded from the root pull so jobs do not pile up under {DRIVE}/projects/)

Publish defaults to `rclone copy` (no remote deletes, overwrites dest from
the drive). Pass allow_delete=True for `rclone sync`. Sync excludes the
B2-only prefixes (projects/, metadata/, templates/) so they are not deleted.

Pull is two ``rclone copy --update`` steps (never deletes):
1. Whole bucket -> drive root, excluding ``projects/**``
2. ``projects/`` -> ``Ableton/Music Production Agent/``

Env vars:
- B2_BUCKET       — bucket name (stub)
- B2_REMOTE       — rclone remote name (e.g., "b2")
- MASHUP_TEMPLATE_PATH — override template path
  (default: Ableton/HuntingSzn Mashup Template Project)

If B2_REMOTE is not set, prints planned commands and exits 0.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

PUBLISH_EXCLUDES = [
    "$RECYCLE.BIN/**",
    "$Recycle.Bin/**",
    "System Volume Information/**",
    ".Spotlight-V100/**",
    ".TemporaryItems/**",
    ".Trashes/**",
    ".fseventsd/**",
    ".DS_Store",
    "._*",
    ".git/**",
    ".venv/**",
    "**/.venv/**",
    "**/__pycache__/**",
    "**/*.pyc",
    ".uv/**",
    "**/node_modules/**",
    "**/Backup/**",
    # Secrets: gitignored, must not land in B2.
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "cookies.txt",
    "**/cookies.txt",
    "*.pem",
    "**/*.pem",
    # Catalog is published separately to metadata/library.sqlite.
    "/Scripts/data/library.sqlite",
    "/Scripts/data/library.sqlite-wal",
    "/Scripts/data/library.sqlite-shm",
    "/Scripts/data/library.sqlite-journal",
    # B2-only prefixes. rclone does not delete excluded dest paths on sync,
    # so --allow-delete will not wipe projects/, metadata/, or templates/.
    "/projects/**",
    "/metadata/**",
    "/templates/**",
]

# Root pull copies every prefix 1:1 except projects/, which is remapped
# into Ableton/Music Production Agent/ so that folder stays the job home.
PULL_BUCKET_EXCLUDES = [
    "/projects/**",
]


class RcloneError(RuntimeError):
    """rclone subprocess failed."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        pretty = shlex.join(cmd)
        detail = stderr.strip() or "no stderr"
        super().__init__(f"rclone failed ({returncode}): {pretty}\n{detail}")


@dataclass
class RcloneConfig:
    """Configuration for rclone operations."""

    remote: str | None
    bucket: str | None
    mashup_template_path: Path | None

    @classmethod
    def from_env(cls, drive_root: Path | None = None) -> RcloneConfig:
        """Load configuration from environment variables.

        Args:
            drive_root: If provided, use as base for default template path
        """
        remote = os.environ.get("B2_REMOTE")
        bucket = os.environ.get("B2_BUCKET")
        template_str = os.environ.get("MASHUP_TEMPLATE_PATH")
        if template_str:
            template_path = Path(template_str)
        elif drive_root:
            template_path = drive_root / "Ableton" / "HuntingSzn Mashup Template Project"
        else:
            template_path = None
        return cls(remote=remote, bucket=bucket, mashup_template_path=template_path)

    @property
    def is_configured(self) -> bool:
        """Check if B2 is configured for actual operations."""
        return bool(self.remote and self.bucket)


def _format_rclone_cmd(args: list[str]) -> str:
    """Shell-safe rclone command string for logs and copy-paste."""
    return shlex.join(["rclone", *args])


def _run_rclone(args: list[str], *, dry_run: bool = False) -> subprocess.CompletedProcess:
    """Run rclone with inherited stdio so progress is visible.

    Raises RcloneError on non-zero exit or if rclone is not on PATH.
    """
    cmd = ["rclone"] + args
    if dry_run:
        print(f"[dry-run] would run: {_format_rclone_cmd(args)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        raise RcloneError(cmd, 127, "rclone not found on PATH") from exc
    except OSError as exc:
        # pythonw / CREATE_NO_WINDOW can raise WinError 6 (invalid handle)
        # when inheriting closed stdio, even if rclone.exe exists.
        raise RcloneError(cmd, 127, str(exc) or "os error starting rclone") from exc
    if result.returncode != 0:
        raise RcloneError(cmd, result.returncode, "see rclone output above")
    return result


def _get_exclude_args() -> list[str]:
    """Get rclone exclude arguments for publish operations."""
    args = ["--ignore-case"]
    for pattern in PUBLISH_EXCLUDES:
        args.extend(["--exclude", pattern])
    return args


def _bucket_target(config: RcloneConfig, suffix: str = "/") -> str:
    remote = config.remote or "b2"
    bucket = config.bucket or "BUCKET"
    return f"{remote}:{bucket}{suffix}"


def _print_or_run(
    args: list[str],
    config: RcloneConfig,
    *,
    dry_run: bool,
) -> str:
    """Print a planned command or run rclone. Returns the formatted command."""
    cmd = _format_rclone_cmd(args)
    if not config.is_configured:
        print(f"[no B2 configured] planned command: {cmd}")
        return cmd
    if dry_run:
        print(f"[dry-run] {cmd}")
        return cmd
    _run_rclone(args)
    return cmd


def publish_drive(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
    allow_delete: bool = False,
    update: bool = False,
    progress: bool = True,
) -> list[str]:
    """Copy (default) or sync the drive to B2 bucket root.

    Default is copy: never deletes remote files; overwrites dest from the drive.
    allow_delete uses sync, which removes dest files that are not on the local
    drive, except excluded B2-only prefixes (projects/, metadata/, templates/).
    update adds rclone ``--update`` (skip dest files that are newer) and is
    ignored when allow_delete is set.
    progress adds rclone ``--progress`` (skip under pythonw / no console).

    Returns list of commands that were (or would be) executed.
    """
    action = "sync" if allow_delete else "copy"
    args = [action]
    if progress:
        args.append("--progress")
    if update and not allow_delete:
        args.append("--update")
    args.extend(
        [
            str(drive_root),
            _bucket_target(config, "/"),
            *_get_exclude_args(),
        ]
    )
    return [_print_or_run(args, config, dry_run=dry_run)]


def publish_sqlite(
    db_path: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
) -> str | None:
    """Publish SQLite database to B2.

    Returns command that was (or would be) executed.
    """
    if not db_path.exists():
        return None

    args = [
        "copyto",
        str(db_path),
        _bucket_target(config, "/metadata/library.sqlite"),
    ]
    return _print_or_run(args, config, dry_run=dry_run)


def publish_template(
    config: RcloneConfig,
    *,
    dry_run: bool = False,
) -> str | None:
    """Publish mashup template to B2 if configured.

    Returns command that was (or would be) executed, or None if not configured.
    """
    if not config.mashup_template_path or not config.mashup_template_path.exists():
        return None

    args = [
        "copy",
        str(config.mashup_template_path),
        _bucket_target(config, "/templates/mashup/"),
        "--ignore-case",
        "--exclude",
        "**/Backup/**",
        "--exclude",
        ".DS_Store",
        "--exclude",
        "._*",
    ]
    return _print_or_run(args, config, dry_run=dry_run)


def pull_projects(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
    progress: bool = True,
) -> str:
    """Copy B2 projects/ into Ableton/Music Production Agent.

    Uses copy --update: never deletes local files, does not overwrite newer
    local work.

    B2 projects/<slug>/ → {DRIVE}/Ableton/Music Production Agent/<slug>/
    """
    agent_projects = drive_root / "Ableton" / "Music Production Agent"

    if config.is_configured and not dry_run:
        agent_projects.mkdir(parents=True, exist_ok=True)

    args = ["copy"]
    if progress:
        args.append("--progress")
    args.extend(
        [
            "--update",
            _bucket_target(config, "/projects/"),
            str(agent_projects),
        ]
    )
    return _print_or_run(args, config, dry_run=dry_run)


def pull_drive(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
    progress: bool = True,
) -> list[str]:
    """Pull B2 onto the drive: whole bucket (minus projects/) plus Ableton remap.

    1. ``rclone copy --update`` bucket root -> drive, excluding ``projects/**``
       so Thumbnails/, metadata/, etc. land 1:1.
    2. ``rclone copy --update`` ``projects/`` -> ``Ableton/Music Production Agent/``.

    Never deletes local or remote files; never overwrites newer local work.

    Returns the commands that were (or would be) executed.
    """
    args = ["copy"]
    if progress:
        args.append("--progress")
    args.extend(
        [
            "--update",
            _bucket_target(config, "/"),
            str(drive_root),
        ]
    )
    for pattern in PULL_BUCKET_EXCLUDES:
        args.extend(["--exclude", pattern])
    bucket_cmd = _print_or_run(args, config, dry_run=dry_run)
    projects_cmd = pull_projects(
        drive_root, config, dry_run=dry_run, progress=progress
    )
    return [bucket_cmd, projects_cmd]
