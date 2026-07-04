"""BPM lookup backends (songbpm.com scrape by default; GetSongBPM optional)."""

from __future__ import annotations

from typing import Literal

import httpx

from mashup_pop_finder import getsongbpm, songbpm_com
from mashup_pop_finder.models import Candidate, SongMeta

BpmSource = Literal["songbpm", "getsongbpm"]

_ATTRIBUTION: dict[BpmSource, str] = {
    "songbpm": "BPM data via songbpm.com",
    "getsongbpm": "Powered by GetSongBPM — https://getsongbpm.com",
}


def attribution(source: BpmSource) -> str:
    return _ATTRIBUTION[source]


def lookup(
    title: str,
    artist: str,
    *,
    source: BpmSource = "songbpm",
    client: httpx.Client | None = None,
) -> SongMeta | None:
    if source == "getsongbpm":
        return getsongbpm.lookup(title, artist, client=client)
    return songbpm_com.lookup(title, artist, client=client)


def lookup_candidate(
    c: Candidate,
    *,
    source: BpmSource = "songbpm",
    client: httpx.Client | None = None,
) -> SongMeta | None:
    if source == "getsongbpm":
        return getsongbpm.lookup_candidate(c, client=client)
    return songbpm_com.lookup_candidate(c, client=client)
