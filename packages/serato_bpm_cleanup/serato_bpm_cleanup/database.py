"""Serato ``database V2`` BPM field (``tbpm`` UTF-16-BE text inside ``otrk``).

TLV layout matches crates (Holzhaus / pyserato / serato-tools): 4-byte ASCII
tag, 4-byte big-endian length, payload. ``t*``/``p*``/``vrsn`` are UTF-16-BE.
This module only updates existing ``tbpm`` values; it never deletes tracks.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from pathlib import Path

TRACK_FIELD = b"otrk"
PATH_FIELD = b"pfil"
BPM_FIELD = b"tbpm"


@dataclass(frozen=True)
class DbTrack:
    path: str
    bpm: float | None
    offset: int
    length: int
    raw: bytes


def _decode_text(data: bytes) -> str:
    return data.decode("utf-16-be", errors="replace")


def _encode_text(value: str) -> bytes:
    return value.encode("utf-16-be")


def _iter_tlv(data: bytes) -> list[tuple[bytes, bytes, int, int]]:
    """Return (tag, payload, header_offset, total_length) records."""
    records: list[tuple[bytes, bytes, int, int]] = []
    offset = 0
    while offset + 8 <= len(data):
        tag = data[offset : offset + 4]
        (length,) = struct.unpack(">I", data[offset + 4 : offset + 8])
        start = offset + 8
        end = start + length
        if end > len(data):
            break
        records.append((tag, data[start:end], offset, 8 + length))
        offset = end
    return records


def parse_database_tracks(data: bytes) -> list[DbTrack]:
    tracks: list[DbTrack] = []
    for tag, payload, offset, total_len in _iter_tlv(data):
        if tag != TRACK_FIELD:
            continue
        path = None
        bpm: float | None = None
        for inner_tag, inner_payload, _off, _ln in _iter_tlv(payload):
            if inner_tag == PATH_FIELD:
                path = _decode_text(inner_payload)
            elif inner_tag == BPM_FIELD:
                text = _decode_text(inner_payload).strip()
                try:
                    bpm = float(text)
                except ValueError:
                    bpm = None
        if path:
            tracks.append(
                DbTrack(
                    path=path,
                    bpm=bpm,
                    offset=offset,
                    length=total_len,
                    raw=data[offset : offset + total_len],
                )
            )
    return tracks


def _replace_tbpm_in_otrk(otrk_payload: bytes, bpm: int) -> bytes:
    chunks: list[bytes] = []
    replaced = False
    bpm_bytes = _encode_text(f"{bpm:.2f}")
    for tag, payload, _off, _ln in _iter_tlv(otrk_payload):
        if tag == BPM_FIELD:
            payload = bpm_bytes
            replaced = True
        chunks.append(tag + struct.pack(">I", len(payload)) + payload)
    if not replaced:
        chunks.append(BPM_FIELD + struct.pack(">I", len(bpm_bytes)) + bpm_bytes)
    return b"".join(chunks)


def _normalize_db_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("/").lower()


def update_database_bpm(data: bytes, path_to_bpm: dict[str, int]) -> tuple[bytes, int]:
    """Return (new_bytes, n_updated). Paths compared case-insensitively, slash-normalized."""
    wanted = {_normalize_db_path(p): bpm for p, bpm in path_to_bpm.items()}
    out = io.BytesIO()
    updated = 0
    cursor = 0
    for tag, payload, offset, total_len in _iter_tlv(data):
        if offset > cursor:
            out.write(data[cursor:offset])
        if tag == TRACK_FIELD:
            track_path = None
            for inner_tag, inner_payload, _off, _ln in _iter_tlv(payload):
                if inner_tag == PATH_FIELD:
                    track_path = _decode_text(inner_payload)
                    break
            key = _normalize_db_path(track_path) if track_path else ""
            if key in wanted:
                new_payload = _replace_tbpm_in_otrk(payload, wanted[key])
                out.write(tag + struct.pack(">I", len(new_payload)) + new_payload)
                updated += 1
                cursor = offset + total_len
                continue
        out.write(data[offset : offset + total_len])
        cursor = offset + total_len
    if cursor < len(data):
        out.write(data[cursor:])
    return out.getvalue(), updated


def load_database(path: Path) -> bytes:
    return path.read_bytes()


def save_database(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def dump_minimal_database(tracks: list[tuple[str, str]]) -> bytes:
    """Test helper: ``[(relpath, bpm_text), ...]`` → database V2 bytes."""
    version = "2.0/Serato Scratch LIVE Database"
    chunks: list[bytes] = []
    v_payload = _encode_text(version)
    chunks.append(b"vrsn" + struct.pack(">I", len(v_payload)) + v_payload)
    for relpath, bpm_text in tracks:
        inner = bytearray()
        p = _encode_text(relpath)
        inner.extend(b"pfil" + struct.pack(">I", len(p)) + p)
        b = _encode_text(bpm_text)
        inner.extend(b"tbpm" + struct.pack(">I", len(b)) + b)
        chunks.append(b"otrk" + struct.pack(">I", len(inner)) + bytes(inner))
    return b"".join(chunks)
