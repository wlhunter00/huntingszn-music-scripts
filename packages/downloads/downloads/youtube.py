#!/usr/bin/env python3
"""Download YouTube audio via yt-dlp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from downloads._common import dated_output_dir, run_yt_dlp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download YouTube audio as MP3 320 kbps for DJ software."
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--best",
        action="store_true",
        help="Keep native best audio (Opus/AAC) instead of transcoding to MP3.",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Allow full playlist download when the URL points at a playlist.",
    )
    args = parser.parse_args()

    out = dated_output_dir(Path(args.output_dir) if args.output_dir else None)
    mode = "best" if args.best else "mp3"
    for url in args.urls:
        if not run_yt_dlp(
            url, out, audio_mode=mode, no_playlist=False if args.playlist else True
        ):
            sys.exit(1)
        print(f"Saved to {out}")


if __name__ == "__main__":
    main()
