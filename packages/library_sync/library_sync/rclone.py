"""B2 / rclone operations for library sync.

B2 layout:
- Bucket root mirrors drive folders (DJ Music, Ableton, Stem Splitting,
  Thumbnails, etc.)
- metadata/library.sqlite — one-way UP (track catalog for queries)
- templates/mashup/ — one-way UP from Ableton/HuntingSzn Mashup Template Project
- Thumbnails/ — agent drop zone, pulled 1:1
  (``Thumbnails/Releases/...`` -> ``{DRIVE}/Thumbnails/Releases/...``)
- projects/<slug>/ — remapped DOWN to Ableton/Music Production Agent/<slug>/

Publish defaults to `rclone copy` (no remote deletes, overwrites dest from
the drive). Pass allow_delete=True for `rclone sync`. Sync excludes the
B2-only prefixes (projects/, metadata/, templates/) so they are not deleted.

Pull is allowlisted ``rclone copy --update`` only (never deletes, never a
whole-bucket copy). Drive-primary trees (DJ Music, Platnium Notes, Stem
Splitting, Set Recording, Scripts, Ableton) are not pull sources, so a
local delete there is not resurrected from B2. Steps:
1. Each prefix in ``PULL_AGENT_PREFIXES`` (currently Thumbnails/) -> drive 1:1
2. ``projects/`` -> ``Ableton/Music Production Agent/`` (sole writer of that
   job home; Ableton is not pulled as a tree)

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

# Agent drop zones copied 1:1 onto the drive. Never include drive-primary
# trees (DJ Music, Platnium Notes, Stem Splitting, Set Recording, Scripts,
# Ableton) — those stay drive-authored; pull must not resurrect local deletes.
PULL_AGENT_PREFIXES = (
    "Thumbnails/",
)

# Must never appear as a pull source. Ableton is only written via the
# projects/ -> Music Production Agent remap, not as a tree copy.
PULL_DRIVE_PRIMARY_PREFIXES = (
    "DJ Music/",
    "Platnium Notes/",
    "Stem Splitting/",
    "Set Recording/",
    "Scripts/",
    "Ableton/",
)


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


def _copy_update_args(
    source: str,
    dest: Path,
    *,
    progress: bool,
    extra: list[str] | None = None,
) -> list[str]:
    """Build ``rclone copy --update --ignore-case`` argv (never sync/delete)."""
    args = ["copy"]
    if progress:
        args.append("--progress")
    args.extend(["--update", "--ignore-case", source, str(dest)])
    if extra:
        args.extend(extra)
    return args


def pull_projects(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
    progress: bool = True,
) -> str:
    """Copy B2 projects/ into Ableton/Music Production Agent.

    Uses copy --update: never deletes local files, does not overwrite newer
    local work. This is the sole writer of the Music Production job home.

    B2 projects/<slug>/ → {DRIVE}/Ableton/Music Production Agent/<slug>/
    """
    agent_projects = drive_root / "Ableton" / "Music Production Agent"

    if config.is_configured and not dry_run:
        agent_projects.mkdir(parents=True, exist_ok=True)

    args = _copy_update_args(
        _bucket_target(config, "/projects/"),
        agent_projects,
        progress=progress,
    )
    return _print_or_run(args, config, dry_run=dry_run)


def pull_drive(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
    progress: bool = True,
) -> list[str]:
    """Pull allowlisted agent prefixes, then remap projects/ into Ableton.

    1. Each ``PULL_AGENT_PREFIXES`` entry (Thumbnails/) -> drive 1:1.
    2. ``projects/`` -> ``Ableton/Music Production Agent/``.

    Never copies the bucket root or drive-primary trees. Never deletes.
    Agent copies run first; if one fails, the remap is not started.

    Returns the commands that were (or would be) executed.
    """
    commands: list[str] = []
    for prefix in PULL_AGENT_PREFIXES:
        dest = drive_root / prefix.rstrip("/")
        if config.is_configured and not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
        args = _copy_update_args(
            _bucket_target(config, f"/{prefix}"),
            dest,
            progress=progress,
        )
        commands.append(_print_or_run(args, config, dry_run=dry_run))
    commands.append(
        pull_projects(drive_root, config, dry_run=dry_run, progress=progress)
    )
    return commands
