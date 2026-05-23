"""songkeyfinder.com scraper.

Refuses to run until `selectors.py` is populated against real captured
HTML. See README §Recon-first.
"""

from __future__ import annotations

import urllib.parse

import httpx
from selectolax.parser import HTMLParser, Node

from music_script import selectors
from music_script.http import make_client
from music_script.models import Candidate, SongMeta


class SongkeyfinderError(RuntimeError):
    pass


def _client_get(client: httpx.Client, url: str) -> str:
    resp = client.get(url)
    if resp.status_code >= 400:
        raise SongkeyfinderError(f"GET {url} → {resp.status_code}")
    return resp.text


def _text_or_none(node: Node | None) -> str | None:
    if node is None:
        return None
    text = (node.text() or "").strip()
    return text or None


def resolve_base_song(title: str, artist: str, client: httpx.Client | None = None) -> SongMeta:
    """Search songkeyfinder for (title, artist) and return the first hit's
    title/artist/key (+ source URL).

    Raises if selectors aren't configured or no result found.
    """
    base = selectors.require("SONGKEYFINDER_BASE_URL", selectors.SONGKEYFINDER_BASE_URL)
    search_path = selectors.require(
        "SONGKEYFINDER_SEARCH_PATH", selectors.SONGKEYFINDER_SEARCH_PATH
    )
    row_sel = selectors.require("LISTING_ROW_SELECTOR", selectors.LISTING_ROW_SELECTOR)
    title_sel = selectors.require("LISTING_TITLE_SELECTOR", selectors.LISTING_TITLE_SELECTOR)
    artist_sel = selectors.require("LISTING_ARTIST_SELECTOR", selectors.LISTING_ARTIST_SELECTOR)
    key_sel = selectors.require("SONG_PAGE_KEY_SELECTOR", selectors.SONG_PAGE_KEY_SELECTOR)
    href_sel = selectors.LISTING_DETAIL_HREF_SELECTOR  # optional

    query = urllib.parse.quote_plus(f"{title} {artist}")
    url = base + search_path.format(query=query)

    own = client is None
    client = client or make_client()
    try:
        html = _client_get(client, url)
        tree = HTMLParser(html)
        rows = tree.css(row_sel)
        if not rows:
            raise SongkeyfinderError(f"No search results for {title!r} / {artist!r} at {url}")

        # Take the first row, drill into its detail page if href_sel is set.
        first = rows[0]
        found_title = _text_or_none(first.css_first(title_sel)) or title
        found_artist = _text_or_none(first.css_first(artist_sel)) or artist

        detail_url: str | None = None
        if href_sel:
            anchor = first.css_first(href_sel)
            if anchor is not None:
                href = (anchor.attributes or {}).get("href")
                if href:
                    detail_url = urllib.parse.urljoin(base + "/", href)

        # Fetch detail page to read the key.
        key_text: str | None = None
        if detail_url:
            detail_html = _client_get(client, detail_url)
            detail_tree = HTMLParser(detail_html)
            key_text = _text_or_none(detail_tree.css_first(key_sel))
        else:
            # Some sites surface the key on the listing row itself.
            key_text = _text_or_none(first.css_first(key_sel))

        if not key_text:
            raise SongkeyfinderError(
                f"Resolved {found_title!r} / {found_artist!r} but couldn't read key at {detail_url or url}"
            )

        return SongMeta(
            title=found_title,
            artist=found_artist,
            key=key_text,
            source_url=detail_url or url,
        )
    finally:
        if own:
            client.close()


def list_songs_in_key(key: str, limit: int, client: httpx.Client | None = None) -> list[Candidate]:
    """Return up to `limit` candidate songs from the "songs in this key"
    listing page for `key`.
    """
    base = selectors.require("SONGKEYFINDER_BASE_URL", selectors.SONGKEYFINDER_BASE_URL)
    listing_path = selectors.require(
        "SONGKEYFINDER_KEY_LISTING_PATH", selectors.SONGKEYFINDER_KEY_LISTING_PATH
    )
    row_sel = selectors.require("LISTING_ROW_SELECTOR", selectors.LISTING_ROW_SELECTOR)
    title_sel = selectors.require("LISTING_TITLE_SELECTOR", selectors.LISTING_TITLE_SELECTOR)
    artist_sel = selectors.require("LISTING_ARTIST_SELECTOR", selectors.LISTING_ARTIST_SELECTOR)
    href_sel = selectors.LISTING_DETAIL_HREF_SELECTOR

    slug = key.strip().replace(" ", "-").lower()
    url = base + listing_path.format(slug=slug)

    own = client is None
    client = client or make_client()
    try:
        html = _client_get(client, url)
        tree = HTMLParser(html)
        out: list[Candidate] = []
        for row in tree.css(row_sel):
            t = _text_or_none(row.css_first(title_sel))
            a = _text_or_none(row.css_first(artist_sel))
            if not t or not a:
                continue
            detail = None
            if href_sel:
                anchor = row.css_first(href_sel)
                if anchor is not None:
                    href = (anchor.attributes or {}).get("href")
                    if href:
                        detail = urllib.parse.urljoin(base + "/", href)
            out.append(Candidate(title=t, artist=a, detail_url=detail))
            if len(out) >= limit:
                break
        return out
    finally:
        if own:
            client.close()
