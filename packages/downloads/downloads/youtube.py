#!/usr/bin/env python3
"""Download YouTube audio via yt-dlp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from downloads._common import dated_output_dir, run_yt_dlp


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download YouTube audio at the best quality yt-dlp can fetch "
            "(native AAC/Opus/etc., not upsampled). Use --mp3 only if you need DJ-software MP3."
        )
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--mp3",
        action="store_true",
        help="Transcode to MP3 320 kbps instead of keeping the best source format.",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Allow full playlist download when the URL points at a playlist.",
    )
    args = parser.parse_args()

    out = dated_output_dir(Path(args.output_dir) if args.output_dir else None)
    mode = "mp3" if args.mp3 else "best"
    for url in args.urls:
        if not run_yt_dlp(
            url, out, audio_mode=mode, no_playlist=False if args.playlist else True
        ):
            sys.exit(1)
        print(f"Saved to {out}")


if __name__ == "__main__":
    main()
