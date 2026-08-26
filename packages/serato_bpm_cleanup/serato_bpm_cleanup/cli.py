"""serato-bpm-cleanup — round fractional Serato BPMs (dry-run by default)."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from serato_bpm_cleanup import (
    ACTION_FIX,
    ACTION_SKIP_ALREADY_INTEGER,
    ACTION_SKIP_HAS_CUES,
    ACTION_SKIP_NO_BPM,
    FRACTION_THRESHOLD,
    __version__,
)
from serato_bpm_cleanup.backup import timestamped_backup_root
from serato_bpm_cleanup.detect import (
    default_database_path,
    default_library_roots,
    serato_is_running,
)
from serato_bpm_cleanup.process import apply_database_updates, apply_fix, inspect_library

CLOSE_SERATO_WARNING = (
    "WARNING: Close Serato DJ Pro before writing. Serato can overwrite tags on exit. "
    "Dry-run does not mutate files."
)

EPILOG = f"""
Default is dry-run: nothing is written. Pass --write to mutate files.

What --write actually rewrites (only tracks with 0 Serato cues/loops):
  • ID3 TBPM
  • GEOB "Serato Autotags" BPM (if present)
  • GEOB "Serato BeatGrid" terminal BPM on constant (single-marker) grids,
    keeping the first-beat offset
  • `_Serato_/database V2` field tbpm when --db is set / auto-detected

What is never rewritten:
  • Tracks with any Serato hot cues, loops, or named/colored markers
  • Dynamic (multi-marker) beatgrids — BPM tags may still be rounded
  • Rekordbox files, cue GEOB payloads, B2, or any deletes

Close Serato DJ Pro before --write. This tool prints a close-Serato warning
even on dry-run, and --write refuses if Serato appears to be running.

Bad BPM means abs(bpm - round(bpm)) >= {FRACTION_THRESHOLD}. Proposed fix is
nearest integer (128.31 → 128, 127.6 → 128). Tempo is never doubled/halved.

Cue count comes from Serato Markers2 / Markers_ GEOB, never from ID3 COMM.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serato-bpm-cleanup",
        description=(
            "Identify fractional Serato BPMs and (with --write) round them to "
            "integers. Default is dry-run."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=None,
        help="Audio folder (or file) to scan. Auto-detects DJ Music / C:\\Users\\Will on Windows.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to Serato `database V2`. Auto-detects Music/_Serato_ and drive-root _Serato_.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Mutate tags/DB. Refuses if Serato appears to be running. Backs up files first.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional CSV of the report (path, bpm, proposed, cue-count, action).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Directory for copies of mutated files (default: ./serato-bpm-cleanup-backups/<utc>).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _print_table(reports: list, file=None) -> None:
    if file is None:
        file = sys.stdout
    headers = ("path", "bpm", "proposed", "cues", "action")
    rows: list[tuple[str, str, str, str, str]] = []
    for report in reports:
        bpm = "" if report.current_bpm is None else f"{report.current_bpm:.2f}"
        proposed = "" if report.proposed_bpm is None else str(report.proposed_bpm)
        rows.append((str(report.path), bpm, proposed, str(report.cue_count), report.action))

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    print(fmt(headers), file=file)
    print("  ".join("-" * w for w in widths), file=file)
    for row in rows:
        print(fmt(row), file=file)


def _write_csv(path: Path, reports: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["path", "current_bpm", "proposed_bpm", "cue_count", "action", "rewrites", "notes"]
        )
        for report in reports:
            writer.writerow(
                [
                    str(report.path),
                    "" if report.current_bpm is None else f"{report.current_bpm:.2f}",
                    "" if report.proposed_bpm is None else report.proposed_bpm,
                    report.cue_count,
                    report.action,
                    report.rewrites,
                    report.notes,
                ]
            )


def _summarize(reports: list) -> dict[str, int]:
    counts = {
        ACTION_FIX: 0,
        ACTION_SKIP_HAS_CUES: 0,
        ACTION_SKIP_ALREADY_INTEGER: 0,
        ACTION_SKIP_NO_BPM: 0,
        "error": 0,
    }
    for report in reports:
        counts[report.action] = counts.get(report.action, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    print(CLOSE_SERATO_WARNING, file=sys.stderr)

    library_roots = default_library_roots(args.library)
    if not library_roots:
        print(
            "Could not auto-detect a music library. Pass --library PATH.",
            file=sys.stderr,
        )
        return 2
    missing = [root for root in library_roots if not root.exists()]
    if missing:
        print(f"Library path not found: {missing[0]}", file=sys.stderr)
        return 2

    db_path = default_database_path(args.db, library_roots)
    db_bytes = None
    if db_path is not None:
        if not db_path.is_file():
            print(f"Serato database not found: {db_path}", file=sys.stderr)
            if args.db is not None:
                return 2
            db_path = None
        else:
            db_bytes = db_path.read_bytes()

    running = serato_is_running()
    if running:
        print("Serato appears to be running.", file=sys.stderr)
        if args.write:
            print(
                "Refusing --write while Serato is running. Close Serato DJ Pro and retry.",
                file=sys.stderr,
            )
            return 1

    reports = inspect_library(library_roots, db_bytes=db_bytes)
    _print_table(reports)

    cue_skips = [r for r in reports if r.action == ACTION_SKIP_HAS_CUES]
    if cue_skips:
        print("\nHas cues, left alone:")
        for report in cue_skips:
            bpm_s = "" if report.current_bpm is None else f"{report.current_bpm:.2f}"
            print(f"  {report.path}  ({report.cue_count} cue(s), bpm={bpm_s})")

    counts = _summarize(reports)
    mode = "write" if args.write else "dry-run"
    print(
        f"\n[{mode}] fix={counts.get(ACTION_FIX, 0)} "
        f"skip-has-cues={counts.get(ACTION_SKIP_HAS_CUES, 0)} "
        f"skip-already-integer={counts.get(ACTION_SKIP_ALREADY_INTEGER, 0)} "
        f"skip-no-bpm={counts.get(ACTION_SKIP_NO_BPM, 0)} "
        f"errors={counts.get('error', 0)}"
    )
    if db_path is not None:
        print(f"Serato DB: {db_path}")

    if args.csv is not None:
        _write_csv(args.csv, reports)
        print(f"CSV: {args.csv}")

    errors = [r for r in reports if r.action == "error"]
    if not args.write:
        return 1 if errors else 0

    backup_base = args.backup_dir or Path("serato-bpm-cleanup-backups")
    backup_root = timestamped_backup_root(backup_base)
    written = 0
    write_errors = 0
    library_root = library_roots[0] if library_roots else None
    for report in reports:
        if report.action != ACTION_FIX:
            continue
        try:
            stores = apply_fix(report, backup_root=backup_root, library_root=library_root)
            if stores:
                written += 1
                print(f"wrote {report.path}: {', '.join(stores)}")
        except Exception as exc:  # noqa: BLE001
            write_errors += 1
            print(f"error writing {report.path}: {exc}", file=sys.stderr)

    db_updated = 0
    if db_path is not None and db_path.is_file():
        try:
            db_updated = apply_database_updates(db_path, reports, backup_root=backup_root)
            if db_updated:
                print(f"updated {db_updated} row(s) in {db_path}")
        except Exception as exc:  # noqa: BLE001
            write_errors += 1
            print(f"error updating Serato database: {exc}", file=sys.stderr)

    if written or db_updated:
        print(f"Backups: {backup_root}")
    print(f"Mutated {written} audio file(s).")

    if errors or write_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
