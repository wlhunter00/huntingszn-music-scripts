"""Platinum Notes prep: strip _pn -> normalize filenames -> write ID3 tags."""

from __future__ import annotations

import argparse
from pathlib import Path

from config.paths import PLATINUM_NOTES

from library_tools import metadata, pn_filename, pn_rename


def run_pipeline(
    root: Path,
    *,
    dry_run: bool,
    flip_style: bool,
    force_metadata: bool,
) -> None:
    print(f"Platinum Notes pipeline on {root}\n")

    print("=== Step 1/3: Strip _pn suffixes ===")
    renamed, skipped = pn_rename.rename_tree(root, dry_run=dry_run)
    print(f"Done: {renamed} renamed, {skipped} skipped.\n")

    print("=== Step 2/3: Normalize filenames ===")
    renamed, skipped = pn_filename.rename_tree(root, dry_run=dry_run, flip_style=flip_style)
    print(f"Done: {renamed} renamed, {skipped} unchanged.\n")

    print("=== Step 3/3: Write ID3 metadata ===")
    metadata.process_folder(root, force=force_metadata, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Platinum Notes prep in order: pn-rename -> pn-filename -> library-metadata."
        )
    )
    parser.add_argument("--root", type=Path, default=PLATINUM_NOTES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--flip-style",
        action="store_true",
        help="Optional: drop retail artist prefix on flips during filename normalization (off by default)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Update ID3 tags even when title and artist already exist",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")

    run_pipeline(
        args.root,
        dry_run=args.dry_run,
        flip_style=args.flip_style,
        force_metadata=args.force,
    )


if __name__ == "__main__":
    main()
