"""Scan Rift preset XML files and export catalog CSV."""

from __future__ import annotations

import argparse
import csv
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from config.paths import CATALOG_OUTPUT_DIR

DEFAULT_PRESET_DIR = Path(r"C:\ProgramData\Minimal\Rift\Presets")


def get_preset_info(file_path: str) -> dict[str, str]:
    preset_name = os.path.basename(file_path)
    preset_path = str(Path(file_path).parent)
    author = "Unknown"
    description = ""
    tags: list[str] = []
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        author_elem = root.find(".//Author")
        if author_elem is not None:
            author = author_elem.text or "Unknown"
        desc_elem = root.find(".//Description")
        if desc_elem is not None:
            description = desc_elem.text or ""
        tags_elem = root.find(".//Tags")
        if tags_elem is not None:
            tags = [tag.text for tag in tags_elem.findall(".//Tag") if tag.text]
    except ET.ParseError:
        print(f"Warning: Could not parse XML file: {file_path}")
    except Exception as exc:
        print(f"Warning: Error processing {file_path}: {exc}")
    return {
        "Preset Name": preset_name,
        "Author": author,
        "Description": description,
        "Tags": ", ".join(tags) if tags else "",
        "Path": preset_path,
    }


def scan_presets(preset_dir: Path) -> list[dict[str, str]]:
    presets: list[dict[str, str]] = []
    if not preset_dir.is_dir():
        print(f"Error: Preset directory not found at {preset_dir}")
        return presets
    for root, _, files in os.walk(preset_dir):
        for file in files:
            if file.lower().endswith(".xml"):
                presets.append(get_preset_info(os.path.join(root, file)))
    return presets


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Rift presets and export CSV.")
    parser.add_argument("--preset-dir", type=Path, default=DEFAULT_PRESET_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=CATALOG_OUTPUT_DIR / "rift_presets.csv",
    )
    args = parser.parse_args()
    print("Scanning for Rift presets...")
    presets = scan_presets(args.preset_dir)
    if not presets:
        print("No presets found!")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Preset Name", "Author", "Description", "Tags", "Path"]
    with args.output.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(presets)
    print(f"Exported {len(presets)} presets to {args.output}")


if __name__ == "__main__":
    main()
