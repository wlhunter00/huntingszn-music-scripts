"""Shared download utilities."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from config.paths import DOWNLOADS

_YOUTUBE_HOST_MARKERS = ("youtube.com", "youtu.be", "music.youtube.com")


def dated_output_dir(override: Path | None) -> Path:
    out = override or (DOWNLOADS / date.today().isoformat())
    out.mkdir(parents=True, exist_ok=True)
    return out


def yt_dlp_cmd(*extra: str) -> list[str] | None:
    """Build a yt-dlp argv using the uv-managed package, not PATH brew/pip."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print(
            "yt-dlp is not installed in this environment. "
            "Run: uv sync --package music-downloads",
            file=sys.stderr,
        )
        return None
    return [sys.executable, "-m", "yt_dlp", "--no-update", *extra]


def _is_youtube(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _YOUTUBE_HOST_MARKERS)


def run_yt_dlp(
    url: str,
    output_dir: Path,
    *,
    auth_token: str | None = None,
    audio_mode: str = "mp3",
    no_playlist: bool | None = None,
    output_template: str | None = None,
) -> bool:
    """Run yt-dlp.

    audio_mode: ``mp3`` (320k transcode) or ``best`` (native best audio, minimal loss).

    ``no_playlist``: if ``True``, pass ``--no-playlist``; if ``False``, ``--yes-playlist``;
    if ``None`` (default), omit both (yt-dlp default).

    ``output_template``: optional yt-dlp ``-o`` template. Defaults to
    ``output_dir / "%(title)s.%(ext)s"``.
    """
    template = output_template or str(output_dir / "%(title)s.%(ext)s")
    cmd = yt_dlp_cmd("-o", template)
    if cmd is None:
        return False
    if no_playlist is True:
        cmd.append("--no-playlist")
    elif no_playlist is False:
        cmd.append("--yes-playlist")
    if audio_mode == "best":
        # Prefer a dedicated audio stream, then fall back; extract with least re-encoding.
        cmd.extend(
            [
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "best",
            ]
        )
    else:
        cmd.extend(
            [
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "320K",
            ]
        )
    cmd.extend(["--embed-thumbnail", "--add-metadata"])
    if _is_youtube(url):
        # Deno is default; Node on PATH is ignored unless listed.
        # https://github.com/yt-dlp/yt-dlp/issues/16747
        # Latest defaults dropped android_vr (SABR / 403-prone).
        cmd.extend(
            [
                "--js-runtimes",
                "deno,node",
                "--extractor-args",
                "youtube:player_client=default",
            ]
        )
    if auth_token:
        cmd.extend(["--username", "oauth", "--password", auth_token])
    cmd.append(url)
    try:
        subprocess.run(cmd, check=True)
        return True
    except FileNotFoundError:
        print(f"Python not found: {sys.executable}", file=sys.stderr)
        return False
    except subprocess.CalledProcessError:
        return False


def dump_yt_dlp_json(*extra: str) -> list[dict]:
    """Run yt-dlp with ``--dump-json`` and parse newline-delimited JSON objects."""
    import json

    cmd = yt_dlp_cmd("--dump-json", "--no-download", *extra)
    if cmd is None:
        return []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    if not result.stdout.strip():
        return []
    rows: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
