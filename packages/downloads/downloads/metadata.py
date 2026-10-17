"""Filename sanitization, Spotify tagging, and download history/manifest."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from downloads.spotify_api import TrackMeta

_INVALID_WIN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r"\s+")


def sanitize_filename(name: str, *, max_len: int = 180) -> str:
    cleaned = _INVALID_WIN.sub("", name)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "untitled"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned


def artist_title_filename(track: TrackMeta, *, ext: str = "mp3") -> str:
    base = sanitize_filename(f"{track.artists_joined} - {track.name}")
    ext = ext.lstrip(".")
    return f"{base}.{ext}"


def apply_spotify_tags(path: Path, track: TrackMeta) -> None:
    """Overwrite tags with Spotify metadata; embed artwork when available."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import APIC, ID3
        from mutagen.id3 import error as ID3Error
        from mutagen.mp3 import MP3
    except ImportError as exc:
        raise RuntimeError(
            "mutagen is not installed. Run: uv sync --package music-downloads"
        ) from exc

    if path.suffix.lower() != ".mp3":
        # Best-effort for non-mp3 via mutagen File
        _apply_generic_tags(path, track)
        return

    try:
        tags = EasyID3(path)
    except ID3Error:
        audio = MP3(path)
        audio.add_tags()
        audio.save()
        tags = EasyID3(path)

    tags["title"] = track.name
    tags["artist"] = track.artists_joined
    tags["album"] = track.album
    if track.track_number is not None:
        tags["tracknumber"] = str(track.track_number)
    if track.disc_number is not None:
        tags["discnumber"] = str(track.disc_number)
    if track.release_date:
        # EasyID3 date
        tags["date"] = track.release_date[:4]
    tags.save()

    if track.artwork_url:
        try:
            image = _fetch_bytes(track.artwork_url)
        except OSError:
            return
        id3 = ID3(path)
        id3.delall("APIC")
        mime = "image/jpeg"
        if track.artwork_url.lower().endswith(".png"):
            mime = "image/png"
        id3.add(
            APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=image,
            )
        )
        id3.save(v2_version=3)


def _apply_generic_tags(path: Path, track: TrackMeta) -> None:
    from mutagen import File

    audio = File(path, easy=True)
    if audio is None:
        return
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:  # noqa: BLE001
            return
    audio["title"] = track.name
    audio["artist"] = track.artists_joined
    audio["album"] = track.album
    audio.save()


def _fetch_bytes(url: str, *, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "music-downloads/sp-dl"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — artwork URLs from Spotify CDN
        return resp.read()


@dataclass
class HistoryEntry:
    spotify_id: str
    title: str
    artists: str
    status: str
    source: str | None = None
    source_url: str | None = None
    confidence: float | None = None
    output_path: str | None = None
    error: str | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class DownloadManifest:
    """JSON history beside an output directory for resume / skip-existing."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, HistoryEntry] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in data.get("entries") or []:
            try:
                entry = HistoryEntry(**item)
            except TypeError:
                continue
            self.entries[entry.spotify_id] = entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "entries": [asdict(e) for e in self.entries.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get(self, spotify_id: str) -> HistoryEntry | None:
        return self.entries.get(spotify_id)

    def is_done(self, spotify_id: str) -> bool:
        entry = self.entries.get(spotify_id)
        if not entry or entry.status != "ok":
            return False
        if entry.output_path and Path(entry.output_path).exists():
            return True
        return entry.status == "ok" and not entry.output_path

    def record(self, entry: HistoryEntry) -> None:
        self.entries[entry.spotify_id] = entry
        self.save()
