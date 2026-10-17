"""Spotify Web API helpers: URL parsing, auth, pagination, normalized tracks."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

SpotifyKind = Literal["track", "album", "playlist"]

_SPOTIFY_ID_RE = re.compile(r"^[0-9A-Za-z]{22}$")
_URI_RE = re.compile(
    r"^spotify:(track|album|playlist):([0-9A-Za-z]{22})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpotifyRef:
    kind: SpotifyKind
    id: str
    raw: str


@dataclass(frozen=True)
class TrackMeta:
    id: str
    uri: str
    name: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int
    explicit: bool
    track_number: int | None
    disc_number: int | None
    release_date: str | None
    artwork_url: str | None
    isrc: str | None = None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else "Unknown Artist"

    @property
    def artists_joined(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def search_query(self) -> str:
        return f"{self.primary_artist} {self.name}".strip()


def parse_spotify_ref(value: str) -> SpotifyRef:
    """Parse open.spotify.com URLs, spotify: URIs, or bare 22-char track IDs."""
    raw = value.strip()
    if not raw:
        raise ValueError("Empty Spotify reference")

    uri_match = _URI_RE.match(raw)
    if uri_match:
        kind = uri_match.group(1).lower()  # type: ignore[assignment]
        return SpotifyRef(kind=kind, id=uri_match.group(2), raw=raw)

    if _SPOTIFY_ID_RE.match(raw):
        return SpotifyRef(kind="track", id=raw, raw=raw)

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in {"open.spotify.com", "play.spotify.com", "spotify.link"}:
        # Allow share links that redirect; still require /track|album|playlist/
        if "spotify.com" not in host and host not in {"", "spotify.link"}:
            raise ValueError(f"Not a Spotify URL/URI: {value}")

    path = parsed.path.strip("/")
    # drop locale prefixes like /intl-en/
    parts = [p for p in path.split("/") if p and not p.startswith("intl-")]
    if len(parts) >= 2 and parts[0] in {"track", "album", "playlist"}:
        kind = parts[0]  # type: ignore[assignment]
        sid = parts[1].split("?")[0]
        if not _SPOTIFY_ID_RE.match(sid):
            raise ValueError(f"Invalid Spotify id in URL: {value}")
        return SpotifyRef(kind=kind, id=sid, raw=raw)

    # spotify.link short URLs need expansion; reject with clear error
    if host == "spotify.link":
        raise ValueError(
            "spotify.link short URLs are not supported; paste the full open.spotify.com URL"
        )

    raise ValueError(f"Could not parse Spotify reference: {value}")


def _require_credentials() -> tuple[str, str]:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required. "
            "Copy .env.example to .env and fill Spotify Developer Dashboard credentials."
        )
    return client_id, client_secret


def build_spotify_client(*, market: str | None = None):
    """Client-credentials Spotify client for public catalog metadata."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError as exc:
        raise RuntimeError(
            "spotipy is not installed. Run: uv sync --package music-downloads"
        ) from exc

    client_id, client_secret = _require_credentials()
    auth = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    return spotipy.Spotify(auth_manager=auth, requests_timeout=30), market


def _artwork_from_images(images: list[dict[str, Any]] | None) -> str | None:
    if not images:
        return None
    # Prefer largest
    best = max(images, key=lambda im: int(im.get("width") or 0))
    return best.get("url")


def track_from_api(obj: dict[str, Any]) -> TrackMeta:
    artists = tuple(
        a.get("name") or "Unknown Artist" for a in (obj.get("artists") or []) if a
    )
    album = obj.get("album") or {}
    external = obj.get("external_ids") or {}
    return TrackMeta(
        id=obj["id"],
        uri=obj.get("uri") or f"spotify:track:{obj['id']}",
        name=obj.get("name") or "Unknown Title",
        artists=artists or ("Unknown Artist",),
        album=(album.get("name") if isinstance(album, dict) else None) or "Unknown Album",
        duration_ms=int(obj.get("duration_ms") or 0),
        explicit=bool(obj.get("explicit")),
        track_number=obj.get("track_number"),
        disc_number=obj.get("disc_number"),
        release_date=album.get("release_date") if isinstance(album, dict) else None,
        artwork_url=_artwork_from_images(
            album.get("images") if isinstance(album, dict) else None
        ),
        isrc=external.get("isrc"),
    )


def _paginate(
    sp,
    first_page: dict[str, Any],
    *,
    items_key: str = "items",
) -> Iterator[dict[str, Any]]:
    page = first_page
    while page:
        for item in page.get(items_key) or []:
            if item:
                yield item
        next_url = page.get("next")
        if not next_url:
            break
        page = sp.next(page)


def fetch_tracks_for_ref(
    ref: SpotifyRef,
    *,
    market: str | None = None,
    limit: int | None = None,
) -> list[TrackMeta]:
    """Expand a Spotify track/album/playlist into normalized TrackMeta list."""
    sp, default_market = build_spotify_client(market=market)
    mkt = market or default_market
    kwargs: dict[str, Any] = {}
    if mkt:
        kwargs["market"] = mkt

    tracks: list[TrackMeta] = []

    if ref.kind == "track":
        obj = sp.track(ref.id, **kwargs)
        tracks.append(track_from_api(obj))
        return tracks

    if ref.kind == "album":
        album = sp.album(ref.id, **kwargs)
        album_name = album.get("name") or "Unknown Album"
        release = album.get("release_date")
        page = sp.album_tracks(ref.id, limit=50, **kwargs)
        for item in _paginate(sp, page):
            # album_tracks items lack full album nest; enrich
            enriched = dict(item)
            enriched["album"] = {
                "name": album_name,
                "release_date": release,
                "images": album.get("images") or [],
            }
            tracks.append(track_from_api(enriched))
            if limit is not None and len(tracks) >= limit:
                return tracks[:limit]
        return tracks

    # playlist
    page = sp.playlist_items(
        ref.id,
        limit=100,
        additional_types=("track",),
        **kwargs,
    )
    for entry in _paginate(sp, page):
        track = entry.get("track")
        if not track or track.get("is_local") or not track.get("id"):
            continue
        # Ensure album images present when API returns them
        tracks.append(track_from_api(track))
        if limit is not None and len(tracks) >= limit:
            return tracks[:limit]
    return tracks


def expand_inputs(
    values: list[str],
    *,
    market: str | None = None,
    limit: int | None = None,
) -> list[TrackMeta]:
    """Parse many Spotify refs and expand, de-duplicating by track id (order preserved)."""
    seen: set[str] = set()
    out: list[TrackMeta] = []
    remaining = limit
    for value in values:
        ref = parse_spotify_ref(value)
        batch_limit = remaining
        batch = fetch_tracks_for_ref(ref, market=market, limit=batch_limit)
        for t in batch:
            if t.id in seen:
                continue
            seen.add(t.id)
            out.append(t)
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    return out
    return out
