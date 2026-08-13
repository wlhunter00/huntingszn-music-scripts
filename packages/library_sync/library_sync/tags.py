"""Audio tag reading with mutagen.

Reads ID3 tags (MP3), Vorbis comments (FLAC), and MP4 tags (M4A).
Parses BPM, key, and Camelot values including Mixed In Key conventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3
from mutagen.mp3 import MP3

from library_sync.camelot import musical_to_camelot


@dataclass
class TrackTags:
    """Parsed audio tags from a file."""

    artist: str | None = None
    title: str | None = None
    album: str | None = None
    genre: str | None = None
    duration_sec: float | None = None
    bpm: float | None = None
    key: str | None = None
    camelot_key: str | None = None


def _parse_bpm(value: str | None) -> float | None:
    """Parse BPM from string, handling various formats."""
    if not value:
        return None
    value = value.strip()
    match = re.match(r"^(\d+(?:\.\d+)?)", value)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _parse_key_and_camelot(
    key_str: str | None, comment: str | None = None
) -> tuple[str | None, str | None]:
    """Parse key string and extract camelot code.

    Mixed In Key often stores the Camelot code in TKEY or in comments.
    Returns (musical_key, camelot_key)
    """
    camelot_pattern = re.compile(r"\b(1[0-2]|[1-9])[ABab]\b")

    musical_key = None
    camelot_key = None

    if key_str:
        key_str = key_str.strip()
        match = camelot_pattern.search(key_str)
        if match:
            camelot_key = match.group(0).upper()
        else:
            converted = musical_to_camelot(key_str)
            if converted:
                camelot_key = converted
                musical_key = key_str

    if not camelot_key and comment:
        match = camelot_pattern.search(comment)
        if match:
            camelot_key = match.group(0).upper()

    return musical_key, camelot_key


def _get_id3_text(tags: ID3, key: str) -> str | None:
    """Get text value from ID3 tags."""
    frame = tags.get(key)
    if frame:
        text = frame.text[0] if hasattr(frame, "text") and frame.text else None
        return str(text) if text else None
    return None


def _get_comment(tags: ID3) -> str | None:
    """Get comment from ID3 tags (various COMM frames)."""
    for key in tags.keys():
        if key.startswith("COMM"):
            frame = tags[key]
            if hasattr(frame, "text") and frame.text:
                return str(frame.text[0])
    return None


def read_tags(path: Path) -> TrackTags:
    """Read audio tags from a file.

    Supports MP3, FLAC, AIFF, WAV, and M4A files.
    """
    tags = TrackTags()

    try:
        audio = MutagenFile(path, easy=False)
        if audio is None:
            return tags
    except Exception:
        return tags

    if isinstance(audio, MP3):
        if audio.tags:
            id3 = audio.tags
            tags.artist = _get_id3_text(id3, "TPE1")
            tags.title = _get_id3_text(id3, "TIT2")
            tags.album = _get_id3_text(id3, "TALB")
            tags.genre = _get_id3_text(id3, "TCON")

            bpm_str = _get_id3_text(id3, "TBPM")
            tags.bpm = _parse_bpm(bpm_str)

            key_str = _get_id3_text(id3, "TKEY")
            initial_key = _get_id3_text(id3, "TXXX:INITIALKEY") or _get_id3_text(
                id3, "TXXX:initialkey"
            )
            comment = _get_comment(id3)

            key_str = key_str or initial_key
            tags.key, tags.camelot_key = _parse_key_and_camelot(key_str, comment)

        if audio.info:
            tags.duration_sec = audio.info.length

    elif hasattr(audio, "tags") and audio.tags:
        audio_tags = audio.tags

        def get_tag(keys: list[str]) -> str | None:
            for k in keys:
                val = audio_tags.get(k)
                if val:
                    return str(val[0]) if isinstance(val, list) else str(val)
            return None

        tags.artist = get_tag(["artist", "ARTIST", "\xa9ART", "TPE1"])
        tags.title = get_tag(["title", "TITLE", "\xa9nam", "TIT2"])
        tags.album = get_tag(["album", "ALBUM", "\xa9alb", "TALB"])
        tags.genre = get_tag(["genre", "GENRE", "\xa9gen", "TCON"])

        bpm_str = get_tag(["bpm", "BPM", "TBPM", "tmpo"])
        tags.bpm = _parse_bpm(bpm_str)

        key_str = get_tag(["key", "KEY", "TKEY", "initialkey", "INITIALKEY"])
        comment = get_tag(["comment", "COMMENT"])
        tags.key, tags.camelot_key = _parse_key_and_camelot(key_str, comment)

        if hasattr(audio, "info") and audio.info:
            tags.duration_sec = audio.info.length

    return tags
