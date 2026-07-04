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
            "drum", "drums", "kick", "kicks", "snare", "snares", "hat", "hats",
            "clap", "claps", "percussion", "perc", "cymbals", "toms", "fills",
            "oneshot", "one shot",
        ],
    },
    "Bass Sample": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": ["bass", "808", "sub", "bass one shot", "bass oneshot"],
    },
    "FX / Riser": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": [
            "fx", "effect", "effects", "riser", "risers", "sweep", "sweeps",
            "impact", "impacts", "transition", "whoosh", "woosh", "downlifter", "uplifter",
        ],
    },
    "Loop": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": ["loop", "loops", "drum loop", "bass loop", "melody loop", "vocal loop"],
    },
    "Vocal Sample": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": ["vocal", "vocals", "vox", "acapella", "voice"],
    },
    "Synth Sample": {
        "extensions": [".wav", ".aif", ".aiff"],
        "folders": [
            "synth", "lead", "leads", "melody", "melodies", "pad", "pads", "pluck", "plucks",
        ],
    },
}

CSV_FIELDS = ["File Name", "Type", "Extension", "Folder", "Full Path", "Pack/Source"]


def sanitize_filename(filename: str) -> str:
    return filename.replace('"', '""')


def classify_file(filepath: str, filename: str, extension: str) -> str:
    lower_path = filepath.lower()
    lower_filename = filename.lower()
    path_parts = [part.strip() for part in lower_path.split(os.sep)]

    for folder in path_parts:
        if folder in ("fx", "effects"):
            return "FX / Riser"
        if folder == "drums" or "drum" in folder or "one shot" in folder or "oneshot" in folder:
            return "Drum Sample"
        if folder == "bass" or folder == "808s":
            return "Bass Sample"
        if folder in ("vocals", "vox"):
            return "Vocal Sample"
        if folder in ("synths", "leads"):
            return "Synth Sample"
        if folder in ("loops", "sequences"):
            return "Loop"

    extension = extension.lower()
    for file_type, type_info in FILE_TYPES.items():
        if extension not in type_info["extensions"]:
            continue
        if extension in (".adg", ".als", ".fxp", ".vstpreset", ".adv", ".nmsv", ".preset", ".fxb"):
            return file_type
        folder_patterns = type_info["folders"]
        for folder in path_parts:
            for pattern in folder_patterns:
                if pattern in folder:
                    return file_type
            if any(word in folder.replace(" ", "") for word in folder_patterns):
                return file_type

    search_text = " ".join(path_parts + lower_filename.split())
    if any(p in search_text for p in [
        "drum", "kick", "snare", "hat", "clap", "perc", "crash", "cymbal", "ride",
        "tom", "hihat", "hi-hat", "hi hat", "rimshot", "one shot", "oneshot",
    ]):
        return "Drum Sample"
    if any(p in search_text for p in [
        "fx", "effect", "riser", "impact", "sweep", "transition", "whoosh", "woosh",
        "downlifter", "uplifter", "reverse", "buildup", "build up",
    ]):
        return "FX / Riser"
    if any(p in search_text for p in ["bass", "808", "sub", "low end"]):
        return "Bass Sample"
    if any(p in search_text for p in ["loop", "loops", "sequence", "sequences"]):
        return "Loop"
    if any(p in search_text for p in ["vocal", "vox", "voice", "acapella", "vocal shot"]):
        return "Vocal Sample"
    if any(p in search_text for p in ["synth", "lead", "pad", "pluck", "arp", "melody", "chord"]):
        return "Synth Sample"
    return "Unknown"


def scan_directory(root_dir: Path) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    total_files = 0
    all_extensions = {ext for info in FILE_TYPES.values() for ext in info["extensions"]}

    for root, _, files in os.walk(root_dir):
        for file in files:
            _, extension = os.path.splitext(file)
            if extension.lower() not in all_extensions:
                continue
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, root_dir)
            folder = os.path.dirname(relative_path)
            file_type = classify_file(full_path, file, extension)
            path_parts = relative_path.split(os.sep)
            source = path_parts[0] if path_parts else "Unknown"
            inventory.append({
                "File Name": sanitize_filename(file),
                "Type": file_type,
                "Extension": extension,
                "Folder": sanitize_filename(folder),
                "Full Path": sanitize_filename(full_path),
                "Pack/Source": sanitize_filename(source),
            })
            total_files += 1
            if total_files % 1000 == 0:
                print(f"Processed {total_files} files in {root_dir}...")

    print(f"Found {total_files} files in {root_dir}")
    return inventory


def scan(roots: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for root in roots:
        if not root.is_dir():
            print(f"Directory not found: {root}")
            continue
        rows.extend(scan_directory(root))
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
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
