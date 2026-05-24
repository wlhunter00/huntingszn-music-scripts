"""Crawl drive roots and inventory samples, projects, and presets."""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from config.paths import CATALOG_OUTPUT_DIR, DEFAULT_SAMPLE_ROOTS

FILE_TYPES: dict[str, dict] = {
    "Ableton Rack": {
        "extensions": [".adg"],
        "folders": ["rack", "racks", "audio effect", "midi effect", "instrument rack"],
    },
    "Ableton Project": {
        "extensions": [".als"],
        "folders": ["project", "projects", "sessions", "ableton"],
    },
    "Plugin Preset": {
        "extensions": [".fxp", ".vstpreset", ".adv", ".nmsv", ".preset", ".fxb"],
        "folders": ["preset", "presets", "serum", "vital", "massive", "sylenth"],
    },
    "Drum Sample": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": [
            "drum",
            "drums",
            "kick",
            "snare",
            "hat",
            "clap",
            "percussion",
            "oneshot",
        ],
    },
}


def classify(path: Path) -> str | None:
    lower_parts = [p.lower() for p in path.parts]
    ext = path.suffix.lower()
    for label, spec in FILE_TYPES.items():
        if ext in spec["extensions"]:
            if any(f in " ".join(lower_parts) for f in spec["folders"]):
                return label
            if label in ("Ableton Rack", "Ableton Project"):
                return label
    if ext in (".wav", ".aif", ".aiff", ".mp3"):
        return "Audio"
    return None


def scan(roots: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _, files in os.walk(root):
            for name in files:
                path = Path(dirpath) / name
                kind = classify(path)
                if not kind:
                    continue
                stat = path.stat()
                rows.append(
                    {
                        "path": str(path),
                        "type": kind,
                        "size_bytes": str(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory samples and projects.")
    parser.add_argument("--roots", nargs="*", type=Path, default=list(DEFAULT_SAMPLE_ROOTS))
    parser.add_argument(
        "--output",
        type=Path,
        default=CATALOG_OUTPUT_DIR / f"sample_inventory_{datetime.now():%Y-%m-%d}.csv",
    )
    args = parser.parse_args()
    rows = scan(args.roots)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "type", "size_bytes", "modified"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
