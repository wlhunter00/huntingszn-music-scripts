"""Scan Minimal plugin XML files and export catalog CSV."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from config.paths import CATALOG_OUTPUT_DIR

DEFAULT_MINIMAL_DIR = Path(r"C:\ProgramData\Minimal")


def get_plugin_info(file_path: str) -> dict[str, str] | None:
    path_parts = Path(file_path).parts
    try:
        minimal_idx = path_parts.index("Minimal")
    except ValueError:
        return None
    plugin = path_parts[minimal_idx + 1] if len(path_parts) > minimal_idx + 1 else "Unknown"
    type_name = Path(file_path).parent.name
    return {
        "Name": os.path.basename(file_path),
        "Plugin": plugin,
        "Type": type_name,
        "Path": file_path,
    }


def scan_minimal_directory(minimal_dir: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not minimal_dir.is_dir():
        print(f"Error: Minimal directory not found at {minimal_dir}")
        return items
    for root, _, files in os.walk(minimal_dir):
        for file in files:
            if file.lower().endswith(".xml"):
                info = get_plugin_info(os.path.join(root, file))
                if info:
                    items.append(info)
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Minimal plugin XML and export CSV.")
    parser.add_argument("--minimal-dir", type=Path, default=DEFAULT_MINIMAL_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=CATALOG_OUTPUT_DIR / "minimal_plugins.csv",
    )
    args = parser.parse_args()
    print("Scanning Minimal directory for XML files...")
    items = scan_minimal_directory(args.minimal_dir)
    if not items:
        print("No XML files found!")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Name", "Plugin", "Type", "Path"]
    with args.output.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(items)
    print(f"Exported {len(items)} XML files to {args.output}")


if __name__ == "__main__":
    main()
