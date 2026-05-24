"""
Step 1: Scan the library and extract current metadata into a catalog CSV.

Reads FLAC (INITIALKEY via Vorbis) and MP3 (TKEY via ID3) tags.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

from library_tools.key_correction.settings import AUDIO_EXTENSIONS, LIBRARY_PATH, OUTPUT_DIR


def get_metadata_ffprobe(filepath: Path) -> dict[str, str]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        return {k.lower(): str(v) for k, v in tags.items()}
    except (json.JSONDecodeError, subprocess.SubprocessError):
        return {}


def extract_key(tags: dict[str, str]) -> str:
    for key in ("initialkey", "tkey", "key"):
        if key in tags:
            return tags[key]
    return ""


def catalog_library(library: Path, output_csv: Path) -> int:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for path in sorted(library.rglob("*")):
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        tags = get_metadata_ffprobe(path)
        rows.append(
            {
                "filepath": str(path),
                "artist": tags.get("artist", ""),
                "title": tags.get("title", ""),
                "album": tags.get("album", ""),
                "key": extract_key(tags),
            }
        )

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", "artist", "title", "album", "key"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Catalog current key tags in the DJ library.")
    parser.add_argument("--library", type=Path, default=LIBRARY_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "catalog.csv")
    args = parser.parse_args()
    if not args.library.is_dir():
        raise SystemExit(f"Not a directory: {args.library}")
    count = catalog_library(args.library, args.output)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
