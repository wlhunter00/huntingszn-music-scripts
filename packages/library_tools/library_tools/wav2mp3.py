"""Convert WAV files to MP3 via ffmpeg."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def convert_wav_to_mp3(
    input_path: Path,
    output_path: Path | None = None,
    *,
    bitrate: str = "320k",
    overwrite: bool = False,
) -> Path:
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if input_path.suffix.lower() != ".wav":
        raise ValueError(f"Expected .wav file: {input_path}")

    out = output_path or input_path.with_suffix(".mp3")
    if out.exists() and not overwrite:
        raise FileExistsError(f"Output exists (use --overwrite): {out}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-y" if overwrite else "-n",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert WAV files to MP3 via ffmpeg.")
    parser.add_argument("inputs", nargs="+", type=Path, help="One or more .wav files")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .mp3 path (only valid for a single input)",
    )
    parser.add_argument("-b", "--bitrate", default="320k", help="MP3 bitrate (default: 320k)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .mp3 files")
    args = parser.parse_args()

    if len(args.inputs) > 1 and args.output:
        parser.error("--output only works with a single input file")

    failed = False
    for inp in args.inputs:
        try:
            out = convert_wav_to_mp3(
                inp,
                args.output if len(args.inputs) == 1 else None,
                bitrate=args.bitrate,
                overwrite=args.overwrite,
            )
            print(out)
        except FileNotFoundError as exc:
            if exc.filename == "ffmpeg":
                print("ffmpeg not found. Install ffmpeg and ensure it is on PATH.", file=sys.stderr)
            else:
                print(exc, file=sys.stderr)
            failed = True
            break
        except (FileExistsError, ValueError) as exc:
            print(exc, file=sys.stderr)
            failed = True
        except subprocess.CalledProcessError:
            print(f"ffmpeg failed: {inp}", file=sys.stderr)
            failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
