"""Resolve Spotify track metadata to YouTube / SoundCloud download URLs."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from downloads._common import yt_dlp_cmd
from downloads.spotify_api import TrackMeta

SourceName = Literal["youtube", "soundcloud"]

_VERSION_MARKERS = (
    "remix",
    "mix",
    "edit",
    "instrumental",
    "karaoke",
    "live",
    "cover",
    "acoustic",
    "sped up",
    "slowed",
    "nightcore",
    "8d",
    "mashup",
    "bootleg",
    "rework",
    "vip",
    "radio edit",
    "extended",
)

_NOISE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceCandidate:
    source: SourceName
    url: str
    title: str
    uploader: str
    duration_s: float | None
    score: float
    reason: str


@dataclass(frozen=True)
class ResolveResult:
    track: TrackMeta
    candidate: SourceCandidate | None
    rejected: tuple[SourceCandidate, ...]
    error: str | None = None


def normalize_text(value: str) -> str:
    text = value.casefold()
    text = _NOISE_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _tokens(value: str) -> set[str]:
    return {t for t in normalize_text(value).split() if len(t) > 1}


def _marker_set(text: str) -> set[str]:
    norm = normalize_text(text)
    found: set[str] = set()
    for marker in _VERSION_MARKERS:
        if marker in norm:
            found.add(marker)
    return found


def score_candidate(
    track: TrackMeta,
    *,
    title: str,
    uploader: str,
    duration_s: float | None,
    source: SourceName,
) -> tuple[float, str]:
    """Return (score 0-100, human reason). Higher is better."""
    reasons: list[str] = []
    score = 0.0

    track_title_n = normalize_text(track.name)
    cand_title_n = normalize_text(title)
    artist_n = normalize_text(track.primary_artist)
    artists_n = normalize_text(track.artists_joined)

    title_tokens = _tokens(track.name)
    cand_tokens = _tokens(title)
    if title_tokens and title_tokens.issubset(cand_tokens):
        score += 35
        reasons.append("title tokens present")
    elif track_title_n and track_title_n in cand_title_n:
        score += 28
        reasons.append("title substring")
    elif title_tokens:
        overlap = len(title_tokens & cand_tokens) / max(len(title_tokens), 1)
        score += 20 * overlap
        reasons.append(f"title overlap {overlap:.0%}")

    if artist_n and (artist_n in cand_title_n or artist_n in normalize_text(uploader)):
        score += 25
        reasons.append("artist match")
    elif any(
        normalize_text(a) in cand_title_n or normalize_text(a) in normalize_text(uploader)
        for a in track.artists
    ):
        score += 18
        reasons.append("secondary artist match")
    elif artists_n and artists_n in cand_title_n:
        score += 15
        reasons.append("artists string in title")

    expected = track.duration_s
    if duration_s and expected > 0:
        delta = abs(duration_s - expected)
        if delta <= 3:
            score += 25
            reasons.append(f"duration ±{delta:.1f}s")
        elif delta <= 5:
            score += 18
            reasons.append(f"duration ±{delta:.1f}s")
        elif delta <= 8:
            score += 8
            reasons.append(f"duration ±{delta:.1f}s")
        else:
            score -= min(30, (delta - 8) * 2)
            reasons.append(f"duration miss ±{delta:.1f}s")
    else:
        reasons.append("no duration")

    track_markers = _marker_set(track.name)
    cand_markers = _marker_set(title)
    if track_markers == cand_markers:
        if track_markers:
            score += 10
            reasons.append("version markers match")
    else:
        extra = cand_markers - track_markers
        missing = track_markers - cand_markers
        if extra:
            score -= 12 * len(extra)
            reasons.append(f"extra markers {sorted(extra)}")
        if missing:
            score -= 10 * len(missing)
            reasons.append(f"missing markers {sorted(missing)}")

    # Prefer topic/official-ish uploaders lightly
    up_n = normalize_text(uploader)
    if "topic" in up_n or "official" in up_n or "vevo" in up_n:
        score += 5
        reasons.append("official-ish uploader")

    if source == "soundcloud":
        # Slight penalty so YouTube wins ties unless SC is clearly better
        score -= 2

    score = max(0.0, min(100.0, score))
    return score, "; ".join(reasons) if reasons else "no signals"


def _dump_search(query: str, *, playlist_items: int = 5) -> list[dict[str, Any]]:
    cmd = yt_dlp_cmd(
        "--dump-json",
        "--no-download",
        "--flat-playlist",
        "--playlist-end",
        str(playlist_items),
        query,
    )
    if cmd is None:
        return []
    # YouTube search benefits from JS runtime
    if query.startswith("ytsearch"):
        cmd.extend(
            [
                "--js-runtimes",
                "deno,node",
                "--extractor-args",
                "youtube:player_client=default",
            ]
        )
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0 and not result.stdout.strip():
        return []
    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _entry_url(entry: dict[str, Any], source: SourceName) -> str | None:
    url = entry.get("webpage_url") or entry.get("url") or entry.get("original_url")
    if url and isinstance(url, str) and url.startswith("http"):
        return url
    eid = entry.get("id")
    if not eid:
        return None
    if source == "youtube":
        return f"https://www.youtube.com/watch?v={eid}"
    if source == "soundcloud":
        # flat playlist may only have id; skip if no permalink
        return None
    return None


def _candidates_from_entries(
    track: TrackMeta,
    entries: list[dict[str, Any]],
    source: SourceName,
) -> list[SourceCandidate]:
    out: list[SourceCandidate] = []
    for entry in entries:
        url = _entry_url(entry, source)
        if not url:
            continue
        title = str(entry.get("title") or entry.get("fulltitle") or "")
        uploader = str(
            entry.get("uploader")
            or entry.get("channel")
            or entry.get("creator")
            or ""
        )
        duration = entry.get("duration")
        duration_s = float(duration) if duration is not None else None
        score, reason = score_candidate(
            track,
            title=title,
            uploader=uploader,
            duration_s=duration_s,
            source=source,
        )
        out.append(
            SourceCandidate(
                source=source,
                url=url,
                title=title,
                uploader=uploader,
                duration_s=duration_s,
                score=score,
                reason=reason,
            )
        )
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def search_youtube(track: TrackMeta, *, results: int = 5) -> list[SourceCandidate]:
    query = f"ytsearch{results}:{track.search_query}"
    return _candidates_from_entries(track, _dump_search(query, playlist_items=results), "youtube")


def search_soundcloud(track: TrackMeta, *, results: int = 5) -> list[SourceCandidate]:
    query = f"scsearch{results}:{track.search_query}"
    return _candidates_from_entries(
        track, _dump_search(query, playlist_items=results), "soundcloud"
    )


def resolve_source(
    track: TrackMeta,
    *,
    source: Literal["youtube", "soundcloud", "auto"] = "auto",
    min_score: float = 55.0,
    results: int = 5,
) -> ResolveResult:
    """Pick best external source URL for a Spotify track."""
    rejected: list[SourceCandidate] = []
    pool: list[SourceCandidate] = []

    try:
        if source in ("youtube", "auto"):
            pool.extend(search_youtube(track, results=results))
        if source in ("soundcloud", "auto"):
            # For auto, only search SC if YT best is weak
            if source == "soundcloud" or not pool or pool[0].score < min_score:
                pool.extend(search_soundcloud(track, results=results))
    except Exception as exc:  # noqa: BLE001 — surface as resolve error
        return ResolveResult(track=track, candidate=None, rejected=(), error=str(exc))

    pool.sort(key=lambda c: c.score, reverse=True)
    if not pool:
        return ResolveResult(
            track=track,
            candidate=None,
            rejected=(),
            error="No search results",
        )

    best = pool[0]
    rejected = pool[1:]
    if best.score < min_score:
        return ResolveResult(
            track=track,
            candidate=None,
            rejected=tuple(pool),
            error=f"Best match score {best.score:.1f} below threshold {min_score}",
        )
    return ResolveResult(
        track=track,
        candidate=best,
        rejected=tuple(rejected),
        error=None,
    )
