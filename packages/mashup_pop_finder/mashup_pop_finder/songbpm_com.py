"""Look up song tempo by scraping songbpm.com (no API key required)."""

from __future__ import annotations

import re

import httpx
from selectolax.parser import HTMLParser

from mashup_pop_finder.http import make_client
from mashup_pop_finder.models import Candidate, SongMeta

_BASE = "https://songbpm.com"

_TEMPO_METRICS_RE = re.compile(r"Tempo\s*\(BPM\)\s*(\d{2,3})\b", re.IGNORECASE)
_TEMPO_PROSE_RE = re.compile(r"with a tempo of (\d{2,3})\s*BPM", re.IGNORECASE)
_HEADING_BPM_RE = re.compile(r"<h1[^>]*>.*?</h1>\s*(\d{2,3})\s*BPM", re.IGNORECASE | re.DOTALL)


class SongbpmComError(RuntimeError):
    pass


def _slug(part: str) -> str:
    s = part.lower().strip()
    s = s.replace("&", "and")
    s = re.sub(r"[''`]", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _candidate_paths(artist: str, title: str) -> list[str]:
    """URL path segments to try, most likely first."""
    a = _slug(artist)
    t = _slug(title)
    paths = [f"/@{a}/{t}"]
    # Titles with leading articles sometimes drop them on songbpm.
    for prefix in ("the-", "a-"):
        if t.startswith(prefix):
            paths.append(f"/@{a}/{t[len(prefix) :]}")
    return paths


def _parse_bpm(html: str) -> float | None:
    m = _TEMPO_METRICS_RE.search(html)
    if m:
        return float(m.group(1))
    m = _TEMPO_PROSE_RE.search(html)
    if m:
        return float(m.group(1))
    m = _HEADING_BPM_RE.search(html)
    if m:
        return float(m.group(1))
    # Last resort: first h1 sibling block in parsed tree.
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    if h1 is not None:
        n = h1.next
        for _ in range(4):
            if n is None:
                break
            text = (n.text() or "").strip()
            m2 = re.match(r"^(\d{2,3})\s*BPM$", text, re.IGNORECASE)
            if m2:
                return float(m2.group(1))
            n = n.next
    return None


def _page_title_matches(html: str, title: str, artist: str) -> bool:
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    if h1 is None:
        return True
    heading = (h1.text() or "").lower()
    return _slug(title).replace("-", "") in heading.replace("-", "") or title.lower() in heading


def lookup(
    title: str,
    artist: str,
    client: httpx.Client | None = None,
) -> SongMeta | None:
    """Return BPM for (title, artist), or None if songbpm.com has no match."""
    own = client is None
    client = client or make_client()
    try:
        for path in _candidate_paths(artist, title):
            url = _BASE + path
            resp = client.get(url)
            if resp.status_code == 404:
                continue
            if resp.status_code >= 400:
                raise SongbpmComError(f"GET {url} → {resp.status_code}")
            bpm = _parse_bpm(resp.text)
            if bpm is None:
                continue
            if not _page_title_matches(resp.text, title, artist):
                continue
            return SongMeta(
                title=title,
                artist=artist,
                bpm=bpm,
                source_url=str(resp.request.url),
            )
        return None
    finally:
        if own:
            client.close()


def lookup_candidate(c: Candidate, client: httpx.Client | None = None) -> SongMeta | None:
    return lookup(c.title, c.artist, client=client)
