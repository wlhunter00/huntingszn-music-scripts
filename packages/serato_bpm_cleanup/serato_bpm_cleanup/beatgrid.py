"""Serato BeatGrid GEOB payload (Holzhaus / serato-tools layout).

Header: version ``01 00``, then uint32 marker count.
Non-terminal markers: float32 position_s + uint32 beats_till_next.
The last marker is always terminal: float32 position_s + float32 BPM.
Footer: 1 unknown byte (preserved on rewrite).

A *constant* grid has a single terminal marker. That is the only layout this
tool rewrites: BPM float is replaced, first-beat ``position_s`` and footer stay.
Multi-marker (dynamic) grids are left untouched — rewriting only the terminal
BPM would desync earlier segments.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

BEATGRID_VERSION = (0x01, 0x00)


@dataclass(frozen=True)
class NonTerminalMarker:
    position_s: float
    beats_till_next_marker: int


@dataclass(frozen=True)
class TerminalMarker:
    position_s: float
    bpm: float


@dataclass(frozen=True)
class BeatGrid:
    markers: tuple[NonTerminalMarker | TerminalMarker, ...]
    footer: int = 0

    @property
    def is_constant(self) -> bool:
        return len(self.markers) == 1 and isinstance(self.markers[0], TerminalMarker)

    @property
    def is_dynamic(self) -> bool:
        return any(isinstance(m, NonTerminalMarker) for m in self.markers)

    @property
    def terminal(self) -> TerminalMarker | None:
        for marker in reversed(self.markers):
            if isinstance(marker, TerminalMarker):
                return marker
        return None

    @property
    def bpm(self) -> float | None:
        terminal = self.terminal
        return None if terminal is None else float(terminal.bpm)

    @property
    def first_beat_s(self) -> float | None:
        if not self.markers:
            return None
        return float(self.markers[0].position_s)

    def with_constant_bpm(self, bpm: float) -> BeatGrid:
        """Replace terminal BPM on a constant grid. Raises if the grid is dynamic."""
        if not self.is_constant:
            raise ValueError("refusing to rewrite a dynamic (multi-marker) beatgrid")
        terminal = self.markers[0]
        assert isinstance(terminal, TerminalMarker)
        return BeatGrid(
            markers=(TerminalMarker(position_s=terminal.position_s, bpm=float(bpm)),),
            footer=self.footer,
        )


def parse_beatgrid(data: bytes) -> BeatGrid:
    """Parse a raw ``GEOB:Serato BeatGrid`` payload (not base64)."""
    fp = io.BytesIO(data)
    version = struct.unpack("BB", fp.read(2))
    if version != BEATGRID_VERSION:
        raise ValueError(f"unsupported Serato BeatGrid version: {version}")
    (count,) = struct.unpack(">I", fp.read(4))
    markers: list[NonTerminalMarker | TerminalMarker] = []
    for i in range(count):
        (position_s,) = struct.unpack(">f", fp.read(4))
        raw = fp.read(4)
        if i == count - 1:
            (bpm,) = struct.unpack(">f", raw)
            markers.append(TerminalMarker(position_s=position_s, bpm=bpm))
        else:
            (beats,) = struct.unpack(">I", raw)
            markers.append(NonTerminalMarker(position_s=position_s, beats_till_next_marker=beats))
    footer_byte = fp.read(1)
    footer = struct.unpack("B", footer_byte)[0] if footer_byte else 0
    leftover = fp.read()
    if leftover:
        raise ValueError(f"unexpected trailing BeatGrid bytes: {len(leftover)}")
    return BeatGrid(markers=tuple(markers), footer=footer)


def dump_beatgrid(grid: BeatGrid) -> bytes:
    """Serialize a BeatGrid back to a GEOB payload."""
    if not grid.markers or not isinstance(grid.markers[-1], TerminalMarker):
        raise ValueError("beatgrid must end with a terminal marker")
    fp = io.BytesIO()
    fp.write(struct.pack("BB", *BEATGRID_VERSION))
    fp.write(struct.pack(">I", len(grid.markers)))
    for marker in grid.markers:
        fp.write(struct.pack(">f", marker.position_s))
        if isinstance(marker, TerminalMarker):
            fp.write(struct.pack(">f", marker.bpm))
        else:
            fp.write(struct.pack(">I", marker.beats_till_next_marker))
    fp.write(struct.pack("B", grid.footer & 0xFF))
    return fp.getvalue()
