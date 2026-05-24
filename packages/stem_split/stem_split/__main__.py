"""CLI: python -m stem_split --input ... --output ..."""

from __future__ import annotations

import argparse
from pathlib import Path

from config.paths import STEM_INPUT, STEM_OUTPUT
from stem_split.pipeline import process_audio_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the stem-splitting pipeline.")
    parser.add_argument(
        "--input",
        type=Path,
        default=STEM_INPUT,
        help="Folder of audio files to process",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=STEM_OUTPUT,
        help="Output folder (creates htdemucs_ft/ subdirs)",
    )
    args = parser.parse_args()
    process_audio_folder(str(args.input), str(args.output))


if __name__ == "__main__":
    main()
