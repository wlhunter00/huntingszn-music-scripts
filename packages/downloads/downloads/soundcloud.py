#!/usr/bin/env python3
"""Download SoundCloud audio via yt-dlp."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from downloads._common import dated_output_dir, run_yt_dlp


def check_preview_only(url: str, auth_token: str | None) -> tuple[bool, float]:
    cmd = ["yt-dlp", "--dump-json", "--no-download", url]
    if auth_token:
        cmd.extend(["--username", "oauth", "--password", auth_token])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        duration = float(data.get("duration") or 0)
        return duration <= 35, duration
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return False, 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Download SoundCloud tracks as MP3 320.")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--auth-token", default=os.environ.get("SOUNDCLOUD_AUTH_TOKEN"))
    args = parser.parse_args()

    from pathlib import Path

    out = dated_output_dir(Path(args.output_dir) if args.output_dir else None)

    for url in args.urls:
        preview, dur = check_preview_only(url, args.auth_token)
        if preview:
            print(f"Warning: {url} may be preview-only ({dur}s). Pass --auth-token for Go+.")
        if not run_yt_dlp(url, out, auth_token=args.auth_token):
            sys.exit(1)
        print(f"Saved to {out}")


if __name__ == "__main__":
    main()
