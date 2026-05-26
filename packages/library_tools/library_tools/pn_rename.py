"""Strip _pn suffix from filenames under Platinum Notes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from config.paths import PLATINUM_NOTES


def rename_tree(root: Path, *, dry_run: bool) -> tuple[int, int]:
    renamed = 0
    skipped = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not re.search(r"_pn", path.name, re.IGNORECASE):
            continue
        new_name = re.sub(r"_pn", "", path.name, flags=re.IGNORECASE)
        if new_name == path.name:
            skipped += 1
            continue
        target = path.with_name(new_name)
        if target.exists():
            print(f"skip (exists): {path} -> {target}")
            skipped += 1
            continue
        print(f"{'[dry-run] ' if dry_run else ''}{path} -> {target}")
        if not dry_run:
            path.rename(target)
        renamed += 1
    return renamed, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove _pn from filenames under Platinum Notes.")
    parser.add_argument("--root", type=Path, default=PLATINUM_NOTES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")
    renamed, skipped = rename_tree(args.root, dry_run=args.dry_run)
    print(f"Done: {renamed} renamed, {skipped} skipped.")


if __name__ == "__main__":
    main()
