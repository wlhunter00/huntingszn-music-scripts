"""Shared download utilities."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from config.paths import DOWNLOADS


def dated_output_dir(override: Path | None) -> Path:
    out = override or (DOWNLOADS / date.today().isoformat())
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_yt_dlp(
    url: str,
    output_dir: Path,
    *,
    auth_token: str | None = None,
    audio_mode: str = "mp3",
    no_playlist: bool | None = None,
) -> bool:
    """Run yt-dlp.

    audio_mode: ``mp3`` (320k transcode) or ``best`` (native best audio, minimal loss).

    ``no_playlist``: if ``True``, pass ``--no-playlist``; if ``False``, ``--yes-playlist``;
    if ``None`` (default), omit both (yt-dlp default).
    """
    output_template = str(output_dir / "%(title)s.%(ext)s")
    cmd: list[str] = [
        "yt-dlp",
        "-o",
        output_template,
    ]
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
    if auth_token:
        cmd.extend(["--username", "oauth", "--password", auth_token])
    cmd.append(url)
    try:
        subprocess.run(cmd, check=True)
        return True
    except FileNotFoundError:
        print("yt-dlp not found. Install: brew install yt-dlp", file=sys.stderr)
        return False
    except subprocess.CalledProcessError:
        return False
