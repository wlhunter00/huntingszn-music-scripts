import dataclasses
from pathlib import Path

import pytest

from library_tools.mik_clear_cues import (
    clear_mik_cues_rule,
    is_mik_comment,
    is_mik_cue_name,
    main,
    process_folder,
)
from serato_tools.track_cues_v2 import TrackCuesV2


def _cue(index: int, name: str) -> TrackCuesV2.CueEntry:
    return TrackCuesV2.CueEntry(
        field1=b"\x00",
        index=index,
        position=1000 * (index + 1),
        field4=b"\x00",
        color=TrackCuesV2.CueColors.RED.value,
        field6=b"\x00\x00",
        name=name,
    )


def test_is_mik_cue_name():
    assert is_mik_cue_name("Energy 7")
    assert is_mik_cue_name("energy 4")
    assert not is_mik_cue_name("DROP")
    assert not is_mik_cue_name("Energy")
    assert not is_mik_cue_name("")


def test_clear_mik_cues_rule_none_when_no_energy_cues():
    track = TrackCuesV2.TrackCuesInfo(cues=[_cue(0, "DROP")])
    assert clear_mik_cues_rule(track) is None


def test_clear_mik_cues_rule_drops_energy_keeps_others():
    drop = _cue(0, "DROP")
    energy = _cue(1, "Energy 7")
    loop = TrackCuesV2.LoopEntry(
        field1=b"\x00",
        index=0,
        startposition=0,
        endposition=4000,
        field5=b"\x00\x00\x00\x00",
        field6=b"\x00\x00\x00\x00",
        color=TrackCuesV2.CueColors.RED.value,
        locked=False,
        name="LOOP",
    )
    track = TrackCuesV2.TrackCuesInfo(cues=[drop, energy], loops=[loop])
    result = clear_mik_cues_rule(track)
    assert result is not None
    assert result.cues == [drop]
    assert result.loops == [loop]
    assert dataclasses.replace(track, cues=[drop]) == result


def test_is_mik_comment():
    assert is_mik_comment("9A - Energy 8")
    assert is_mik_comment("10B - Energy 7")
    assert not is_mik_comment("DROP")
    assert not is_mik_comment("")


def test_process_folder_strips_mik_comments(tmp_path: Path):
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, COMM

    folder = tmp_path / "spotify"
    folder.mkdir()
    track = folder / "Song.mp3"
    track.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
    EasyID3().save(track)
    id3 = ID3(track)
    id3.add(COMM(encoding=3, lang="eng", desc="", text=["9A - Energy 8"]))
    id3.add(COMM(encoding=3, lang="eng", desc="ID3v1 Comment", text=["9A - Energy 8"]))
    id3.add(COMM(encoding=3, lang="eng", desc="note", text=["keep this"]))
    id3.save(track)

    process_folder(tmp_path, dry_run=False)

    leftover = ID3(track).getall("COMM")
    texts = [str(frame.text[0]) for frame in leftover]
    assert texts == ["keep this"]


def test_main_requires_folder(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["mik-clear-cues"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "required" in err.lower() or "root" in err.lower()
