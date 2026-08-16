"""CLI for library-sync.

Subcommands:
- detect       — print drive path or "not mounted"
- index        — scan all catalogs: tracks, stems, ableton projects
- publish      — index all catalogs + rclone copy FULL drive to B2 (sync with --allow-delete)
- pull         — rclone copy --update projects/ -> Ableton/Music Production Agent/
- watch        — pull -> incremental index -> publish when the drive is mounted
- install-watch — install a per-PC login stub (launchd / Task Scheduler / systemd)
- uninstall-watch — remove the per-PC login stub
- query        — search tracks by camelot/bpm/text
- query-stems  — search stem folders by name/model
- query-projects — search Ableton projects by name/kind
- status       — drive mounted?, sqlite path, counts for all catalogs

Note: Index catalogs tracks (DJ Music + Platnium Notes), stems, and Ableton projects.
      Publish mirrors the ENTIRE drive to B2 (excluding system files).
      watch never passes --allow-delete; it never auto-deletes remotes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from library_sync.db import AbletonProject, LibraryDB, Stem
from library_sync.index import index_files
from library_sync.index_ableton import index_ableton
from library_sync.index_stems import index_stems
from library_sync.install_watch import cmd_install_watch, cmd_uninstall_watch
from library_sync.mount import find_drive
from library_sync.query import format_tracks_table, query_tracks, tracks_to_json
from library_sync.rclone import (
    RcloneConfig,
    RcloneError,
    publish_drive,
    publish_sqlite,
    publish_template,
    pull_projects,
)
from library_sync.watch import DEFAULT_DEBOUNCE_S, DEFAULT_POLL_S, cmd_watch


def configure_stdio_utf8() -> None:
    """Keep CLI prints alive on Windows cp1252 consoles and under pythonw.

    ``pythonw.exe`` (Task Scheduler install-watch) sets ``sys.stdout`` /
    ``sys.stderr`` to ``None``. Bare ``print`` then raises and the watch
    pipeline never starts.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            stream = open(os.devnull, "w", encoding="utf-8", errors="replace")
            setattr(sys, name, stream)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


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


def _progress(dry_run: bool):
    n = 0

    def progress(action: str, path: str, item: object) -> None:
        nonlocal n
        if dry_run:
            print(f"[dry-run] {action}: {path}")
            return
        if action == "skip":
            return
        n += 1
        if n == 1 or n % 100 == 0:
            print(f"{action}: {path} ({n})")

    return progress


def parse_cli_limit(value: str) -> int:
    """Argparse type for --limit. 0 means unlimited; negatives are rejected."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit must be >= 0 (0 = unlimited)")
    return parsed


def _cli_limit(limit: int) -> int | None:
    """CLI --limit: 0 means unlimited."""
    return None if limit == 0 else limit


def _index_all_catalogs(
    db: LibraryDB,
    drive_root: Path,
    index_roots: list[Path],
    *,
    dry_run: bool,
    progress_callback: object = None,
) -> None:
    """Index tracks, stems, and Ableton projects."""
    existing_roots = [r for r in index_roots if r.exists()]
    print("=== Indexing Tracks (DJ Music + Platnium Notes) ===")
    track_stats = index_files(
        db,
        drive_root,
        existing_roots,
        dry_run=dry_run,
        progress_callback=progress_callback,
    )
    print(
        f"Tracks: {track_stats['added']} added, {track_stats['updated']} updated, "
        f"{track_stats['skipped']} skipped, {track_stats['missing']} missing"
    )
    print()

    print("=== Indexing Stems ===")
    stem_stats = index_stems(
        db,
        drive_root,
        dry_run=dry_run,
        progress_callback=progress_callback,
    )
    print(
        f"Stems: {stem_stats['added']} added, {stem_stats['updated']} updated, "
        f"{stem_stats['skipped']} skipped, {stem_stats['missing']} missing"
    )
    print()

    print("=== Indexing Ableton Projects ===")
    ableton_stats = index_ableton(
        db,
        drive_root,
        dry_run=dry_run,
        progress_callback=progress_callback,
    )
    print(
        f"Ableton: {ableton_stats['added']} added, {ableton_stats['updated']} updated, "
        f"{ableton_stats['skipped']} skipped, {ableton_stats['missing']} missing"
    )


def cmd_index(args: argparse.Namespace) -> int:
    """Index tracks, stems, and Ableton projects into SQLite."""
    drive_root, sqlite_path, index_roots = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    print(f"Drive: {drive_root}")
    print(f"SQLite: {sqlite_path}")
    print()

    with LibraryDB(sqlite_path, create=not args.dry_run) as db:
        _index_all_catalogs(
            db,
            drive_root,
            index_roots,
            dry_run=args.dry_run,
            progress_callback=_progress(args.dry_run),
        )

    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Index all catalogs and publish to B2."""
    drive_root, sqlite_path, index_roots = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    config = RcloneConfig.from_env(drive_root)

    if not args.skip_index:
        print("=== Indexing tracks, stems, and Ableton projects ===")
        with LibraryDB(sqlite_path, create=not args.dry_run) as db:
            _index_all_catalogs(
                db,
                drive_root,
                index_roots,
                dry_run=args.dry_run,
            )
        print()

    if not args.dry_run and sqlite_path.exists():
        with LibraryDB(sqlite_path) as db:
            db.prepare_for_copy()

    action = "sync (deletes remote extras)" if args.allow_delete else "copy (no remote deletes)"
    print(f"=== Publishing full drive to B2 via rclone {action} ===")
    if not config.is_configured:
        print("B2 not configured (B2_REMOTE / B2_BUCKET not set)")
        print("Showing planned commands:")
        print()

    try:
        publish_drive(
            drive_root,
            config,
            dry_run=args.dry_run,
            allow_delete=args.allow_delete,
        )
        publish_sqlite(sqlite_path, config, dry_run=args.dry_run)
        publish_template(config, dry_run=args.dry_run)
    except RcloneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    """Pull projects from B2 without deleting local Ableton work."""
    drive_root, _, _ = _get_paths(args.root)

    if drive_root is None:
        print("Error: drive not mounted", file=sys.stderr)
        return 2

    config = RcloneConfig.from_env(drive_root)

    print("=== Copying projects from B2 -> Ableton/Music Production Agent ===")
    if not config.is_configured:
        print("B2 not configured (B2_REMOTE / B2_BUCKET not set)")
        print("Showing planned command:")
        print()

    try:
        pull_projects(drive_root, config, dry_run=args.dry_run)
    except RcloneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query tracks by camelot/bpm/text."""
    sqlite_path = _resolve_db_path(args.db)

    if not sqlite_path.exists():
        print(f"Error: database not found at {sqlite_path}", file=sys.stderr)
        return 2

    with LibraryDB(sqlite_path, create=False) as db:
        tracks = query_tracks(
            db,
            camelot=args.camelot,
            bpm=args.bpm,
            text_search=args.q,
            role=args.role,
            limit=_cli_limit(args.limit),
        )

    if args.json:
        print(json.dumps(tracks_to_json(tracks), indent=2))
    else:
        print(format_tracks_table(tracks))
        print(f"\n{len(tracks)} track(s) found")

    return 0


def _stems_to_json(stems: list[Stem]) -> list[dict]:
    """Convert stems to JSON-serializable dicts."""
    return [
        {
            "id": s.id,
            "relative_path": s.relative_path,
            "song_name": s.song_name,
            "model": s.model,
            "has_vocals": bool(s.has_vocals),
            "has_drums": bool(s.has_drums),
            "has_bass": bool(s.has_bass),
            "has_other": bool(s.has_other),
            "has_no_vocals": bool(s.has_no_vocals),
            "file_size": s.file_size,
        }
        for s in stems
    ]


def _format_stems_table(stems: list[Stem]) -> str:
    """Format stems as a simple table."""
    if not stems:
        return "No stems found."
    lines = ["SONG NAME                              MODEL          V D B O N"]
    lines.append("-" * 65)
    for s in stems:
        flags = (
            f"{'V' if s.has_vocals else '-'} "
            f"{'D' if s.has_drums else '-'} "
            f"{'B' if s.has_bass else '-'} "
            f"{'O' if s.has_other else '-'} "
            f"{'N' if s.has_no_vocals else '-'}"
        )
        name = s.song_name[:38] if len(s.song_name) > 38 else s.song_name
        lines.append(f"{name:<38} {s.model:<14} {flags}")
    return "\n".join(lines)


def cmd_query_stems(args: argparse.Namespace) -> int:
    """Query stems by name/model."""
    sqlite_path = _resolve_db_path(args.db)

    if not sqlite_path.exists():
        print(f"Error: database not found at {sqlite_path}", file=sys.stderr)
        return 2

    with LibraryDB(sqlite_path, create=False) as db:
        stems = db.query_stems(
            text_search=args.q,
            model=args.model,
            limit=_cli_limit(args.limit),
        )

    if args.json:
        print(json.dumps(_stems_to_json(stems), indent=2))
    else:
        print(_format_stems_table(stems))
        print(f"\n{len(stems)} stem folder(s) found")

    return 0


def _ableton_to_json(projects: list[AbletonProject]) -> list[dict]:
    """Convert Ableton projects to JSON-serializable dicts."""
    return [
        {
            "id": p.id,
            "relative_path": p.relative_path,
            "name": p.name,
            "folder": p.folder,
            "kind": p.kind,
            "file_size": p.file_size,
        }
        for p in projects
    ]


def _format_ableton_table(projects: list[AbletonProject]) -> str:
    """Format Ableton projects as a simple table."""
    if not projects:
        return "No Ableton projects found."
    lines = ["NAME                                   FOLDER                    KIND"]
    lines.append("-" * 75)
    for p in projects:
        name = p.name[:38] if len(p.name) > 38 else p.name
        folder = p.folder[:24] if len(p.folder) > 24 else p.folder
        lines.append(f"{name:<38} {folder:<25} {p.kind}")
    return "\n".join(lines)


def cmd_query_projects(args: argparse.Namespace) -> int:
    """Query Ableton projects by name/kind."""
    sqlite_path = _resolve_db_path(args.db)

    if not sqlite_path.exists():
        print(f"Error: database not found at {sqlite_path}", file=sys.stderr)
        return 2

    with LibraryDB(sqlite_path, create=False) as db:
        projects = db.query_ableton(
            text_search=args.q,
            kind=args.kind,
            limit=_cli_limit(args.limit),
        )

    if args.json:
        print(json.dumps(_ableton_to_json(projects), indent=2))
    else:
        print(_format_ableton_table(projects))
        print(f"\n{len(projects)} project(s) found")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of drive, database, and B2 config."""
    drive_root = find_drive()
    sqlite_path = _resolve_db_path(args.db)
    config = RcloneConfig.from_env(drive_root)

    print("=== Library Sync Status ===")
    print()

    if drive_root:
        print(f"Drive: {drive_root} (mounted)")
    else:
        print("Drive: not mounted")

    print(f"SQLite: {sqlite_path}")

    if sqlite_path.exists():
        with LibraryDB(sqlite_path, create=False) as db:
            # Tracks
            track_total = db.count_tracks()
            track_present = db.count_tracks(status="present")
            track_missing = db.count_tracks(status="missing")
            last_updated = db.get_last_updated()

            # Stems
            stem_total = db.count_stems()
            stem_present = db.count_stems(status="present")
            stem_missing = db.count_stems(status="missing")

            # Ableton
            ableton_total = db.count_ableton()
            ableton_present = db.count_ableton(status="present")
            ableton_missing = db.count_ableton(status="missing")

        print()
        print("  Tracks (DJ Music + Platnium Notes):")
        print(f"    Total: {track_total}, Present: {track_present}, Missing: {track_missing}")
        print()
        print("  Stems (Stem Splitting/stem-output):")
        print(f"    Total: {stem_total}, Present: {stem_present}, Missing: {stem_missing}")
        print()
        print("  Ableton Projects:")
        print(f"    Total: {ableton_total}, Present: {ableton_present}, Missing: {ableton_missing}")
        print()
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
    configure_stdio_utf8()
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
    sub_publish.add_argument(
        "--allow-delete",
        action="store_true",
        help=(
            "Use rclone sync (deletes remote files not on the drive). "
            "Does not delete B2-only prefixes: projects/, metadata/, templates/. "
            "Default is copy."
        ),
    )
    sub_publish.add_argument("--root", type=Path, help="Override drive root path")
    sub_publish.set_defaults(func=cmd_publish)

    sub_pull = subparsers.add_parser(
        "pull", help="Pull projects from B2 to Ableton/Music Production Agent"
    )
    sub_pull.add_argument("--dry-run", action="store_true", help="Show planned command only")
    sub_pull.add_argument("--root", type=Path, help="Override drive root path")
    sub_pull.set_defaults(func=cmd_pull)

    sub_watch = subparsers.add_parser(
        "watch",
        help=(
            "When the music drive is mounted: pull from B2, incremental index, "
            "publish (copy --update; never deletes from B2)"
        ),
        description=(
            "Install once per PC with install-watch, then plug in the drive. "
            "watch runs pull -> incremental index -> publish (rclone copy --update). "
            "It never passes --allow-delete and never auto-deletes remotes. "
            "Log: {DRIVE}/Scripts/data/watch.log"
        ),
    )
    sub_watch.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once if the drive is mounted, then exit",
    )
    sub_watch.add_argument(
        "--debounce",
        type=float,
        default=DEFAULT_DEBOUNCE_S,
        help=f"Seconds to wait after a mount burst before running (default {DEFAULT_DEBOUNCE_S:g})",
    )
    sub_watch.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_S,
        help=f"Seconds between mount checks in daemon mode (default {DEFAULT_POLL_S:g})",
    )
    sub_watch.add_argument("--dry-run", action="store_true", help="Show planned rclone only")
    sub_watch.add_argument("--root", type=Path, help="Override drive root path")
    sub_watch.set_defaults(func=cmd_watch)

    sub_install = subparsers.add_parser(
        "install-watch",
        help="Install a per-PC login stub (Task Scheduler / launchd / systemd user)",
        description=(
            "Install once per PC (not on the HDD). After that, plugging in the "
            "HuntingSzn / Will Hunter Music drive runs pull -> index -> publish. "
            "Never deletes from B2. Discovers the drive by volume name; does not "
            "hardcode H:."
        ),
    )
    sub_install.add_argument("--dry-run", action="store_true", help="Print what would be installed")
    sub_install.set_defaults(func=cmd_install_watch)

    sub_uninstall = subparsers.add_parser(
        "uninstall-watch",
        help="Remove the per-PC login stub installed by install-watch",
    )
    sub_uninstall.add_argument("--dry-run", action="store_true", help="Print what would be removed")
    sub_uninstall.set_defaults(func=cmd_uninstall_watch)

    sub_query = subparsers.add_parser("query", help="Query tracks by camelot/BPM/text")
    sub_query.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_query.add_argument("--camelot", help="Target Camelot key (e.g., 8A)")
    sub_query.add_argument("--bpm", type=float, help="Target BPM")
    sub_query.add_argument("--q", help="Text search in artist/title/filename")
    sub_query.add_argument(
        "--role", choices=["vocal", "drop", "unknown"], help="Filter by role"
    )
    sub_query.add_argument(
        "--limit",
        type=parse_cli_limit,
        default=200,
        help="Maximum results (default 200; 0 = unlimited)",
    )
    sub_query.add_argument("--json", action="store_true", help="Output as JSON")
    sub_query.set_defaults(func=cmd_query)

    sub_query_stems = subparsers.add_parser("query-stems", help="Query stem folders by name/model")
    sub_query_stems.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_query_stems.add_argument("--q", help="Text search in song name")
    sub_query_stems.add_argument("--model", help="Filter by model (e.g., htdemucs_ft)")
    sub_query_stems.add_argument(
        "--limit",
        type=parse_cli_limit,
        default=200,
        help="Maximum results (default 200; 0 = unlimited)",
    )
    sub_query_stems.add_argument("--json", action="store_true", help="Output as JSON")
    sub_query_stems.set_defaults(func=cmd_query_stems)

    sub_query_projects = subparsers.add_parser(
        "query-projects", help="Query Ableton projects by name/kind"
    )
    sub_query_projects.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_query_projects.add_argument("--q", help="Text search in project name/folder")
    sub_query_projects.add_argument(
        "--kind", choices=["template", "project"], help="Filter by kind"
    )
    sub_query_projects.add_argument(
        "--limit",
        type=parse_cli_limit,
        default=200,
        help="Maximum results (default 200; 0 = unlimited)",
    )
    sub_query_projects.add_argument("--json", action="store_true", help="Output as JSON")
    sub_query_projects.set_defaults(func=cmd_query_projects)

    sub_status = subparsers.add_parser("status", help="Show status of drive, database, B2 config")
    sub_status.add_argument("--db", type=Path, help="Path to SQLite database")
    sub_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
