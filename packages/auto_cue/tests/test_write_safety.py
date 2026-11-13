from __future__ import annotations

import shutil
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from auto_cue import cli
from auto_cue.protection import check_protection, parse_crate_file
from auto_cue.tags import TrackTags, read_track_tags, write_track_beatgrid
from auto_cue.validate import CueSet
from mutagen.id3 import GEOB, ID3
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker


def legacy_markers(kind: int, *, set_slot: bool = True) -> bytes:
    entry = bytearray(b"\x7f" * 22)
    entry[0] = 0 if set_slot else 0x7f
    entry[20] = kind
    return b"\x02\x05" + struct.pack(">I", 1) + entry + b"\x07\x7f\x7f\x7f"


@pytest.mark.parametrize("kind", [1, 3])
def test_legacy_only_mp3_is_not_written(sample_mp3, kind):
    tags = ID3()
    tags.add(GEOB(encoding=0, mime="application/octet-stream",
                  desc="Serato Markers_", data=legacy_markers(kind)))
    tags.save(sample_mp3)
    before = sample_mp3.read_bytes()
    parsed = read_track_tags(sample_mp3)
    assert parsed.markers2 is None
    assert check_protection(parsed).protected
    result = cli.process_track(sample_mp3, write=True, replace_mik=True, use_llm=False)
    assert result.action == "skip-skip"
    assert "legacy cues or loops" in result.error
    assert sample_mp3.read_bytes() == before


@pytest.mark.parametrize("raw", [b"", b"\x02\x05", b"\x02\x05\x00\x00\x00\x01",
                                  legacy_markers(1)[:-4],
                                  b"\x00\x00\x00\x00\x00\x00"])
def test_malformed_legacy_markers_are_protected(raw):
    status = check_protection(TrackTags(path=Path("test.mp3"), markers_v1_raw=raw))
    assert status.protected
    assert "legacy marker error" in status.reasons[0]


def test_unused_legacy_slots_do_not_protect():
    tags = TrackTags(path=Path("test.mp3"), markers_v1_raw=legacy_markers(1, set_slot=False))
    assert not check_protection(tags).protected


def chunk(kind: bytes, data: bytes) -> bytes:
    return kind + struct.pack(">I", len(data)) + data


def test_nested_crate_paths_are_normalized(tmp_path):
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    crate = subcrates / "Sets%%House.crate"
    path = "DJ Music/Cafe\u0301.mp3"
    crate.write_bytes(chunk(b"vrsn", b"1.0") + chunk(
        b"otrk", chunk(b"ptrk", (path + "\0").encode("utf-16-be"))))
    assert parse_crate_file(crate) == ["DJ Music/Café.mp3"]


def test_empty_crate(tmp_path):
    crate = tmp_path / "empty.crate"
    crate.write_bytes(b"")
    assert parse_crate_file(crate) == []


@pytest.mark.parametrize("raw", [b"otrk", chunk(b"otrk", b"ptrk"),
                                  chunk(b"ptrk", b"\x00"), b"otrk\x00\x00\x00\x10"])
def test_malformed_crate_does_not_block_a_library_write(
    sample_mp3, tmp_path, monkeypatch, raw,
):
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    crate = subcrates / "Sets.crate"
    crate.write_bytes(raw)
    with pytest.raises(ValueError, match="cannot read crate"):
        parse_crate_file(crate)
    monkeypatch.setattr(cli, "serato_is_running", lambda: False)
    seen = []

    def record(path, **kwargs):
        seen.append(path)
        return cli.ProcessResult(path=path, action="skip-skip", error="has existing cues")

    monkeypatch.setattr(cli, "process_track", record)
    assert cli.main(["--file", str(sample_mp3), "--write", "--db",
                     str(tmp_path / "database V2")]) == 0
    assert seen == [sample_mp3]


@pytest.mark.parametrize("raw", [b"otrk", chunk(b"otrk", b"ptrk"),
                                  chunk(b"ptrk", b"\x00"), b"otrk\x00\x00\x00\x10"])
def test_malformed_requested_crate_aborts_before_processing(
    sample_mp3, tmp_path, monkeypatch, capsys, raw,
):
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    (subcrates / "Sets.crate").write_bytes(raw)
    monkeypatch.setattr(cli, "serato_is_running", lambda: False)
    monkeypatch.setattr(cli, "process_track", lambda *a, **kw: pytest.fail("must not process"))
    assert cli.main(["--file", str(sample_mp3), "--write", "--crate", "Sets", "--db",
                     str(tmp_path / "database V2")]) == 1
    assert "Cannot safely filter requested crate" in capsys.readouterr().err


def test_unreadable_crate_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="cannot read crate"):
        parse_crate_file(tmp_path / "missing.crate")


@pytest.mark.parametrize("fixture", ["sample_mp3", "sample_flac"])
def test_cli_backups_preserve_relative_paths_and_refuse_overwrite(
    fixture, request, tmp_path, monkeypatch,
):
    sample = request.getfixturevalue(fixture)
    library = tmp_path / "library"
    backup = tmp_path / "backup"
    grid = BeatGrid(markers=(TerminalMarker(position_s=0.1, bpm=128.0),))
    monkeypatch.setattr(cli, "extract_features", lambda *a: SimpleNamespace(total_beats=256))
    monkeypatch.setattr(cli, "predict_cues_rules", lambda *a: SimpleNamespace(confidence=1.0))
    monkeypatch.setattr(cli, "prediction_to_cue_set", lambda *a: CueSet(
        cue4=64, cue6=128, total_beats=256, confidences={4: 1.0, 6: 1.0}))
    originals = {}
    for folder in ["a", "b"]:
        path = library / folder / sample.name
        path.parent.mkdir(parents=True)
        shutil.copy2(sample, path)
        write_track_beatgrid(path, grid)
        originals[folder] = path.read_bytes()
        result = cli.process_track(path, write=True, use_llm=False,
                                   library_root=library, backup_root=backup)
        assert result.action == "write", result.error
        assert (backup / folder / sample.name).read_bytes() == originals[folder]

    path = library / "a" / sample.name
    shutil.copy2(sample, path)
    write_track_beatgrid(path, grid)
    before = path.read_bytes()
    result = cli.process_track(path, write=True, use_llm=False,
                               library_root=library, backup_root=backup)
    assert result.action == "error-write"
    assert path.read_bytes() == before
    assert (backup / "a" / sample.name).read_bytes() == originals["a"]
