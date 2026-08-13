"""CLI for library-sync.

Subcommands:
- detect   — print drive path or "not mounted"
- index    — scan + upsert sqlite
- publish  — index (unless --skip-index) + rclone copy audio + sqlite
- pull     — rclone sync projects/ → Ready to Mix/
- query    — search by camelot/bpm/text
- status   — drive mounted?, sqlite path, track count, last updated, B2 env set?
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from library_sync.db import LibraryDB
from library_sync.index import index_files
from library_sync.mount import find_drive
from library_sync.query import format_tracks_table, query_tracks, tracks_to_json
from library_sync.rclone import (
    RcloneConfig,
    publish_audio,
    publish_sqlite,
    publish_template,
    pull_projects,
)


def _get_paths(args_root: Path | None) -> tuple[Path | None, Path, list[Path]]:
    """Get drive root, sqlite path, and index roots.

    Returns (drive_root, sqlite_path, index_roots)
    """
    drive_root = find_drive(args_root)
    if drive_root is None:
        return None, Path("library.sqlite"), []

    scripts_root = drive_root / "Scripts"
    sqlite_path = scripts_root / "data" / "library.sqlite"
    index_roots = [
        drive_root / "DJ Music",
        drive_root / "Platnium Notes",
    ]
    return drive_root, sqlite_path, index_roots


def _resolve_db_path(explicit_db: Path | None) -> Path:
    """Resolve database path for query/status (works without drive mounted).

    Fallback order:
    1. explicit --db PATH if provided
    2. {drive}/Scripts/data/library.sqlite if drive is mounted
    3. LIBRARY_SQLITE env variable
    4. CWD library.sqlite
    """
    if explicit_db is not None:
        return explicit_db

    drive_root = find_drive()
    if drive_root is not None:
        return drive_root / "Scripts" / "data" / "library.sqlite"

    env_path = os.environ.get("LIBRARY_SQLITE")
    if env_path:
        return Path(env_path)

    return Path("library.sqlite")


def cmd_detect(args: argparse.Namespace) -> int:
    """Detect and print drive path."""
    drive = find_drive()
    if drive:
        print(drive)
        return 0
    print("not mounted")
    return 2


def cmd_index(args: argparse.Namespace) -> int:
    """Index audio files into SQLite."""
    drive_root, sqlite_path, index_roots = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    index_roots = [r for r in index_roots if r.exists()]
    if not index_roots:
        print("Error: no index roots found", file=sys.stderr)
        return 2

    print(f"Drive: {drive_root}")
    print(f"SQLite: {sqlite_path}")
    print(f"Index roots: {', '.join(str(r) for r in index_roots)}")
    print()

    def progress(action: str, path: str, track: object) -> None:
        if args.dry_run:
            print(f"[dry-run] {action}: {path}")
        elif action != "skip":
            print(f"{action}: {path}")

    with LibraryDB(sqlite_path) as db:
        stats = index_files(
            db,
            drive_root,
            index_roots,
            dry_run=args.dry_run,
            progress_callback=progress,
        )

    print()
    print(f"Scanned: {stats['scanned']}")
    print(f"Added: {stats['added']}")
    print(f"Updated: {stats['updated']}")
    print(f"Skipped (unchanged): {stats['skipped']}")
    print(f"Marked missing: {stats['missing']}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Index and publish to B2."""
    drive_root, sqlite_path, index_roots = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    config = RcloneConfig.from_env()

    if not args.skip_index:
        print("=== Indexing ===")
        with LibraryDB(sqlite_path) as db:
            stats = index_files(
                db,
                drive_root,
                [r for r in index_roots if r.exists()],
                dry_run=args.dry_run,
            )
        print(f"Indexed: {stats['added']} new, {stats['updated']} updated")
        print()

    print("=== Publishing to B2 ===")
    if not config.is_configured:
        print("B2 not configured (B2_REMOTE / B2_BUCKET not set)")
        print("Showing planned commands:")
        print()

    publish_audio(drive_root, config, dry_run=args.dry_run)
    publish_sqlite(sqlite_path, config, dry_run=args.dry_run)
    publish_template(config, dry_run=args.dry_run)

    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """Pull projects from B2."""
    drive_root, _, _ = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    config = RcloneConfig.from_env()

    print("=== Pulling projects from B2 ===")
    if not config.is_configured:
        print("B2 not configured (B2_REMOTE / B2_BUCKET not set)")
        print("Showing planned command:")
        print()

    pull_projects(drive_root, config, dry_run=args.dry_run)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query tracks by camelot/bpm/text."""
    sqlite_path = _resolve_db_path(args.db)

    if not sqlite_path.exists():
        print(f"Error: database not found at {sqlite_path}", file=sys.stderr)
        return 2

    with LibraryDB(sqlite_path) as db:
        tracks = query_tracks(
            db,
            camelot=args.camelot,
            bpm=args.bpm,
            text_search=args.q,
            role=args.role,
            limit=args.limit,
        )

    if args.json:
        print(json.dumps(tracks_to_json(tracks), indent=2))
    else:
        print(format_tracks_table(tracks))
        print(f"\n{len(tracks)} track(s) found")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of drive, database, and B2 config."""
    drive_root = find_drive()
    sqlite_path = _resolve_db_path(args.db)
    config = RcloneConfig.from_env()

    print("=== Library Sync Status ===")
    print()

    if drive_root:
        print(f"Drive: {drive_root} (mounted)")
    else:
        print("Drive: not mounted")

    print(f"SQLite: {sqlite_path}")

    if sqlite_path.exists():
        with LibraryDB(sqlite_path) as db:
            total = db.count_tracks()
            present = db.count_tracks(status="present")
            missing = db.count_tracks(status="missing")
            last_updated = db.get_last_updated()
        print(f"  Total tracks: {total}")
        print(f"  Present: {present}")
        print(f"  Missing: {missing}")
        print(f"  Last updated: {last_updated or 'never'}")
    else:
        print("  (database does not exist)")

    print()
    print("=== B2 Configuration ===")
    print(f"B2_REMOTE: {'set' if config.remote else 'not set'}")
    print(f"B2_BUCKET: {'set' if config.bucket else 'not set'}")
    print(f"MASHUP_TEMPLATE_PATH: {config.mashup_template_path or 'not set'}")
    print(f"B2 ready: {'yes' if config.is_configured else 'no'}")

    return 0


def main() -> None:
    """Main CLI entry point."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="library-sync",
        description="Music library inventory: index portable HDD, sync to B2, query by key/BPM",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sub_detect = subparsers.add_parser("detect", help="Print drive path or 'not mounted'")
    sub_detect.set_defaults(func=cmd_detect)

    sub_index = subparsers.add_parser("index", help="Scan and index audio files into SQLite")
    sub_index.add_argument("--dry-run", action="store_true", help="Don't write to database")
    sub_index.add_argument("--root", type=Path, help="Override drive root path")
    sub_index.set_defaults(func=cmd_index)

    sub_publish = subparsers.add_parser("publish", help="Index and publish to B2")
    sub_publish.add_argument("--dry-run", action="store_true", help="Show planned commands only")
    sub_publish.add_argument("--skip-index", action="store_true", help="Skip indexing step")
    sub_publish.add_argument("--root", type=Path, help="Override drive root path")
    sub_publish.set_defaults(func=cmd_publish)

    sub_pull = subparsers.add_parser("pull", help="Pull projects from B2 to Ready to Mix")
    sub_pull.add_argument("--dry-run", action="store_true", help="Show planned command only")
    sub_pull.add_argument("--root", type=Path, help="Override drive root path")
    sub_pull.set_defaults(func=cmd_pull)

    sub_query = subparsers.add_parser("query", help="Query tracks by camelot/BPM/text")
    sub_query.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_query.add_argument("--camelot", help="Target Camelot key (e.g., 8A)")
    sub_query.add_argument("--bpm", type=float, help="Target BPM")
    sub_query.add_argument("--q", help="Text search in artist/title/filename")
    sub_query.add_argument(
        "--role", choices=["vocal", "drop", "unknown"], help="Filter by role"
    )
    sub_query.add_argument("--limit", type=int, help="Maximum results")
    sub_query.add_argument("--json", action="store_true", help="Output as JSON")
    sub_query.set_defaults(func=cmd_query)

    sub_status = subparsers.add_parser("status", help="Show status of drive, database, B2 config")
    sub_status.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
