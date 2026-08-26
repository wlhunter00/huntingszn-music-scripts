"""Count Serato cues from Markers2 / Markers_ GEOB blobs — never from ID3 COMM.

Cue count = hot cues (CUE) + saved loops (LOOP). Track COLOR and BPMLOCK are
not cues. Named/colored cue points are CUE entries.
"""

from __future__ import annotations

import base64
import io
import struct
from dataclasses import dataclass

MARKERS2_GEOB = "Serato Markers2"
MARKERS_V1_GEOB = "Serato Markers_"
CUE_ENTRY_TYPES = frozenset({"CUE", "LOOP"})

MARKERS2_VERSION = (0x01, 0x01)
MARKERS_V1_VERSION = (0x02, 0x05)
MARKERS_V1_ENTRY_LEN = 22
MARKERS_V1_TYPE_CUE = 1
MARKERS_V1_TYPE_LOOP = 3
MARKERS_V1_SET = 0x00  # 0x00 = True, 0x7F = False


@dataclass(frozen=True)
class MarkerCounts:
    cues: int = 0
    loops: int = 0

    @property
    def total(self) -> int:
        return self.cues + self.loops


def _b64decode_serato(blob: bytes) -> bytes:
    """Decode Serato's slightly-invalid base64 (newlines; missing padding)."""
    cleaned = blob.replace(b"\n", b"").replace(b"\r", b"")
    if len(cleaned) % 4 == 1:
        cleaned += b"A"
    cleaned += b"=" * ((4 - len(cleaned) % 4) % 4)
    return base64.b64decode(cleaned)


def parse_markers2_counts(data: bytes) -> MarkerCounts:
    """Parse a ``GEOB:Serato Markers2`` payload and count CUE + LOOP entries."""
    if len(data) < 2:
        return MarkerCounts()
    version = tuple(data[:2])
    if version != MARKERS2_VERSION:
        raise ValueError(f"unsupported Serato Markers2 version: {version}")
    try:
        nul = data.index(b"\x00", 2)
    except ValueError:
        b64 = data[2:]
    else:
        b64 = data[2:nul]
    payload = _b64decode_serato(b64)
    if len(payload) < 2 or tuple(payload[:2]) != MARKERS2_VERSION:
        raise ValueError("invalid Markers2 inner payload")
    fp = io.BytesIO(payload[2:])
    cues = loops = 0
    while True:
        name_bytes = bytearray()
        while True:
            chunk = fp.read(1)
            if chunk in (b"", b"\x00"):
                break
            name_bytes.extend(chunk)
        if not name_bytes:
            break
        raw_len = fp.read(4)
        if len(raw_len) < 4:
            break
        (entry_len,) = struct.unpack(">I", raw_len)
        fp.read(entry_len)
        name = name_bytes.decode("ascii", errors="replace")
        if name == "CUE":
            cues += 1
        elif name == "LOOP":
            loops += 1
    return MarkerCounts(cues=cues, loops=loops)


def parse_markers_v1_counts(data: bytes) -> MarkerCounts:
    """Parse ``GEOB:Serato Markers_`` and count set cue/loop slots.

    Unused slots have start-position-set = 0x7F. Type 1 = cue, type 3 = loop.
    """
    if len(data) < 6:
        return MarkerCounts()
    version = tuple(data[:2])
    if version != MARKERS_V1_VERSION:
        raise ValueError(f"unsupported Serato Markers_ version: {version}")
    (count,) = struct.unpack(">I", data[2:6])
    body = data[6:]
    cues = loops = 0
    for i in range(count):
        start = i * MARKERS_V1_ENTRY_LEN
        entry = body[start : start + MARKERS_V1_ENTRY_LEN]
        if len(entry) < MARKERS_V1_ENTRY_LEN:
            break
        start_set = entry[0]
        entry_type = entry[20]
        if start_set != MARKERS_V1_SET:
            continue
        if entry_type == MARKERS_V1_TYPE_CUE:
            cues += 1
        elif entry_type == MARKERS_V1_TYPE_LOOP:
            loops += 1
    return MarkerCounts(cues=cues, loops=loops)


def combine_marker_counts(v2: MarkerCounts | None, v1: MarkerCounts | None) -> MarkerCounts:
    """Serato prefers Markers_ when present; skip if *either* store has cues."""
    v2 = v2 or MarkerCounts()
    v1 = v1 or MarkerCounts()
    return MarkerCounts(cues=max(v2.cues, v1.cues), loops=max(v2.loops, v1.loops))


def encode_markers2(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a Markers2 GEOB blob (for tests). Padded to Serato's 470-byte minimum."""
    inner = bytearray(struct.pack("BB", *MARKERS2_VERSION))
    for name, payload in entries:
        inner.extend(name.encode("ascii") + b"\x00")
        inner.extend(struct.pack(">I", len(payload)))
        inner.extend(payload)
    inner.append(0)
    b64 = base64.b64encode(bytes(inner))
    wrapped = b"\n".join(b64[i : i + 72] for i in range(0, len(b64), 72))
    out = struct.pack("BB", *MARKERS2_VERSION) + wrapped
    if len(out) < 470:
        out += b"\x00" * (470 - len(out))
    return out


def encode_cue_payload(*, index: int = 0, position_ms: int = 0, name: str = "") -> bytes:
    """Inner CUE entry bytes (Markers2)."""
    header = struct.pack(
        ">cBIc3s2s",
        b"\x00",
        index,
        position_ms,
        b"\x00",
        b"\xcc\x00\x00",
        b"\x00\x00",
    )
    return header + name.encode("utf-8") + b"\x00"


def encode_loop_payload(
    *,
    index: int = 0,
    start_ms: int = 0,
    end_ms: int = 1000,
    name: str = "",
) -> bytes:
    """Inner LOOP entry bytes (Markers2)."""
    header = struct.pack(
        ">cBII4s4sB?",
        b"\x00",
        index,
        start_ms,
        end_ms,
        b"\xff\xff\xff\xff",
        b"\x00\x27\xaa\xe1",
        0,
        False,
    )
    return header + name.encode("utf-8") + b"\x00"
