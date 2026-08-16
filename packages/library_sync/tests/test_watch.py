"""Tests for library-sync watch: debounce, skip-unmounted, never --allow-delete."""

from __future__ import annotations

import ast
import os
import plistlib
import re
import shlex
import sys
import xml.etree.ElementTree as ET
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from library_sync.cli import cmd_pull, cmd_watch, configure_stdio_utf8
from library_sync.cli import main as cli_main
from library_sync.install_watch import (
    LAUNCHD_LABEL,
    WINDOWS_TASK_NAME,
    _install_path_env,
    _xml_escape,
    render_launchd_plist,
    render_stub,
    render_systemd_unit,
    render_windows_cmd,
    render_windows_task_xml,
    resolve_uv,
    uninstall_watch,
)
from library_sync.mount import VOLUME_NAME, VOLUME_NAME_ALT, find_drive
from library_sync.rclone import publish_drive
from library_sync.watch import (
    DEFAULT_MAX_BACKOFF_S,
    ProcessLock,
    WatchController,
    append_watch_log,
    load_drive_dotenv,
    run_watch_pipeline,
    watch_loop,
    watch_once,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_debounce_burst_runs_pipeline_once(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(str(drive)) or 0,
        debounce_s=8,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()

    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(1)
    assert ctl.tick(drive) == "wait_debounce"
    assert ctl.tick(drive) == "wait_debounce"
    assert runs == []

    clock.advance(8)
    assert ctl.tick(drive) == "run"
    assert runs == [str(drive)]

    clock.advance(8)
    assert ctl.tick(drive) == "idle"
    assert len(runs) == 1


def test_already_mounted_at_start_still_runs_after_debounce(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append("go") or 0,
        debounce_s=2,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "Will Hunter Music"
    drive.mkdir()
    ctl.tick(drive)
    assert runs == []
    clock.advance(2)
    assert ctl.tick(drive) == "run"
    assert runs == ["go"]


def test_failed_pipeline_retries_after_debounce(tmp_path):
    runs: list[int] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(1) or 1,
        debounce_s=2,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "drive"
    drive.mkdir()
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    assert runs == [1]
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    assert runs == [1, 1]


def test_failed_pipeline_exponential_backoff_not_every_debounce(tmp_path):
    runs: list[int] = []
    logs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(1) or 1,
        debounce_s=2,
        max_backoff_s=10,
        monotonic=clock,
        log=lambda _drive, msg: logs.append(msg),
    )
    drive = tmp_path / "drive"
    drive.mkdir()
    ctl.tick(drive)
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    # Second retry waits 4s (2 * 2^(2-1)), not another 2s debounce.
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(drive) == "wait_debounce"
    assert runs == [1, 1]
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    assert runs == [1, 1, 1]
    # Third retry waits 8s; fourth is capped at 10s.
    ctl.tick(drive)
    clock.advance(8)
    assert ctl.tick(drive) == "run_failed"
    ctl.tick(drive)
    clock.advance(9)
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(1)
    assert ctl.tick(drive) == "run_failed"
    assert any("backoff" in line for line in logs)
    assert DEFAULT_MAX_BACKOFF_S >= 10


def test_remount_resets_failure_backoff(tmp_path):
    runs: list[int] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(1) or 1,
        debounce_s=2,
        max_backoff_s=60,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "drive"
    drive.mkdir()
    ctl.tick(drive)
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    ctl.tick(drive)
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    # Unplug / replug: do not sit out 4s+ backoff.
    assert ctl.tick(None) == "skip_unmounted"
    assert ctl.tick(drive) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(drive) == "run_failed"
    assert runs == [1, 1, 1]


def test_drive_letter_change_without_unmount_tick_retriggers(tmp_path):
    """Poll can miss the unmounted gap when H: is taken and HuntingSzn returns as E:."""
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(str(drive)) or 0,
        debounce_s=2,
        monotonic=clock,
        log=lambda *_: None,
    )
    old = tmp_path / "H"
    new = tmp_path / "E"
    old.mkdir()
    new.mkdir()
    ctl.tick(old)
    clock.advance(2)
    assert ctl.tick(old) == "run"
    assert runs == [str(old)]
    assert ctl.tick(new) == "wait_debounce"
    clock.advance(2)
    assert ctl.tick(new) == "run"
    assert runs == [str(old), str(new)]


def test_same_drive_path_does_not_retrigger(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(str(drive)) or 0,
        debounce_s=2,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    ctl.tick(drive)
    clock.advance(2)
    assert ctl.tick(drive) == "run"
    clock.advance(2)
    assert ctl.tick(drive) == "idle"
    assert ctl.tick(Path(drive)) == "idle"
    assert runs == [str(drive)]


def test_in_flight_run_queues_follow_up_instead_of_overlapping(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ctl: WatchController

    def pipeline(drive: Path) -> int:
        runs.append("start")
        ctl.observe(False)
        ctl.observe(True)
        assert ctl.tick(drive) == "in_flight"
        assert ctl.in_flight is True
        runs.append("end")
        return 0

    ctl = WatchController(
        run_pipeline=pipeline,
        debounce_s=0,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "drive"
    drive.mkdir()
    assert ctl.tick(drive) == "run"
    assert runs == ["start", "end"]
    assert ctl.tick(drive) == "run"
    assert runs == ["start", "end", "start", "end"]


def test_skip_when_unmounted_does_not_run_pipeline():
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append(str(drive)) or 0,
        debounce_s=8,
        monotonic=clock,
        log=lambda *_: None,
    )
    assert ctl.tick(None) == "idle"
    clock.advance(8)
    assert ctl.tick(None) == "idle"
    assert runs == []


def test_pending_run_skipped_if_drive_vanishes_during_debounce(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ctl = WatchController(
        run_pipeline=lambda drive: runs.append("ran") or 0,
        debounce_s=8,
        monotonic=clock,
        log=lambda *_: None,
    )
    drive = tmp_path / "drive"
    drive.mkdir()
    ctl.tick(drive)
    clock.advance(8)
    assert ctl.tick(None) == "skip_unmounted"
    assert runs == []


def test_watch_once_unmounted_skips_without_b2_or_rclone():
    called: list[str] = []

    def boom(*_a, **_k):
        called.append("pipeline")
        raise AssertionError("pipeline must not run when unmounted")

    with patch("library_sync.watch.run_watch_pipeline", side_effect=boom):
        with patch("library_sync.rclone.subprocess.run") as rclone:
            rc = watch_once(debounce_s=0, find=lambda explicit=None: None)
            rclone.assert_not_called()
    assert rc == 0
    assert called == []


def test_cmd_watch_once_unmounted_exits_0(monkeypatch):
    monkeypatch.setattr("library_sync.watch.find_drive", lambda explicit=None: None)
    rc = cmd_watch(Namespace(once=True, debounce=0, poll_interval=5, root=None, dry_run=False))
    assert rc == 0


def test_watch_pipeline_never_passes_allow_delete(tmp_path, monkeypatch):
    drive = tmp_path / "Will Hunter Music"
    drive.mkdir()
    captured: dict[str, object] = {}
    commands: list[str] = []

    def wrap(
        drive_root,
        config,
        *,
        dry_run=False,
        allow_delete=False,
        update=False,
        progress=True,
    ):
        captured["allow_delete"] = allow_delete
        captured["update"] = update
        captured["progress"] = progress
        result = publish_drive(
            drive_root,
            config,
            dry_run=dry_run,
            allow_delete=allow_delete,
            update=update,
            progress=progress,
        )
        commands.extend(result)
        return result

    monkeypatch.setattr("library_sync.watch.pull_projects", lambda *a, **k: "ok")
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)
    monkeypatch.setattr("library_sync.watch.publish_sqlite", lambda *a, **k: None)
    monkeypatch.setattr("library_sync.watch.publish_template", lambda *a, **k: None)
    monkeypatch.setattr("library_sync.watch.publish_drive", wrap)

    logs: list[str] = []
    rc = run_watch_pipeline(drive, dry_run=True, log=logs.append)
    assert rc == 0
    assert captured["allow_delete"] is False
    assert captured["update"] is True
    assert captured["progress"] is False
    assert commands
    tokens = shlex.split(commands[0])
    assert tokens[0] == "rclone"
    assert tokens[1] == "copy"
    assert "--update" in tokens
    assert "--progress" not in tokens
    assert "sync" not in tokens
    assert "--allow-delete" not in tokens
    assert all("--allow-delete" not in cmd for cmd in commands)


def test_watch_pipeline_loads_env_from_drive_scripts(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_text("B2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n", encoding="utf-8")
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("library_sync.watch.pull_projects", lambda *a, **k: "ok")
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)
    monkeypatch.setattr(
        "library_sync.watch.publish_drive",
        lambda *a, **k: ["rclone copy --update src dst"],
    )
    monkeypatch.setattr("library_sync.watch.publish_sqlite", lambda *a, **k: None)
    monkeypatch.setattr("library_sync.watch.publish_template", lambda *a, **k: None)
    rc = run_watch_pipeline(drive, dry_run=False)
    assert rc == 0
    assert os.environ["B2_REMOTE"] == "b2"
    assert os.environ["B2_BUCKET"] == "huntingszn-music"
    assert load_drive_dotenv(drive) is True


def test_load_drive_dotenv_utf8_bom(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_bytes(
        b"\xef\xbb\xbfB2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n"
    )
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"
    assert os.environ["B2_BUCKET"] == "huntingszn-music"
    assert "\ufeffB2_REMOTE" not in os.environ


def test_load_drive_dotenv_does_not_pin_music_drive_root(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_text(
        "MUSIC_DRIVE_ROOT=H:\\\nB2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MUSIC_DRIVE_ROOT", raising=False)
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"
    assert os.environ["B2_BUCKET"] == "huntingszn-music"
    assert "MUSIC_DRIVE_ROOT" not in os.environ


def test_watch_finds_volume_after_dotenv_stale_letter(tmp_path, monkeypatch):
    """User env / cli load_dotenv may pin H:; remount as another letter must still run."""
    stale = tmp_path / "not-mounted"
    monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(stale))
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
    monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: drive)
    monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
    assert find_drive() == drive


def test_watch_finds_volume_when_pinned_letter_exists_as_other_drive(tmp_path, monkeypatch):
    """cli load_dotenv pins H: from .env; H: occupied is why the stick is E:."""
    wrong = tmp_path / "OtherUSB"
    wrong.mkdir()
    drive = tmp_path / "HuntingSzn"
    (drive / "DJ Music").mkdir(parents=True)
    monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(wrong))
    monkeypatch.setattr("library_sync.mount.sys.platform", "win32")
    monkeypatch.setattr("library_sync.mount._find_windows_volume", lambda: drive)
    monkeypatch.setattr("library_sync.mount._find_windows_scripts_parent", lambda: None)
    assert find_drive() == drive
    assert find_drive() != wrong

    runs: list[str] = []
    clock = FakeClock()
    ticks = {"n": 0}

    def sleep(_s: float) -> None:
        clock.advance(8)

    def should_stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 4 or bool(runs)

    lock = tmp_path / "watch.lock"
    rc = watch_loop(
        debounce_s=8,
        poll_s=8,
        find=find_drive,
        run_pipeline=lambda d: runs.append(str(d)) or 0,
        sleep=sleep,
        should_stop=should_stop,
        lock_path=lock,
        monotonic=clock,
    )
    assert rc == 0
    assert runs == [str(drive)]


def test_watch_once_explicit_root_skips_env_and_volume_scan(tmp_path, monkeypatch):
    explicit = tmp_path / "custom-root"
    explicit.mkdir()
    monkeypatch.setenv("MUSIC_DRIVE_ROOT", str(tmp_path / "other"))
    monkeypatch.setattr(
        "library_sync.mount._find_windows_volume",
        lambda: (_ for _ in ()).throw(AssertionError("volume scan must not run")),
    )
    with patch("library_sync.watch.run_watch_pipeline", return_value=0) as pipeline:
        rc = watch_once(debounce_s=0, root=explicit, lock_path=tmp_path / "watch.lock")
    assert rc == 0
    pipeline.assert_called_once()
    assert pipeline.call_args[0][0] == explicit


def test_load_drive_dotenv_overrides_empty_env(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_text("B2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n", encoding="utf-8")
    monkeypatch.setenv("B2_REMOTE", "")
    monkeypatch.setenv("B2_BUCKET", "")
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"
    assert os.environ["B2_BUCKET"] == "huntingszn-music"


def test_load_drive_dotenv_follows_scripts_symlink(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    real_scripts = tmp_path / "real-scripts"
    drive.mkdir()
    real_scripts.mkdir()
    (real_scripts / ".env").write_text(
        "B2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n", encoding="utf-8"
    )
    try:
        (drive / "Scripts").symlink_to(real_scripts, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported")
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"


def test_load_drive_dotenv_loads_when_resolve_fails(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_text("B2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n", encoding="utf-8")
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)

    def boom(self):
        raise OSError("GetFinalPathNameByHandle")

    monkeypatch.setattr(Path, "resolve", boom)
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"
    assert os.environ["B2_BUCKET"] == "huntingszn-music"


def test_load_drive_dotenv_loads_when_resolve_raises_runtimeerror(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    scripts = drive / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / ".env").write_text("B2_REMOTE=b2\nB2_BUCKET=huntingszn-music\n", encoding="utf-8")
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    monkeypatch.setattr(
        Path, "resolve", lambda self: (_ for _ in ()).throw(RuntimeError("loop"))
    )
    assert load_drive_dotenv(drive) is True
    assert os.environ["B2_REMOTE"] == "b2"


def test_append_watch_log_survives_pythonw_none_stdout(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    monkeypatch.setattr(sys, "stdout", None)
    append_watch_log(drive, "start: pipeline")
    text = (drive / "Scripts" / "data" / "watch.log").read_text(encoding="utf-8")
    assert "start: pipeline" in text


def test_append_watch_log_falls_back_to_pc_when_drive_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr("library_sync.install_watch.local_data_dir", lambda: tmp_path / "pc")
    drive = tmp_path / "not-a-dir"
    drive.write_text("x", encoding="utf-8")
    append_watch_log(drive, "failure: publish")
    local = tmp_path / "pc" / "watch.log"
    assert local.is_file()
    assert "failure: publish" in local.read_text(encoding="utf-8")


def test_append_watch_log_unmounted_writes_pc_log(tmp_path, monkeypatch):
    monkeypatch.setattr("library_sync.install_watch.local_data_dir", lambda: tmp_path / "pc")
    append_watch_log(None, "skip: drive not mounted")
    text = (tmp_path / "pc" / "watch.log").read_text(encoding="utf-8")
    assert "skip: drive not mounted" in text


def test_watch_pipeline_sets_rclone_log_file(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    pc = tmp_path / "pc"
    seen: dict[str, str | None] = {}
    monkeypatch.setenv("B2_REMOTE", "b2")
    monkeypatch.setenv("B2_BUCKET", "huntingszn-music")
    monkeypatch.setattr("library_sync.install_watch.local_data_dir", lambda: pc)
    stale = pc / "rclone.log"
    stale.parent.mkdir(parents=True)
    stale.write_text("INFO : old file copied\n" * 50, encoding="utf-8")

    def fake_pull(*_a, **_k):
        seen["log"] = os.environ.get("RCLONE_LOG_FILE")
        seen["level"] = os.environ.get("RCLONE_LOG_LEVEL")
        seen["size"] = Path(seen["log"]).stat().st_size if seen["log"] else -1
        seen["progress"] = _k.get("progress")
        return "ok"

    monkeypatch.setattr("library_sync.watch.pull_projects", fake_pull)
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)
    monkeypatch.setattr(
        "library_sync.watch.publish_drive",
        lambda *a, **k: ["rclone copy --update src dst"],
    )
    monkeypatch.setattr("library_sync.watch.publish_sqlite", lambda *a, **k: None)
    monkeypatch.setattr("library_sync.watch.publish_template", lambda *a, **k: None)
    assert run_watch_pipeline(drive) == 0
    assert seen["log"] == str(pc / "rclone.log")
    assert seen["level"] == "ERROR"
    assert seen["size"] == 0
    assert seen["progress"] is False
    assert os.environ.get("RCLONE_LOG_FILE") != seen["log"]


def test_watch_pipeline_missing_template_does_not_fail_publish(tmp_path, monkeypatch):
    drive = tmp_path / "Will Hunter Music"
    drive.mkdir()
    monkeypatch.setenv("B2_REMOTE", "b2")
    monkeypatch.setenv("B2_BUCKET", "huntingszn-music")
    monkeypatch.setattr("library_sync.watch.pull_projects", lambda *a, **k: "ok")
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)
    captured: list[str] = []

    def wrap(
        drive_root,
        config,
        *,
        dry_run=False,
        allow_delete=False,
        update=False,
        progress=True,
    ):
        result = publish_drive(
            drive_root,
            config,
            dry_run=True,
            allow_delete=allow_delete,
            update=update,
            progress=progress,
        )
        captured.extend(result)
        return result

    monkeypatch.setattr("library_sync.watch.publish_drive", wrap)
    monkeypatch.setattr("library_sync.watch.publish_sqlite", lambda *a, **k: None)
    # Real publish_template: path missing -> None, must not raise.
    rc = run_watch_pipeline(drive, dry_run=True)
    assert rc == 0
    tokens = shlex.split(captured[0])
    assert tokens[1] == "copy"
    assert "--progress" not in tokens
    assert "sync" not in tokens


def test_watch_pipeline_missing_rclone_logs_and_returns(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    monkeypatch.setenv("B2_REMOTE", "b2")
    monkeypatch.setenv("B2_BUCKET", "huntingszn-music")
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)

    logs: list[str] = []
    with patch("library_sync.rclone.subprocess.run", side_effect=FileNotFoundError("rclone")):
        rc = run_watch_pipeline(drive, log=logs.append)
    assert rc == 1
    assert any("failure: pull" in line for line in logs)
    assert any("rclone not found" in line for line in logs)
    log_file = drive / "Scripts" / "data" / "watch.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "failure: pull" in text


def test_watch_pipeline_unconfigured_b2_does_not_hang(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    logs: list[str] = []
    with patch("library_sync.rclone.subprocess.run") as rclone:
        rc = run_watch_pipeline(drive, log=logs.append)
        rclone.assert_not_called()
    assert rc == 1
    assert any("B2 not configured" in line for line in logs)


def test_watch_loop_stop_after_debounced_run(tmp_path):
    runs: list[str] = []
    clock = FakeClock()
    ticks = {"n": 0}

    def sleep(_s: float) -> None:
        clock.advance(8)

    def should_stop() -> bool:
        ticks["n"] += 1
        return ticks["n"] > 4 or bool(runs)

    drive = tmp_path / "drive"
    drive.mkdir()
    lock = tmp_path / "watch.lock"
    rc = watch_loop(
        debounce_s=8,
        poll_s=8,
        find=lambda explicit=None: drive,
        run_pipeline=lambda d: runs.append(str(d)) or 0,
        sleep=sleep,
        should_stop=should_stop,
        lock_path=lock,
        monotonic=clock,
    )
    assert rc == 0
    assert len(runs) == 1


def test_process_lock_second_acquire_fails(tmp_path):
    path = tmp_path / "watch.lock"
    first = ProcessLock(path)
    second = ProcessLock(path)
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def test_watch_once_skips_when_lock_held(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    lock_path = tmp_path / "watch.lock"
    holder = ProcessLock(lock_path)
    assert holder.acquire() is True
    try:
        with patch("library_sync.watch.run_watch_pipeline") as pipeline:
            rc = watch_once(
                debounce_s=0,
                find=lambda explicit=None: drive,
                lock_path=lock_path,
            )
            pipeline.assert_not_called()
        assert rc == 0
        log = (drive / "Scripts" / "data" / "watch.log").read_text(encoding="utf-8")
        assert "already in flight" in log
    finally:
        holder.release()


def test_stub_discovers_volume_names_not_drive_letter():
    stub = render_stub(Path("/opt/homebrew/bin/uv"))
    assert VOLUME_NAME in stub
    assert VOLUME_NAME_ALT in stub
    assert "HuntingSzn" in stub
    assert "Will Hunter Music" in stub
    assert "H:\\" not in stub
    assert "H:" not in stub
    assert "--package" in stub
    assert "library-sync" in stub
    assert "watch" in stub
    assert "PYTHONUTF8" in stub


def test_launchd_plist_is_local_and_utf8_safe(tmp_path):
    uv = Path("/opt/homebrew/bin/uv")
    stub = tmp_path / "watch-stub.py"
    plist = render_launchd_plist(uv, stub, "/opt/homebrew/bin:/usr/bin")
    assert LAUNCHD_LABEL in plist
    assert str(uv) in plist
    assert str(stub) in plist
    assert "PYTHONUTF8" in plist
    assert "<true/>" in plist
    assert "RunAtLoad" in plist
    assert "KeepAlive" in plist
    assert "H:" not in plist
    assert "WorkingDirectory" not in plist


def test_windows_task_xml_ignores_overlapping_and_has_no_drive_letter(tmp_path):
    cmd = tmp_path / "watch-stub.cmd"
    xml = render_windows_task_xml(cmd)
    assert "IgnoreNew" in xml
    assert "PT0S" in xml
    assert "LogonTrigger" in xml
    assert str(cmd) in xml
    assert "H:" not in xml
    assert "<Hidden>true</Hidden>" in xml
    wrapper = render_windows_cmd(
        Path(r"C:\Users\Will\.local\bin\uv.exe"),
        tmp_path / "watch-stub.py",
        r"C:\Users\Will\.local\bin;C:\Windows\system32",
    )
    assert "PYTHONUTF8=1" in wrapper
    assert "H:" not in wrapper
    assert r"C:\Users\Will\.local\bin" in wrapper
    assert "%PATH%" in wrapper


def test_systemd_unit_restarts_and_sets_utf8(tmp_path):
    unit = render_systemd_unit(Path("/usr/bin/uv"), tmp_path / "watch-stub.py", "/usr/bin")
    assert "Restart=always" in unit
    assert "PYTHONUTF8=1" in unit
    assert "library-sync" in unit.lower() or "watch-stub" in unit


def test_pull_banner_is_ascii_arrow(capsys, monkeypatch, tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr("library_sync.cli.find_drive", lambda explicit=None: drive)
    monkeypatch.delenv("B2_REMOTE", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    rc = cmd_pull(Namespace(root=None, dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "->" in out
    assert "\u2192" not in out


def test_configure_stdio_utf8_sets_env(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    configure_stdio_utf8()
    assert os.environ["PYTHONUTF8"] == "1"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"


def test_configure_stdio_utf8_replaces_none_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    configure_stdio_utf8()
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdout.fileno() >= 0
    assert sys.stderr.fileno() >= 0
    sys.stdout.write("ok")
    sys.stdout.flush()


def test_watch_pipeline_rclone_oserror_is_logged(tmp_path, monkeypatch):
    drive = tmp_path / "HuntingSzn"
    drive.mkdir()
    monkeypatch.setenv("B2_REMOTE", "b2")
    monkeypatch.setenv("B2_BUCKET", "huntingszn-music")
    monkeypatch.setattr("library_sync.watch.index_drive", lambda *a, **k: None)
    logs: list[str] = []
    with patch(
        "library_sync.rclone.subprocess.run",
        side_effect=OSError(6, "The handle is invalid"),
    ):
        rc = run_watch_pipeline(drive, log=logs.append)
    assert rc == 1
    assert any("failure: pull" in line for line in logs)
    assert any("handle is invalid" in line for line in logs)


def test_stub_is_valid_python():
    stub = render_stub(Path("/usr/bin/uv"))
    compile(stub, "watch-stub.py", "exec")
    assert "HuntingSzn" in stub
    assert "Will Hunter Music" in stub


def test_xml_escape_emits_entities():
    assert _xml_escape('a<b>c"d&e') == "a&lt;b&gt;c&quot;d&amp;e"


def test_launchd_plist_is_well_formed_plist(tmp_path):
    uv = Path("/opt/homebrew/bin/uv")
    stub = tmp_path / "Application Support" / "library-sync" / "watch-stub.py"
    plist = render_launchd_plist(uv, stub, "/opt/homebrew/bin:/usr/bin")
    data = plistlib.loads(plist.encode("utf-8"))
    assert data["Label"] == LAUNCHD_LABEL
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True
    assert data["ProgramArguments"] == [
        str(uv),
        "run",
        "--python",
        "3.12",
        str(stub),
    ]
    assert data["EnvironmentVariables"]["PYTHONUTF8"] == "1"
    assert data["EnvironmentVariables"]["PATH"].startswith("/opt/homebrew/bin")


def test_windows_task_xml_is_well_formed_utf16(tmp_path):
    cmd = tmp_path / "Will & Co" / "watch-stub.cmd"
    cmd.parent.mkdir()
    xml = render_windows_task_xml(
        cmd,
        arguments=f'"{cmd}"',
        user_id=r"WILLS-GAMING\Will & Co",
        working_directory=cmd.parent,
    )
    assert "&amp;" in xml
    assert "&quot;" in xml
    path = tmp_path / "watch-task.xml"
    path.write_text(xml, encoding="utf-16")
    assert path.read_bytes()[:2] == b"\xff\xfe"
    tree = ET.parse(path)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert tree.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert tree.find(".//t:ExecutionTimeLimit", ns).text == "PT0S"
    assert tree.find(".//t:Hidden", ns).text == "true"
    assert tree.find(".//t:Count", ns).text == "999"
    assert tree.find(".//t:Command", ns).text == str(cmd)
    assert tree.find(".//t:Arguments", ns).text == f'"{cmd}"'
    assert tree.find(".//t:WorkingDirectory", ns).text == str(cmd.parent)
    user_ids = [node.text for node in tree.findall(".//t:UserId", ns)]
    assert user_ids == [r"WILLS-GAMING\Will & Co", r"WILLS-GAMING\Will & Co"]


def test_stub_windows_root_is_drive_root_not_cwd():
    stub = render_stub(Path("/usr/bin/uv"), r"C:\Users\Will\.local\bin")
    compile(stub, "watch-stub.py", "exec")
    match = re.search(r"root_s = letter \+ (\".*\")", stub)
    assert match is not None
    suffix = ast.literal_eval(match.group(1))
    assert suffix == ":\\"
    assert len(suffix) == 2
    assert "H" + suffix == "H:\\"
    assert "GetLogicalDrives" in stub
    assert "GetVolumeInformationW.argtypes" in stub
    assert "--once" not in stub
    assert "time.sleep(POLL_S if rc != 0 else 2)" not in stub
    assert "PATH_PREFIX" in stub
    assert "CREATE_NO_WINDOW" in stub
    assert 'cmd = [UV, "run", "--package", "library-sync", "library-sync", "watch"]' in stub
    assert "cwd=str(scripts)" in stub
    assert 'endswith((".cmd", ".bat"))' in stub
    assert "0x08000000" in stub
    assert "0x01000000" not in stub


def test_stub_bakes_install_path_and_never_once():
    stub = render_stub(Path("/opt/homebrew/bin/uv"), "/opt/homebrew/bin:/usr/bin")
    compile(stub, "watch-stub.py", "exec")
    ns: dict[str, object] = {}
    exec(compile(stub, "watch-stub.py", "exec"), ns)
    assert ns["PATH_PREFIX"] == "/opt/homebrew/bin:/usr/bin"
    assert ns["UV"] == "/opt/homebrew/bin/uv"
    assert "--once" not in stub
    assert "cwd=str(scripts)" in stub


def test_install_path_env_puts_rclone_dir_ahead_of_uv(tmp_path, monkeypatch):
    rclone_dir = tmp_path / "rclone-bin"
    uv_dir = tmp_path / "uv-bin"
    rclone_dir.mkdir()
    uv_dir.mkdir()
    rclone = rclone_dir / "rclone"
    uv = uv_dir / "uv"
    rclone.write_text("", encoding="utf-8")
    uv.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "library_sync.install_watch.shutil.which",
        lambda name: str(rclone) if name == "rclone" else None,
    )
    monkeypatch.setenv("PATH", "/usr/bin")
    path = _install_path_env(uv)
    parts = path.split(os.pathsep)
    assert str(rclone_dir.resolve()) == parts[0]
    assert str(uv_dir) in parts


def test_install_path_env_windows_includes_common_rclone_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("library_sync.install_watch.sys.platform", "win32")
    local = tmp_path / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr("library_sync.install_watch.shutil.which", lambda name: None)
    monkeypatch.setenv("PATH", "C:\\Windows\\system32")
    path = _install_path_env(tmp_path / "uv.exe")
    assert "WinGet" in path
    assert "rclone" in path


def test_resolve_uv_prefers_exe_over_cmd_shim(tmp_path, monkeypatch):
    exe = tmp_path / "uv.exe"
    cmd = tmp_path / "uv.cmd"
    exe.write_text("x", encoding="utf-8")
    cmd.write_text("x", encoding="utf-8")
    monkeypatch.setattr("library_sync.install_watch.shutil.which", lambda name: str(cmd))
    assert resolve_uv() == exe.resolve()


def test_uninstall_windows_ends_then_force_deletes_task(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr("library_sync.install_watch.sys.platform", "win32")
    monkeypatch.setattr("library_sync.install_watch.local_data_dir", lambda: tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("library_sync.install_watch._run", fake_run)
    (tmp_path / "watch-task.xml").write_text("<Task/>", encoding="utf-8")
    (tmp_path / "watch-stub.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "watch-stub.cmd").write_text("@echo off\r\n", encoding="utf-8")
    rc = uninstall_watch()
    assert rc == 0
    assert ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME] in calls
    assert ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"] in calls
    assert not (tmp_path / "watch-stub.py").exists()
    assert not (tmp_path / "watch-task.xml").exists()


def test_watch_help_says_never_deletes_from_b2(capsys):
    with patch.object(sys, "argv", ["library-sync", "watch", "--help"]):
        try:
            cli_main()
        except SystemExit as exc:
            assert exc.code == 0
    out = capsys.readouterr().out
    normalized = " ".join(out.split())
    assert "never passes --allow-delete" in normalized
    assert "pull" in normalized.lower()
    assert "publish" in normalized.lower()
