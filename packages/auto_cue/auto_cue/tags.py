"""Full Serato Markers2 parser/encoder for MP3 and FLAC.

Handles reading and writing hot cues, loops, track color, and BPM lock.
Reuses serato_bpm_cleanup parsers for BeatGrid and Autotags.
"""

from __future__ import annotations

import base64
import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from mutagen.flac import FLAC
from mutagen.id3 import GEOB, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4
from serato_bpm_cleanup.backup import backup_file
from serato_bpm_cleanup.beatgrid import BeatGrid, dump_beatgrid, parse_beatgrid

MARKERS2_GEOB = "Serato Markers2"
MARKERS_V1_GEOB = "Serato Markers_"
BEATGRID_GEOB = "Serato BeatGrid"
AUTOTAGS_GEOB = "Serato Autotags"

MARKERS2_VERSION = (0x01, 0x01)

SERATO_DEFAULT_COLORS = {
    0: (0xCC, 0x00, 0x00),  # A - Red
    1: (0xCC, 0x88, 0x00),  # B - Orange
    2: (0x00, 0x00, 0xCC),  # C - Blue
    3: (0xCC, 0xCC, 0x00),  # D - Yellow
    4: (0x00, 0xCC, 0x00),  # E - Green
    5: (0xCC, 0x00, 0xCC),  # F - Magenta
    6: (0x00, 0xCC, 0xCC),  # G - Cyan
    7: (0x88, 0x00, 0xCC),  # H - Purple
}


@dataclass
class CuePoint:
    """A Serato hot cue."""
    index: int  # 0-7 for slots A-H
    position_ms: int
    color: tuple[int, int, int] = (0xCC, 0x00, 0x00)
    name: str = ""

    @property
    def color_hex(self) -> str:
        return f"{self.color[0]:02X}{self.color[1]:02X}{self.color[2]:02X}"


@dataclass
class Loop:
    """A Serato saved loop."""
    index: int
    start_ms: int
    end_ms: int
    color: tuple[int, int, int] = (0x27, 0xAA, 0xE1)
    locked: bool = False
    name: str = ""


@dataclass
class Markers2Data:
    """Complete Serato Markers2 payload data."""
    cues: list[CuePoint] = field(default_factory=list)
    loops: list[Loop] = field(default_factory=list)
    track_color: tuple[int, int, int] | None = None
    bpm_lock: bool = False
    flip_entries: list[bytes] = field(default_factory=list)
    unknown_entries: list[tuple[str, bytes]] = field(default_factory=list)

    def get_cue(self, index: int) -> CuePoint | None:
        for cue in self.cues:
            if cue.index == index:
                return cue
        return None

    def has_human_cues(self) -> bool:
        """Check if any cues exist that are not MIK Energy cues."""
        from library_tools.mik_clear_cues import is_mik_cue_name
        for cue in self.cues:
            if not is_mik_cue_name(cue.name):
                return True
        return False

    def all_mik_cues(self) -> bool:
        """Check if all cues are MIK Energy cues."""
        from library_tools.mik_clear_cues import is_mik_cue_name
        if not self.cues:
            return False
        return all(is_mik_cue_name(cue.name) for cue in self.cues)


def _b64decode_serato(blob: bytes) -> bytes:
    """Decode Serato's slightly-invalid base64 (newlines; missing padding)."""
    cleaned = blob.replace(b"\n", b"").replace(b"\r", b"")
    if len(cleaned) % 4 == 1:
        cleaned += b"A"
    cleaned += b"=" * ((4 - len(cleaned) % 4) % 4)
    return base64.b64decode(cleaned)


def _b64encode_serato(data: bytes) -> bytes:
    """Encode to Serato's base64 format (72-char wrapped, no padding)."""
    b64 = base64.b64encode(data).rstrip(b"=")
    return b"\n".join(b64[i:i+72] for i in range(0, len(b64), 72))


def parse_markers2(data: bytes) -> Markers2Data:
    """Parse a complete Serato Markers2 GEOB payload."""
    result = Markers2Data()

    if len(data) < 2:
        return result

    version = tuple(data[:2])
    if version != MARKERS2_VERSION:
        raise ValueError(f"unsupported Serato Markers2 version: {version}")

    try:
        nul = data.index(b"\x00", 2)
        b64 = data[2:nul]
    except ValueError:
        b64 = data[2:]

    payload = _b64decode_serato(b64)
    if len(payload) < 2 or tuple(payload[:2]) != MARKERS2_VERSION:
        raise ValueError("invalid Markers2 inner payload")

    fp = io.BytesIO(payload[2:])

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
        entry_data = fp.read(entry_len)
        entry_name = name_bytes.decode("ascii", errors="replace")

        if entry_name == "CUE":
            cue = _parse_cue_entry(entry_data)
            if cue:
                result.cues.append(cue)
        elif entry_name == "LOOP":
            loop = _parse_loop_entry(entry_data)
            if loop:
                result.loops.append(loop)
        elif entry_name == "COLOR":
            if len(entry_data) >= 4:
                result.track_color = (entry_data[1], entry_data[2], entry_data[3])
        elif entry_name == "BPMLOCK":
            if len(entry_data) >= 1:
                result.bpm_lock = entry_data[0] != 0
        elif entry_name == "FLIP":
            result.flip_entries.append(entry_data)
        else:
            result.unknown_entries.append((entry_name, entry_data))

    result.cues.sort(key=lambda c: c.index)
    result.loops.sort(key=lambda lp: lp.index)
    return result


def _parse_cue_entry(data: bytes) -> CuePoint | None:
    """Parse a CUE entry body."""
    if len(data) < 13:
        return None

    index = data[1]
    position_ms = struct.unpack(">I", data[2:6])[0]
    r, g, b = data[7], data[8], data[9]

    name_start = 12
    try:
        name_end = data.index(b"\x00", name_start)
        name = data[name_start:name_end].decode("utf-8", errors="replace")
    except ValueError:
        name = ""

    return CuePoint(index=index, position_ms=position_ms, color=(r, g, b), name=name)


def _parse_loop_entry(data: bytes) -> Loop | None:
    """Parse a LOOP entry body."""
    if len(data) < 18:
        return None

    index = data[1]
    start_ms = struct.unpack(">I", data[2:6])[0]
    end_ms = struct.unpack(">I", data[6:10])[0]
    locked = data[17] != 0

    name_start = 18
    try:
        name_end = data.index(b"\x00", name_start)
        name = data[name_start:name_end].decode("utf-8", errors="replace")
    except ValueError:
        name = ""

    return Loop(index=index, start_ms=start_ms, end_ms=end_ms, locked=locked, name=name)


def encode_markers2(markers: Markers2Data) -> bytes:
    """Encode Markers2Data to a GEOB payload."""
    inner = bytearray(struct.pack("BB", *MARKERS2_VERSION))

    if markers.track_color is not None:
        r, g, b = markers.track_color
        entry = struct.pack(">cBBB", b"\x00", r, g, b)
        inner.extend(b"COLOR\x00")
        inner.extend(struct.pack(">I", len(entry)))
        inner.extend(entry)

    if markers.bpm_lock:
        inner.extend(b"BPMLOCK\x00")
        inner.extend(struct.pack(">I", 1))
        inner.extend(b"\x01")

    for cue in sorted(markers.cues, key=lambda c: c.index):
        entry = _encode_cue_entry(cue)
        inner.extend(b"CUE\x00")
        inner.extend(struct.pack(">I", len(entry)))
        inner.extend(entry)

    for loop in sorted(markers.loops, key=lambda lp: lp.index):
        entry = _encode_loop_entry(loop)
        inner.extend(b"LOOP\x00")
        inner.extend(struct.pack(">I", len(entry)))
        inner.extend(entry)

    for flip_data in markers.flip_entries:
        inner.extend(b"FLIP\x00")
        inner.extend(struct.pack(">I", len(flip_data)))
        inner.extend(flip_data)

    for name, data in markers.unknown_entries:
        inner.extend(name.encode("ascii") + b"\x00")
        inner.extend(struct.pack(">I", len(data)))
        inner.extend(data)

    inner.append(0)

    b64 = _b64encode_serato(bytes(inner))
    out = struct.pack("BB", *MARKERS2_VERSION) + b64

    if len(out) < 470:
        out += b"\x00" * (470 - len(out))

    return out


def _encode_cue_entry(cue: CuePoint) -> bytes:
    """Encode a CuePoint to entry bytes."""
    r, g, b = cue.color
    header = struct.pack(
        ">cBIcBBB2s",
        b"\x00",
        cue.index,
        cue.position_ms,
        b"\x00",
        r, g, b,
        b"\x00\x00",
    )
    return header + cue.name.encode("utf-8") + b"\x00"


def _encode_loop_entry(loop: Loop) -> bytes:
    """Encode a Loop to entry bytes."""
    header = struct.pack(
        ">cBII4s4sB?",
        b"\x00",
        loop.index,
        loop.start_ms,
        loop.end_ms,
        b"\xff\xff\xff\xff",
        b"\x00\x27\xaa\xe1",
        0,
        loop.locked,
    )
    return header + loop.name.encode("utf-8") + b"\x00"


@dataclass
class TrackTags:
    """All Serato tags from a track."""
    path: Path
    markers2: Markers2Data | None = None
    beatgrid: BeatGrid | None = None
    markers2_raw: bytes | None = None
    markers_v1_raw: bytes | None = None
    beatgrid_raw: bytes | None = None
    format: Literal["mp3", "flac", "m4a", "unknown"] = "unknown"
    error: str | None = None

    @property
    def has_grid(self) -> bool:
        return self.beatgrid is not None

    @property
    def bpm(self) -> float | None:
        if self.beatgrid:
            return self.beatgrid.bpm
        return None

    @property
    def first_beat_s(self) -> float | None:
        if self.beatgrid:
            return self.beatgrid.first_beat_s
        return None


def read_track_tags(path: Path) -> TrackTags:
    """Read all Serato tags from a track."""
    result = TrackTags(path=path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".mp3":
            result.format = "mp3"
            _read_mp3_tags(path, result)
        elif suffix == ".flac":
            result.format = "flac"
            _read_flac_tags(path, result)
        elif suffix in (".m4a", ".aac"):
            result.format = "m4a"
            _read_m4a_tags(path, result)
        else:
            result.format = "unknown"
            result.error = f"unsupported format: {suffix}"
    except Exception as e:
        result.error = str(e)

    return result


def _read_mp3_tags(path: Path, result: TrackTags) -> None:
    """Read Serato tags from MP3."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return

    geobs: dict[str, bytes] = {}
    for frame in tags.getall("GEOB"):
        desc = getattr(frame, "desc", None) or ""
        data = getattr(frame, "data", None)
        if desc and data is not None:
            geobs[desc] = bytes(data)

    if MARKERS2_GEOB in geobs:
        result.markers2_raw = geobs[MARKERS2_GEOB]
        try:
            result.markers2 = parse_markers2(result.markers2_raw)
        except ValueError as e:
            result.error = f"markers2 parse error: {e}"

    if MARKERS_V1_GEOB in geobs:
        result.markers_v1_raw = geobs[MARKERS_V1_GEOB]

    if BEATGRID_GEOB in geobs:
        result.beatgrid_raw = geobs[BEATGRID_GEOB]
        try:
            result.beatgrid = parse_beatgrid(result.beatgrid_raw)
        except ValueError as e:
            result.error = f"beatgrid parse error: {e}"


def _read_flac_tags(path: Path, result: TrackTags) -> None:
    """Read Serato tags from FLAC via Vorbis comments."""
    audio = FLAC(path)

    markers2_key = "SERATO_MARKERS_V2"
    if markers2_key in audio:
        raw_b64 = audio[markers2_key][0]
        try:
            decoded = base64.b64decode(raw_b64)
            header = b"application/octet-stream\x00\x00Serato Markers2\x00"
            if decoded.startswith(header):
                result.markers2_raw = decoded[len(header):]
                result.markers2 = parse_markers2(result.markers2_raw)
        except Exception as e:
            result.error = f"flac markers2 error: {e}"

    beatgrid_key = "SERATO_BEATGRID"
    if beatgrid_key in audio:
        raw_b64 = audio[beatgrid_key][0]
        try:
            decoded = base64.b64decode(raw_b64)
            header = b"application/octet-stream\x00\x00Serato BeatGrid\x00"
            if decoded.startswith(header):
                result.beatgrid_raw = decoded[len(header):]
                result.beatgrid = parse_beatgrid(result.beatgrid_raw)
        except Exception as e:
            result.error = f"flac beatgrid error: {e}"


def _read_m4a_tags(path: Path, result: TrackTags) -> None:
    """Read Serato tags from M4A (read-only in v1)."""
    try:
        audio = MP4(path)
    except Exception as e:
        result.error = f"m4a read error: {e}"
        return

    markers2_key = "----:com.serato.dj:markersv2"
    if markers2_key in audio.tags:
        try:
            raw = bytes(audio.tags[markers2_key][0])
            header = b"application/octet-stream\x00\x00Serato Markers2\x00"
            if raw.startswith(header):
                result.markers2_raw = raw[len(header):]
                result.markers2 = parse_markers2(result.markers2_raw)
        except Exception as e:
            result.error = f"m4a markers2 error: {e}"


def write_track_markers2(
    path: Path,
    markers: Markers2Data,
    *,
    backup_root: Path | None = None,
    relative: Path | None = None,
    delete_v1: bool = True,
) -> list[str]:
    """Write Markers2 to a track. Returns list of written tag names."""
    suffix = path.suffix.lower()

    if suffix == ".mp3":
        return _write_mp3_markers2(
            path, markers, backup_root=backup_root, relative=relative, delete_v1=delete_v1
        )
    elif suffix == ".flac":
        return _write_flac_markers2(path, markers, backup_root=backup_root, relative=relative)
    else:
        raise ValueError(f"cannot write Serato Markers2 to {suffix}")


def _write_mp3_markers2(
    path: Path,
    markers: Markers2Data,
    *,
    backup_root: Path | None = None,
    relative: Path | None = None,
    delete_v1: bool = True,
) -> list[str]:
    """Write Markers2 to MP3."""
    if backup_root:
        backup_file(path, backup_root, relative=relative)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    payload = encode_markers2(markers)

    kept_geobs = []
    for frame in tags.getall("GEOB"):
        desc = frame.desc or ""
        if desc == MARKERS2_GEOB:
            continue
        if delete_v1 and desc == MARKERS_V1_GEOB:
            continue
        kept_geobs.append(frame)

    tags.delall("GEOB")
    for frame in kept_geobs:
        tags.add(frame)

    tags.add(GEOB(
        encoding=0,
        mime="application/octet-stream",
        desc=MARKERS2_GEOB,
        data=payload,
    ))

    tags.save(path, v1=0)

    written = [MARKERS2_GEOB]
    if delete_v1:
        written.append(f"deleted {MARKERS_V1_GEOB}")
    return written


def _write_flac_markers2(
    path: Path,
    markers: Markers2Data,
    *,
    backup_root: Path | None = None,
    relative: Path | None = None,
) -> list[str]:
    """Write Markers2 to FLAC via Vorbis comment."""
    if backup_root:
        backup_file(path, backup_root, relative=relative)

    audio = FLAC(path)

    payload = encode_markers2(markers)
    header = b"application/octet-stream\x00\x00Serato Markers2\x00"
    full_payload = header + payload

    b64 = base64.b64encode(full_payload).decode("ascii")

    audio["SERATO_MARKERS_V2"] = b64
    audio.save()

    return ["SERATO_MARKERS_V2"]


def write_track_beatgrid(
    path: Path,
    beatgrid: BeatGrid,
    *,
    backup_root: Path | None = None,
) -> list[str]:
    """Write BeatGrid to a track."""
    suffix = path.suffix.lower()

    if suffix == ".mp3":
        return _write_mp3_beatgrid(path, beatgrid, backup_root=backup_root)
    elif suffix == ".flac":
        return _write_flac_beatgrid(path, beatgrid, backup_root=backup_root)
    else:
        raise ValueError(f"cannot write Serato BeatGrid to {suffix}")


def _write_mp3_beatgrid(
    path: Path,
    beatgrid: BeatGrid,
    *,
    backup_root: Path | None = None,
) -> list[str]:
    """Write BeatGrid to MP3."""
    if backup_root:
        backup_file(path, backup_root)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    payload = dump_beatgrid(beatgrid)

    kept_geobs = [f for f in tags.getall("GEOB") if (f.desc or "") != BEATGRID_GEOB]
    tags.delall("GEOB")
    for frame in kept_geobs:
        tags.add(frame)

    tags.add(GEOB(
        encoding=0,
        mime="application/octet-stream",
        desc=BEATGRID_GEOB,
        data=payload,
    ))

    tags.save(path, v1=0)
    return [BEATGRID_GEOB]


def _write_flac_beatgrid(
    path: Path,
    beatgrid: BeatGrid,
    *,
    backup_root: Path | None = None,
) -> list[str]:
    """Write BeatGrid to FLAC via Vorbis comment."""
    if backup_root:
        backup_file(path, backup_root)

    audio = FLAC(path)

    payload = dump_beatgrid(beatgrid)
    header = b"application/octet-stream\x00\x00Serato BeatGrid\x00"
    full_payload = header + payload

    b64 = base64.b64encode(full_payload).decode("ascii")

    audio["SERATO_BEATGRID"] = b64
    audio.save()

    return ["SERATO_BEATGRID"]


def cues_to_beats(
    markers: Markers2Data,
    beatgrid: BeatGrid,
) -> dict[int, float]:
    """Convert cue positions from ms to beat numbers."""
    if not beatgrid.first_beat_s or not beatgrid.bpm:
        return {}

    first_beat_s = beatgrid.first_beat_s
    bpm = beatgrid.bpm
    beat_duration_ms = 60000.0 / bpm

    result = {}
    for cue in markers.cues:
        beat = (cue.position_ms - first_beat_s * 1000) / beat_duration_ms
        result[cue.index] = beat

    return result


def beats_to_ms(beat: float, beatgrid: BeatGrid) -> int:
    """Convert beat number to milliseconds position."""
    if not beatgrid.first_beat_s or not beatgrid.bpm:
        raise ValueError("beatgrid missing first_beat_s or bpm")

    beat_duration_ms = 60000.0 / beatgrid.bpm
    return round(beatgrid.first_beat_s * 1000 + beat * beat_duration_ms)


def create_cues_from_beats(
    cue_beats: dict[int, int],
    beatgrid: BeatGrid,
) -> list[CuePoint]:
    """Create CuePoint list from beat positions using default Serato colors."""
    cues = []
    for index, beat in cue_beats.items():
        if 0 <= index <= 7:
            position_ms = beats_to_ms(beat, beatgrid)
            color = SERATO_DEFAULT_COLORS.get(index, (0xCC, 0x00, 0x00))
            cues.append(CuePoint(index=index, position_ms=position_ms, color=color, name=""))
    return cues
