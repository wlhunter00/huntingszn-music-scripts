"""GetSongBPM API client.

Refuses to run until `selectors.py` is populated against a real probed
response. See README §Recon-first.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from music_script import selectors
from music_script.http import make_client
from music_script.models import Candidate, SongMeta


class GetSongBpmError(RuntimeError):
    pass


def _get_api_key() -> str:
    key = os.getenv("GETSONGBPM_API_KEY")
    if not key:
        raise GetSongBpmError(
            "GETSONGBPM_API_KEY not set. Register at https://getsongbpm.com/api, "
            "copy your key, and paste it into .env."
        )
    return key


def _dotted_get(d: Any, dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def lookup(
    title: str,
    artist: str,
    client: httpx.Client | None = None,
) -> SongMeta | None:
    """Search GetSongBPM for (title, artist) and return the first hit's
    title/artist/bpm, or None if no result.
    """
    base = selectors.require("GETSONGBPM_API_BASE", selectors.GETSONGBPM_API_BASE)
    path = selectors.require("GETSONGBPM_SEARCH_PATH", selectors.GETSONGBPM_SEARCH_PATH)
    key_param = selectors.require("GETSONGBPM_API_KEY_PARAM", selectors.GETSONGBPM_API_KEY_PARAM)
    lookup_param = selectors.require("GETSONGBPM_LOOKUP_PARAM", selectors.GETSONGBPM_LOOKUP_PARAM)
    list_path = selectors.require(
        "GETSONGBPM_RESULT_LIST_PATH", selectors.GETSONGBPM_RESULT_LIST_PATH
    )
    title_key = selectors.require(
        "GETSONGBPM_RESULT_TITLE_KEY", selectors.GETSONGBPM_RESULT_TITLE_KEY
    )
    artist_key = selectors.require(
        "GETSONGBPM_RESULT_ARTIST_KEY", selectors.GETSONGBPM_RESULT_ARTIST_KEY
    )
    bpm_key = selectors.require("GETSONGBPM_RESULT_BPM_KEY", selectors.GETSONGBPM_RESULT_BPM_KEY)

    api_key = _get_api_key()
    url = base + path
    params = {key_param: api_key, lookup_param: f"{title} {artist}".strip()}

    own = client is None
    client = client or make_client()
    try:
        resp = client.get(url, params=params)
        if resp.status_code >= 400:
            raise GetSongBpmError(f"GET {url} → {resp.status_code} {resp.text[:200]!r}")
        data = resp.json()
        results = _dotted_get(data, list_path)
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        bpm = _dotted_get(first, bpm_key)
        if bpm is None:
            return None
        try:
            bpm_f = float(bpm)
        except (TypeError, ValueError):
            return None
        return SongMeta(
            title=str(_dotted_get(first, title_key) or title),
            artist=str(_dotted_get(first, artist_key) or artist),
            bpm=bpm_f,
            source_url=str(resp.request.url),
        )
    finally:
        if own:
            client.close()


def lookup_candidate(c: Candidate, client: httpx.Client | None = None) -> SongMeta | None:
    return lookup(c.title, c.artist, client=client)
