"""B2 / rclone operations for library sync.

B2 layout:
- audio/          — library files, one-way UP from drive (only new/changed)
- metadata/library.sqlite — one-way UP
- templates/mashup/ — one-way UP when template path set
- projects/       — one-way DOWN to {DRIVE}/Ready to Mix/

Env vars:
- B2_BUCKET       — bucket name (stub)
- B2_REMOTE       — rclone remote name (e.g., "b2")
- MASHUP_TEMPLATE_PATH — local path to mashup template

If B2_REMOTE is not set, --dry-run prints planned commands and exits 0.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RcloneConfig:
    """Configuration for rclone operations."""

    remote: str | None
    bucket: str | None
    mashup_template_path: Path | None

    @classmethod
    def from_env(cls) -> RcloneConfig:
        """Load configuration from environment variables."""
        remote = os.environ.get("B2_REMOTE")
        bucket = os.environ.get("B2_BUCKET")
        template_str = os.environ.get("MASHUP_TEMPLATE_PATH")
        template_path = Path(template_str) if template_str else None
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


def publish_audio(
    drive_root: Path,
    config: RcloneConfig,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Publish new/changed audio files to B2.

    Returns list of commands that were (or would be) executed.
    """
    commands = []

    if not config.is_configured:
        target = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/audio/"
        source = str(drive_root)
        includes = "--include '*.mp3' --include '*.wav' --include '*.flac'"
        includes += " --include '*.aiff' --include '*.aif' --include '*.m4a'"
        cmd = f"rclone copy {includes} {source} {target}"
        print(f"[no B2 configured] planned command: {cmd}")
        commands.append(cmd)
        return commands

    target = f"{config.remote}:{config.bucket}/audio/"

    for index_root in ["DJ Music", "Platnium Notes"]:
        source = drive_root / index_root
        if not source.exists():
            continue

        args = [
            "copy",
            str(source),
            f"{target}{index_root}/",
            "--include", "*.mp3",
            "--include", "*.wav",
            "--include", "*.flac",
            "--include", "*.aiff",
            "--include", "*.aif",
            "--include", "*.m4a",
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
    """Pull projects from B2 to Ready to Mix folder.

    Returns command that was (or would be) executed.
    """
    ready_to_mix = drive_root / "Ready to Mix"

    if not config.is_configured:
        source = f"{config.remote or 'b2'}:{config.bucket or 'BUCKET'}/projects/"
        cmd = f"rclone sync {source} {ready_to_mix}"
        print(f"[no B2 configured] planned command: {cmd}")
        return cmd

    if not dry_run:
        ready_to_mix.mkdir(exist_ok=True)

    source = f"{config.remote}:{config.bucket}/projects/"
    args = ["sync", source, str(ready_to_mix)]
    cmd = f"rclone {' '.join(args)}"

    if not dry_run:
        _run_rclone(args)
    else:
        print(f"[dry-run] {cmd}")

    return cmd
