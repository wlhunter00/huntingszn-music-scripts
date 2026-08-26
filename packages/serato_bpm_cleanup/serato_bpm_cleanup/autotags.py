"""Serato Autotags GEOB: ASCII BPM + auto-gain + gain dB.

Layout (Holzhaus): version ``01 01``, then three NUL-terminated ASCII floats:
BPM (2 decimal places), auto-gain (3), gain dB (3).
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

AUTOTAGS_VERSION = (0x01, 0x01)


@dataclass(frozen=True)
class AutoTags:
    bpm: float
    autogain: float
    gaindb: float

    def with_bpm(self, bpm: float) -> AutoTags:
        return AutoTags(bpm=float(bpm), autogain=self.autogain, gaindb=self.gaindb)


def parse_autotags(data: bytes) -> AutoTags:
    fp = io.BytesIO(data)
    version = struct.unpack("BB", fp.read(2))
    if version != AUTOTAGS_VERSION:
        raise ValueError(f"unsupported Serato Autotags version: {version}")

    def _read_ascii_float() -> float:
        chars: list[bytes] = []
        while True:
            chunk = fp.read(1)
            if chunk in (b"", b"\x00"):
                break
            chars.append(chunk)
        return float(b"".join(chars).decode("ascii"))

    bpm = _read_ascii_float()
    autogain = _read_ascii_float()
    gaindb = _read_ascii_float()
    return AutoTags(bpm=bpm, autogain=autogain, gaindb=gaindb)


def dump_autotags(tags: AutoTags) -> bytes:
    parts = [
        struct.pack("BB", *AUTOTAGS_VERSION),
        f"{tags.bpm:.2f}".encode("ascii") + b"\x00",
        f"{tags.autogain:.3f}".encode("ascii") + b"\x00",
        f"{tags.gaindb:.3f}".encode("ascii") + b"\x00",
    ]
    return b"".join(parts)
