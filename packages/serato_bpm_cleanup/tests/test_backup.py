import errno
from pathlib import Path

import pytest
from serato_bpm_cleanup import backup
from serato_bpm_cleanup.backup import backup_file


def test_backup_refuses_overwrite(tmp_path):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")
    dest = backup_file(src, tmp_path / "backups")
    src.write_bytes(b"changed")
    with pytest.raises(FileExistsError):
        backup_file(src, tmp_path / "backups")
    assert dest.read_bytes() == b"original"


def test_backup_supports_long_filenames(tmp_path):
    src = tmp_path / ("a" * 239 + ".mp3")
    src.write_bytes(b"audio")
    assert backup_file(src, tmp_path / "backups").read_bytes() == b"audio"


def test_existing_backup_is_rejected_before_copying(tmp_path, monkeypatch):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")
    root = tmp_path / "backups"
    backup_file(src, root)
    monkeypatch.setattr(backup.shutil, "copyfileobj",
                        lambda *a: pytest.fail("must not copy an existing backup"))
    monkeypatch.setattr(backup.tempfile, "mkstemp",
                        lambda **kw: pytest.fail("must not create a temporary file"))
    with pytest.raises(FileExistsError):
        backup_file(src, root)


@pytest.mark.parametrize("relative", [Path("../track.mp3"), Path("/track.mp3")])
def test_backup_rejects_non_relative_paths(tmp_path, relative):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"")
    with pytest.raises(ValueError, match="library-relative"):
        backup_file(src, tmp_path / "backups", relative=relative)


@pytest.mark.parametrize("failure", ["copyfileobj", "copystat"])
def test_failed_backup_is_cleaned_and_can_retry(tmp_path, monkeypatch, failure):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original audio")
    root = tmp_path / "backups"

    def fail(*args, **kwargs):
        if failure == "copyfileobj":
            args[1].write(b"partial")
        raise OSError("simulated copy failure")

    with monkeypatch.context() as patch:
        patch.setattr(backup.shutil, failure, fail)
        with pytest.raises(OSError, match="simulated copy failure"):
            backup_file(src, root)
    assert list(root.iterdir()) == []
    dest = backup_file(src, root)
    assert dest.read_bytes() == src.read_bytes()
    assert list(root.iterdir()) == [dest]


def test_backup_falls_back_when_hard_links_are_invalid(tmp_path, monkeypatch):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")

    def unsupported(*args):
        error = OSError(errno.EINVAL, "Incorrect function")
        error.winerror = 1
        raise error

    monkeypatch.setattr(backup.os, "link", unsupported)
    dest = backup_file(src, tmp_path / "backups")
    assert dest.read_bytes() == b"original"


def test_backup_falls_back_without_hard_links(tmp_path, monkeypatch):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")
    root = tmp_path / "backups"

    def unsupported(*args):
        raise OSError(errno.EOPNOTSUPP, "no hard links")

    monkeypatch.setattr(backup.os, "link", unsupported)
    dest = backup_file(src, root)
    assert dest.read_bytes() == b"original"
    src.write_bytes(b"changed")
    with pytest.raises(FileExistsError):
        backup_file(src, root)
    assert dest.read_bytes() == b"original"
    assert list(root.iterdir()) == [dest]


def test_fallback_failure_is_cleaned_and_can_retry(tmp_path, monkeypatch):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")
    root = tmp_path / "backups"
    copy = backup.shutil.copyfileobj
    calls = 0

    def unsupported(*args):
        raise OSError(errno.EOPNOTSUPP, "no hard links")

    def fail_second_copy(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            target.write(b"partial")
            raise OSError("fallback failed")
        copy(source, target)

    monkeypatch.setattr(backup.os, "link", unsupported)
    with monkeypatch.context() as patch:
        patch.setattr(backup.shutil, "copyfileobj", fail_second_copy)
        with pytest.raises(OSError, match="fallback failed"):
            backup_file(src, root)
    assert list(root.iterdir()) == []
    assert backup_file(src, root).read_bytes() == b"original"
