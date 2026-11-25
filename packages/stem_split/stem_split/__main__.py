"""CLI: python -m stem_split --input ... --output ..."""

from __future__ import annotations

import argparse
from pathlib import Path

from stem_split._bootstrap import ensure_config_importable
from stem_split.models import VOCAL_CANDIDATES, VOCAL_MODEL_ALIASES, resolve_vocal_models
from stem_split.pipeline import StemSplitOptions, process_audio_folder

ensure_config_importable()

from config.paths import STEM_INPUT, STEM_OUTPUT  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--dry-vocals",
        action="store_true",
        default=False,
        help="Dereverb then denoise the ensemble vocal stem; writes <title>_vocals_dry.wav",
    )
    parser.add_argument(
        "--karaoke",
        action="store_true",
        default=False,
        help="Lead-vocal-only extraction from ensemble vocals; writes <title>_vocals_lead.wav",
    )
    parser.add_argument(
        "--crowd",
        action="store_true",
        default=False,
        help="Crowd-remove the mix before vocal extraction only (Demucs still uses original mix)",
    )
    parser.add_argument(
        "--vocal-models",
        default=None,
        metavar="A,B",
        help=(
            "Override the vocal ensemble pair. Comma-separated aliases or filenames. "
            "Aliases: " + ", ".join(sorted(VOCAL_MODEL_ALIASES)) + ". "
            "Default: viperx,kim"
        ),
    )
    parser.add_argument(
        "--list-vocal-models",
        action="store_true",
        default=False,
        help="Print the default ensemble and A/B candidate aliases, then exit",
    )
    return parser


def _print_vocal_models() -> None:
    print("Default ensemble: viperx,kim")
    print(f"  1. {VOCAL_CANDIDATES[0].filename}")
    print(f"  2. {VOCAL_CANDIDATES[1].filename}")
    print()
    print(f"{'alias':<22} {'filename':<56} role")
    for c in VOCAL_CANDIDATES:
        print(f"{c.alias:<22} {c.filename:<56} {c.role}")
    print()
    print("Example: --vocal-models resurrection,kim-ft2-bleedless")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_vocal_models:
        _print_vocal_models()
        return
    vocal_models = resolve_vocal_models(args.vocal_models)
    options = StemSplitOptions(
        dry_vocals=args.dry_vocals,
        karaoke=args.karaoke,
        crowd=args.crowd,
        vocal_models=vocal_models,
    )
    process_audio_folder(str(args.input), str(args.output), options=options)


if __name__ == "__main__":
    main()
