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

from library_sync.cli import cmd_pull, cmd_watch, configure_stdio_utf8
from library_sync.cli import main as cli_main
from library_sync.install_watch import (
    LAUNCHD_LABEL,
    _xml_escape,
    render_launchd_plist,
    render_stub,
    render_systemd_unit,
    render_windows_cmd,
    render_windows_task_xml,
)
from library_sync.mount import VOLUME_NAME, VOLUME_NAME_ALT
from library_sync.rclone import publish_drive
from library_sync.watch import (
    ProcessLock,
    WatchController,
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
    ):
        captured["allow_delete"] = allow_delete
        captured["update"] = update
        result = publish_drive(
            drive_root,
            config,
            dry_run=dry_run,
            allow_delete=allow_delete,
            update=update,
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
    assert commands
    tokens = shlex.split(commands[0])
    assert tokens[0] == "rclone"
    assert tokens[1] == "copy"
    assert "--update" in tokens
    assert "sync" not in tokens
    assert "--allow-delete" not in tokens
    assert all("--allow-delete" not in cmd for cmd in commands)


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


def test_stub_bakes_install_path_and_never_once():
    stub = render_stub(Path("/opt/homebrew/bin/uv"), "/opt/homebrew/bin:/usr/bin")
    compile(stub, "watch-stub.py", "exec")
    ns: dict[str, object] = {}
    exec(compile(stub, "watch-stub.py", "exec"), ns)
    assert ns["PATH_PREFIX"] == "/opt/homebrew/bin:/usr/bin"
    assert ns["UV"] == "/opt/homebrew/bin/uv"
    assert "--once" not in stub


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
