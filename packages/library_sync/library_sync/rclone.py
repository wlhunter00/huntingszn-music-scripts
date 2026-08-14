"""B2 / rclone operations for library sync.

B2 layout:
- Bucket root mirrors drive folders (DJ Music, Ableton, Stem Splitting, etc.)
- metadata/library.sqlite — one-way UP (track catalog for queries)
- templates/mashup/ — one-way UP from Ableton/HuntingSzn Mashup Template Project
- projects/<slug>/ — one-way DOWN to Ableton/Music Production Agent/<slug>/

Publish excludes:
- $RECYCLE.BIN, System Volume Information, .Spotlight-V100
- .TemporaryItems, .Trashes, .fseventsd, .DS_Store, ._, .git

Env vars:
- B2_BUCKET       — bucket name (stub)
- B2_REMOTE       — rclone remote name (e.g., "b2")
- MASHUP_TEMPLATE_PATH — override template path
  (default: Ableton/HuntingSzn Mashup Template Project)

If B2_REMOTE is not set, --dry-run prints planned commands and exits 0.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

PUBLISH_EXCLUDES = [
    "$RECYCLE.BIN/**",
    "System Volume Information/**",
    ".Spotlight-V100/**",
    ".TemporaryItems/**",
    ".Trashes/**",
    ".fseventsd/**",
    ".DS_Store",
    "._*",
    ".git/**",
]


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


def _run_rclone(args: list[str], *, dry_run: bool = False) -> subprocess.CompletedProcess:
    """Run rclone command, optionally in dry-run mode."""
    cmd = ["rclone"] + args
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _get_exclude_args() -> list[str]:
    """Get rclone exclude arguments for publish operations."""
    args = []
    for pattern in PUBLISH_EXCLUDES:
        args.extend(["--exclude", pattern])
    return args


def publish_drive(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Mirror the entire drive to B2 bucket root.

    Excludes system files and metadata directories.
    Returns list of commands that were (or would be) executed.
    """
    commands = []
    excludes_str = " ".join(f"--exclude '{p}'" for p in PUBLISH_EXCLUDES)

    if not config.is_configured:
        target = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/"
        cmd = f"rclone sync {excludes_str} --update {drive_root} {target}"
        print(f"[no B2 configured] planned command: {cmd}")
        commands.append(cmd)
        return commands

    target = f"{config.remote}:{config.bucket}/"

    args = [
        "sync",
        str(drive_root),
        target,
        *_get_exclude_args(),
        "--update",
    ]

    cmd = f"rclone {' '.join(args)}"
    commands.append(cmd)

    if not dry_run:
        _run_rclone(args)
    else:
        print(f"[dry-run] {cmd}")

    return commands


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

    if not config.is_configured:
        target = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/metadata/library.sqlite"
        cmd = f"rclone copyto {db_path} {target}"
        print(f"[no B2 configured] planned command: {cmd}")
        return cmd

    target = f"{config.remote}:{config.bucket}/metadata/library.sqlite"
    args = ["copyto", str(db_path), target]
    cmd = f"rclone {' '.join(args)}"

    if not dry_run:
        _run_rclone(args)
    else:
        print(f"[dry-run] {cmd}")

    return cmd


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

    if not config.is_configured:
        target = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/templates/mashup/"
        cmd = f"rclone copy {config.mashup_template_path} {target}"
        print(f"[no B2 configured] planned command: {cmd}")
        return cmd

    target = f"{config.remote}:{config.bucket}/templates/mashup/"
    args = ["copy", str(config.mashup_template_path), target]
    cmd = f"rclone {' '.join(args)}"

    if not dry_run:
        _run_rclone(args)
    else:
        print(f"[dry-run] {cmd}")

    return cmd


def pull_projects(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
) -> str | None:
    """Pull projects from B2 to Ableton/Music Production Agent folder.

    B2 projects/<slug>/ → {DRIVE}/Ableton/Music Production Agent/<slug>/

    Returns command that was (or would be) executed.
    """
    agent_projects = drive_root / "Ableton" / "Music Production Agent"

    if not config.is_configured:
        source = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/projects/"
        cmd = f"rclone sync {source} {agent_projects}"
        print(f"[no B2 configured] planned command: {cmd}")
        return cmd

    if not dry_run:
        agent_projects.mkdir(parents=True, exist_ok=True)

    source = f"{config.remote}:{config.bucket}/projects/"
    args = ["sync", source, str(agent_projects)]
    cmd = f"rclone {' '.join(args)}"

    if not dry_run:
        _run_rclone(args)
    else:
        print(f"[dry-run] {cmd}")

    return cmd
