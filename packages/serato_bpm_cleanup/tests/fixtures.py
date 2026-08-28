"""Shared MP3 / GEOB fixtures for tests."""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import COMM, GEOB, ID3, TBPM
from serato_bpm_cleanup.autotags import AutoTags, dump_autotags
from serato_bpm_cleanup.beatgrid import BeatGrid, TerminalMarker, dump_beatgrid
from serato_bpm_cleanup.markers import (
    MARKERS2_GEOB,
    encode_cue_payload,
    encode_loop_payload,
    encode_markers2,
)
from serato_bpm_cleanup.tags import AUTOTAGS_GEOB, BEATGRID_GEOB

MIN_MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 512


def write_silence_mp3(path: Path) -> Path:
    path.write_bytes(MIN_MP3)
    ID3().save(path)
    return path


def _id3(path: Path) -> ID3:
    return ID3(path)


def add_geob(path: Path, desc: str, data: bytes) -> None:
    tags = _id3(path)
    tags.add(
        GEOB(
            encoding=0,
            mime="application/octet-stream",
            desc=desc,
            data=data,
        )
    )
    tags.save(path)


def set_tbpm(path: Path, bpm: str) -> None:
    tags = _id3(path)
    tags.delall("TBPM")
    tags.add(TBPM(encoding=3, text=[bpm]))
    tags.save(path)


def add_comment(path: Path, text: str) -> None:
    tags = _id3(path)
    tags.add(COMM(encoding=3, lang="eng", desc="", text=[text]))
    tags.save(path)


def empty_markers2() -> bytes:
    return encode_markers2(
        [
            ("COLOR", b"\x00\xff\xff\xff"),
            ("BPMLOCK", b"\x00"),
        ]
    )


def markers2_with_cues(n: int) -> bytes:
    entries: list[tuple[str, bytes]] = [
        ("COLOR", b"\x00\xff\xff\xff"),
        ("BPMLOCK", b"\x00"),
    ]
    for i in range(n):
        entries.append(
            ("CUE", encode_cue_payload(index=i, position_ms=1000 * (i + 1), name=f"CUE{i}"))
        )
    return encode_markers2(entries)


def markers2_with_loop() -> bytes:
    return encode_markers2(
        [
            ("COLOR", b"\x00\xff\xff\xff"),
            ("BPMLOCK", b"\x00"),
            ("LOOP", encode_loop_payload(name="LOOP")),
        ]
    )


def constant_grid(bpm: float, position_s: float = 0.215) -> bytes:
    grid = BeatGrid(markers=(TerminalMarker(position_s=position_s, bpm=bpm),), footer=0x37)
    return dump_beatgrid(grid)


def make_track(
    folder: Path,
    name: str,
    *,
    bpm: float,
    cues: int = 0,
    loop: bool = False,
    comment: str | None = None,
    first_beat_s: float = 0.215,
) -> Path:
    path = folder / name
    write_silence_mp3(path)
    set_tbpm(path, f"{bpm:.2f}")
    add_geob(path, BEATGRID_GEOB, constant_grid(bpm, first_beat_s))
    add_geob(path, AUTOTAGS_GEOB, dump_autotags(AutoTags(bpm=bpm, autogain=-3.257, gaindb=0.0)))
    if loop:
        add_geob(path, MARKERS2_GEOB, markers2_with_loop())
    elif cues:
        add_geob(path, MARKERS2_GEOB, markers2_with_cues(cues))
    else:
        add_geob(path, MARKERS2_GEOB, empty_markers2())
    if comment:
        add_comment(path, comment)
    return path


def id3_geob(path: Path, desc: str) -> bytes:
    tags = ID3(path)
    for frame in tags.getall("GEOB"):
        if frame.desc == desc:
            return bytes(frame.data)
    raise AssertionError(f"missing GEOB {desc}")
