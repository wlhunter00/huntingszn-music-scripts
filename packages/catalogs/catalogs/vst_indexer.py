"""Scan Windows VST folders and export plugin inventory to CSV."""

from __future__ import annotations

import argparse
import csv
import os
import winreg
from pathlib import Path

from config.paths import CATALOG_OUTPUT_DIR

DEFAULT_VST_FOLDERS = (
    r"C:\Program Files (x86)\Steinberg",
    r"C:\Program Files\Common Files\VST3",
    r"C:\Program Files\Common Files\VstPlugins",
)


def get_vst_folders() -> list[str]:
    folders = list(DEFAULT_VST_FOLDERS)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VST") as key:
            try:
                vst_path = winreg.QueryValueEx(key, "VSTPluginsPath")[0]
                if vst_path and os.path.exists(vst_path):
                    folders.append(vst_path)
            except OSError:
                pass
    except OSError:
        pass
    return folders


def get_plugin_info(file_path: str) -> dict[str, str]:
    plugin_name = os.path.basename(file_path)
    plugin_type = "VST3" if file_path.lower().endswith(".vst3") else "VST2"
    category = "Unknown"
    vendor = "Unknown"
    lower_name = plugin_name.lower()
    if "synth" in lower_name:
        category = "Synth"
    elif "eq" in lower_name:
        category = "EQ"
    elif "comp" in lower_name:
        category = "Compressor"
    elif "reverb" in lower_name:
        category = "Reverb"
    elif "delay" in lower_name:
        category = "Delay"
    path_parts = Path(file_path).parts
    if len(path_parts) > 1:
        vendor = path_parts[-2]
    return {
        "Plugin Name": plugin_name,
        "Type": plugin_type,
        "Category": category,
        "Vendor": vendor,
        "Path": file_path,
    }


def scan_plugins(folders: list[str]) -> list[dict[str, str]]:
    plugins: list[dict[str, str]] = []
    for folder in folders:
        if not os.path.exists(folder):
            continue
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith((".vst3", ".dll")):
                    plugins.append(get_plugin_info(os.path.join(root, file)))
    return plugins


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan VST plugin folders and export CSV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=CATALOG_OUTPUT_DIR / "vst_plugins.csv",
    )
    args = parser.parse_args()
    print("Scanning for VST plugins...")
    plugins = scan_plugins(get_vst_folders())
    if not plugins:
        print("No plugins found!")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Plugin Name", "Type", "Category", "Vendor", "Path"]
    with args.output.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(plugins)
    print(f"Exported {len(plugins)} plugins to {args.output}")


if __name__ == "__main__":
    main()
