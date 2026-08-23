"""Drive-mount watcher: pull -> incremental index -> publish (never deletes B2).

``library-sync watch`` is the job. It reuses ``find_drive()`` (volume names
``Will Hunter Music`` / ``HuntingSzn``, no hardcoded ``H:``) and the same B2
env as ``status`` / ``publish``.

A burst of mount events is debounced. At most one pipeline runs at a time;
a trigger that arrives while a run is in flight is queued for one follow-up
after debounce. If the drive is not mounted the watcher idles (no B2 calls).
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType

from library_sync.db import LibraryDB
from library_sync.index import index_files
from library_sync.index_ableton import index_ableton
from library_sync.index_stems import index_stems
from library_sync.mount import find_drive
from library_sync.rclone import (
    RcloneConfig,
    RcloneError,
    publish_drive,
    publish_sqlite,
    publish_template,
    pull_drive,
)

DEFAULT_DEBOUNCE_S = 8.0
DEFAULT_POLL_S = 5.0
# Pipeline-level cap after rclone/B2 failures. rclone itself is also limited
# via _WATCH_RCLONE_ENV (do not hammer B2 with a full-drive copy every debounce).
DEFAULT_MAX_BACKOFF_S = 15 * 60

# Fail faster when rclone/B2 is missing or unreachable.
_WATCH_RCLONE_ENV = {
    "RCLONE_RETRIES": "1",
    "RCLONE_LOW_LEVEL_RETRIES": "1",
    "RCLONE_CONTIMEOUT": "30s",
}


class ProcessLock:
    """Non-blocking exclusive lock released when this process exits."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: object | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        fh.write(b"0")
        fh.flush()
        fh.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()
            self._fh = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def default_lock_path() -> Path:
    from library_sync.install_watch import local_data_dir

    return local_data_dir() / "watch.lock"


def watch_log_path(drive_root: Path) -> Path:
    """``{DRIVE}/Scripts/data/watch.log``."""
    return drive_root / "Scripts" / "data" / "watch.log"


def pc_watch_log_path() -> Path:
    """Per-PC fallback log. pythonw has no console; a yanked drive cannot be written."""
    from library_sync.install_watch import local_data_dir

    return local_data_dir() / "watch.log"


def _append_log_file(path: Path, line: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except OSError:
        return False


def append_watch_log(drive_root: Path | None, message: str) -> None:
    """Append a timestamped line to watch.log; fall back to the PC if the drive cannot be written.

    Task Scheduler runs the stub via ``pythonw`` (stdout is ``None``). ``print`` must
    not raise, or the pipeline never starts and the drive log is never created.
    """
    try:
        print(message, flush=True)
    except (OSError, AttributeError, RuntimeError, ValueError):
        pass
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} {message}\n"
    wrote_drive = False
    if drive_root is not None:
        wrote_drive = _append_log_file(watch_log_path(drive_root), line)
    if not wrote_drive:
        _append_log_file(pc_watch_log_path(), line)


def _index_roots(drive_root: Path) -> list[Path]:
    return [drive_root / "DJ Music", drive_root / "Platnium Notes"]


def _sqlite_path(drive_root: Path) -> Path:
    return drive_root / "Scripts" / "data" / "library.sqlite"


def load_drive_dotenv(drive_root: Path) -> bool:
    """Load ``{DRIVE}/Scripts/.env`` so B2 vars exist without a Task Scheduler cwd.

    ``python-dotenv``'s default ``load_dotenv()`` walks from ``cli.py``, not cwd.
    The stub does pass ``cwd={DRIVE}/Scripts`` into watch, but a uv cache layout
    or a process started from ``%LOCALAPPDATA%\\library-sync`` can miss the file.

    Resolves directory junctions/symlinks on ``Scripts``. Uses ``utf-8-sig`` so a
    Notepad UTF-8 BOM cannot turn ``B2_REMOTE`` into ``\\ufeffB2_REMOTE``. Writes
    values into ``os.environ`` so empty Task Scheduler / user-env placeholders
    cannot block the drive file (``load_dotenv(override=True)`` is not enough on
    every python-dotenv version when the existing value is ``""``). Skips
    ``MUSIC_DRIVE_ROOT`` so a pinned letter in ``.env`` cannot hide a remount.
    """
    env_path = drive_root / "Scripts" / ".env"
    try:
        resolved = env_path.resolve()
        if resolved.is_file():
            env_path = resolved
    except (OSError, RuntimeError):
        # USB/junction GetFinalPathNameByHandle can fail while the .env is still readable.
        pass
    if not env_path.is_file():
        return False
    from dotenv import dotenv_values

    try:
        values = dotenv_values(env_path, encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return False
    # MUSIC_DRIVE_ROOT in .env is a pinned letter (often H:). Loading it into a
    # long-lived watch process would hide HuntingSzn when Windows remounts as E:.
    for key, value in values.items():
        if not key or value is None or key == "MUSIC_DRIVE_ROOT":
            continue
        os.environ[key] = value
    return True


def index_drive(drive_root: Path, *, dry_run: bool = False) -> None:
    """Incremental index of tracks, stems, and Ableton projects."""
    sqlite_path = _sqlite_path(drive_root)
    index_roots = [path for path in _index_roots(drive_root) if path.exists()]
    with LibraryDB(sqlite_path, create=not dry_run) as db:
        index_files(db, drive_root, index_roots, dry_run=dry_run)
        index_stems(db, drive_root, dry_run=dry_run)
        index_ableton(db, drive_root, dry_run=dry_run)


def _watch_rclone_env() -> dict[str, str]:
    """rclone env for watch: fail fast, and keep a PC-local log under pythonw.

    ERROR (not INFO): a full DJ-library copy at INFO logs every file into
    ``%LOCALAPPDATA%`` with no rotation. Truncate at the start of each run so
    a previous failure cannot grow the file without bound.
    """
    env = dict(_WATCH_RCLONE_ENV)
    from library_sync.install_watch import local_data_dir

    log_dir = local_data_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return env
    log_path = log_dir / "rclone.log"
    try:
        log_path.write_bytes(b"")
    except OSError:
        pass
    env["RCLONE_LOG_FILE"] = str(log_path)
    env["RCLONE_LOG_LEVEL"] = "ERROR"
    return env


def run_watch_pipeline(
    drive_root: Path,
    *,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> int:
    """Pull -> incremental index -> publish. Never passes ``allow_delete``.

    Returns 0 on success (or dry-run / unconfigured B2 skip after logging),
    1 on rclone/B2 failure. Does not hang waiting for a missing rclone binary.
    """
    def write_log(message: str) -> None:
        append_watch_log(drive_root, message)
        if log is not None:
            log(message)

    load_drive_dotenv(drive_root)
    config = RcloneConfig.from_env(drive_root)
    sqlite_path = _sqlite_path(drive_root)

    rclone_env = _watch_rclone_env()
    saved_env = {key: os.environ.get(key) for key in rclone_env}
    os.environ.update(rclone_env)
    rclone_log = rclone_env.get("RCLONE_LOG_FILE")
    rclone_log_hint = f" (rclone log: {rclone_log})" if rclone_log else ""
    try:
        if not config.is_configured and not dry_run:
            write_log("failure: B2 not configured (B2_REMOTE / B2_BUCKET); skipping run")
            return 1

        write_log("start: pull (full B2 bucket -> drive, rclone copy --update, never delete)")
        try:
            pull_drive(drive_root, config, dry_run=dry_run, progress=False)
        except RcloneError as exc:
            write_log(f"failure: pull: {exc}{rclone_log_hint}")
            return 1

        write_log("start: incremental index")
        try:
            index_drive(drive_root, dry_run=dry_run)
        except Exception as exc:
            write_log(f"failure: index: {exc}")
            return 1

        if not dry_run and sqlite_path.exists():
            with LibraryDB(sqlite_path) as db:
                db.prepare_for_copy()

        write_log("start: publish (rclone copy --update, never delete from B2)")
        try:
            commands = publish_drive(
                drive_root,
                config,
                dry_run=dry_run,
                allow_delete=False,
                update=True,
                progress=False,
            )
            publish_sqlite(sqlite_path, config, dry_run=dry_run)
            publish_template(config, dry_run=dry_run)
        except RcloneError as exc:
            write_log(f"failure: publish: {exc}{rclone_log_hint}")
            return 1

        if any("--allow-delete" in cmd or cmd.split()[1:2] == ["sync"] for cmd in commands):
            write_log("failure: publish attempted a deleting sync; aborted")
            return 1

        write_log("finish: ok")
        return 0
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _root_key(path: Path) -> str:
    """Identity for remount detection. ``H:`` / ``H:\\`` are the same volume."""
    if path.drive:
        return path.drive[0].upper()
    return os.path.normcase(os.path.normpath(str(path)))


class WatchController:
    """Debounce mount bursts and refuse overlapping pipeline runs.

    - First tick with the drive mounted (login / already plugged in) schedules
      a run after debounce, not only a rising edge.
    - Rising edge (unmounted -> mounted) schedules a run and resets failure
      backoff (unplug/replug should not wait out a 15-minute cap).
    - A Windows letter change (H: -> E:) is treated as a remount even if the
      poll missed the unmounted gap; otherwise watch idles on the old run.
    - One in-flight run at a time; extra triggers queue a single follow-up.
    - A failed pipeline retries with exponential backoff (first retry after
      debounce, then 2x, 4x, … capped) so a persistent rclone error cannot
      republish the whole drive every few seconds.
    """

    def __init__(
        self,
        *,
        run_pipeline: Callable[[Path], int],
        debounce_s: float = DEFAULT_DEBOUNCE_S,
        max_backoff_s: float = DEFAULT_MAX_BACKOFF_S,
        monotonic: Callable[[], float] = time.monotonic,
        log: Callable[[Path | None, str], None] = append_watch_log,
    ) -> None:
        self._run_pipeline = run_pipeline
        self._debounce_s = debounce_s
        self._max_backoff_s = max_backoff_s
        self._monotonic = monotonic
        self._log = log
        self._started = False
        self._last_mounted = False
        self._last_key: str | None = None
        self._pending_at: float | None = None
        self._wait_s = debounce_s
        self._queued = False
        self._fail_count = 0
        self.in_flight = False

    def _schedule(self) -> None:
        if self.in_flight:
            self._queued = True
            return
        # A new debounce (startup, remount, H:→E:) replaces a failure retry.
        # Leaving _queued set caused a second full-drive publish after the
        # remount run succeeded — the R6 letter-change path after a yank.
        self._queued = False
        self._pending_at = self._monotonic()
        self._wait_s = self._debounce_s

    def observe(self, mounted: bool, drive_key: str | None = None) -> None:
        """Record mount state and schedule on startup-mounted, rising edge, or letter change."""
        first = not self._started
        self._started = True
        changed = (
            mounted
            and drive_key is not None
            and self._last_key is not None
            and drive_key != self._last_key
        )
        rising = mounted and (first or not self._last_mounted or changed)
        if rising:
            if not first:
                self._fail_count = 0
            self._schedule()
        self._last_mounted = mounted
        if mounted and drive_key is not None:
            self._last_key = drive_key
        elif not mounted:
            self._last_key = None

    def tick(self, drive_root: Path | None) -> str:
        """Advance debounce/queue. Returns the action taken this tick."""
        mounted = drive_root is not None
        key = _root_key(drive_root) if drive_root is not None else None
        self.observe(mounted, key)

        if self.in_flight:
            return "in_flight"

        if not mounted:
            had_work = self._queued or self._pending_at is not None
            self._queued = False
            self._pending_at = None
            if had_work:
                self._log(None, "skip: drive not mounted")
                return "skip_unmounted"
            return "idle"

        if self._queued and self._pending_at is None:
            self._queued = False
            self._pending_at = self._monotonic()
            if self._fail_count:
                self._wait_s = min(
                    self._debounce_s * (2 ** (self._fail_count - 1)),
                    self._max_backoff_s,
                )
                self._log(
                    drive_root,
                    f"queued: retry after {self._wait_s:g}s backoff "
                    f"(failure {self._fail_count})",
                )
            else:
                self._wait_s = self._debounce_s
                self._log(drive_root, "queued: running again after debounce")

        if self._pending_at is None:
            return "idle"

        elapsed = self._monotonic() - self._pending_at
        if elapsed < self._wait_s:
            return "wait_debounce"

        assert drive_root is not None
        self._pending_at = None
        self.in_flight = True
        failed = False
        try:
            self._log(drive_root, f"start: pipeline (drive={drive_root})")
            rc = self._run_pipeline(drive_root)
            if rc != 0:
                failed = True
                self._log(drive_root, f"finish: pipeline failed (exit {rc})")
            else:
                self._fail_count = 0
            return "run" if rc == 0 else "run_failed"
        except Exception as exc:
            failed = True
            self._log(drive_root, f"failure: {exc}")
            return "run_failed"
        finally:
            self.in_flight = False
            if failed:
                self._fail_count += 1
                self._queued = True


def watch_once(
    *,
    debounce_s: float = DEFAULT_DEBOUNCE_S,
    root: Path | None = None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    find: Callable[..., Path | None] | None = None,
    lock_path: Path | None = None,
) -> int:
    """Run the pipeline once if the drive is mounted; otherwise idle-exit 0."""
    finder = find if find is not None else find_drive
    drive = finder(root)
    if drive is None:
        return 0
    lock = ProcessLock(lock_path or default_lock_path())
    if not lock.acquire():
        append_watch_log(drive, "skip: run already in flight")
        return 0
    try:
        if debounce_s > 0:
            sleep(debounce_s)
            drive = finder(root)
            if drive is None:
                return 0
        return run_watch_pipeline(drive, dry_run=dry_run)
    finally:
        lock.release()


def watch_loop(
    *,
    debounce_s: float = DEFAULT_DEBOUNCE_S,
    poll_s: float = DEFAULT_POLL_S,
    root: Path | None = None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    find: Callable[..., Path | None] | None = None,
    run_pipeline: Callable[[Path], int] | None = None,
    should_stop: Callable[[], bool] | None = None,
    lock_path: Path | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Poll for the drive and run the pipeline on mount (including already mounted)."""
    pipeline = run_pipeline or (lambda drive: run_watch_pipeline(drive, dry_run=dry_run))
    finder = find if find is not None else find_drive
    controller = WatchController(
        run_pipeline=pipeline,
        debounce_s=debounce_s,
        monotonic=monotonic,
    )
    lock = ProcessLock(lock_path or default_lock_path())
    if not lock.acquire():
        drive = finder(root)
        append_watch_log(drive, "skip: run already in flight")
        return 0
    try:
        while True:
            if should_stop is not None and should_stop():
                return 0
            drive = finder(root)
            controller.tick(drive)
            if should_stop is not None and should_stop():
                return 0
            sleep(poll_s)
    finally:
        lock.release()


def cmd_watch(args: object) -> int:
    """CLI entry for ``library-sync watch``."""
    debounce_s = float(getattr(args, "debounce", DEFAULT_DEBOUNCE_S))
    poll_s = float(getattr(args, "poll_interval", DEFAULT_POLL_S))
    root = getattr(args, "root", None)
    dry_run = bool(getattr(args, "dry_run", False))
    once = bool(getattr(args, "once", False))

    if once:
        return watch_once(debounce_s=debounce_s, root=root, dry_run=dry_run)
    try:
        return watch_loop(
            debounce_s=debounce_s,
            poll_s=poll_s,
            root=root,
            dry_run=dry_run,
        )
    except KeyboardInterrupt:
        print("watch stopped", file=sys.stderr)
        return 0
