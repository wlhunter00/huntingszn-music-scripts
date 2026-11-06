from pathlib import Path

import pytest
from serato_bpm_cleanup.backup import backup_file


def test_backup_refuses_overwrite(tmp_path):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"original")
    dest = backup_file(src, tmp_path / "backups")
    src.write_bytes(b"changed")
    with pytest.raises(FileExistsError):
        backup_file(src, tmp_path / "backups")
    assert dest.read_bytes() == b"original"


@pytest.mark.parametrize("relative", [Path("../track.mp3"), Path("/track.mp3")])
def test_backup_rejects_non_relative_paths(tmp_path, relative):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"")
    with pytest.raises(ValueError, match="library-relative"):
        backup_file(src, tmp_path / "backups", relative=relative)
