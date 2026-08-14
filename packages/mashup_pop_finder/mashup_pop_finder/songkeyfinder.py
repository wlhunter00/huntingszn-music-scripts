"""songkeyfinder.com scraper.

Refuses to run until `selectors.py` is populated against real captured
HTML. See README §Recon-first.
"""

from __future__ import annotations

import urllib.parse

import httpx
from selectolax.parser import HTMLParser, Node

from mashup_pop_finder import selectors
from mashup_pop_finder.http import make_client
from mashup_pop_finder.models import Candidate, SongMeta

SONGS_PER_PAGE = 30


class SongkeyfinderError(RuntimeError):
    pass


def pages_for_limit(limit: int) -> int:
    """Listing pages needed to collect up to `limit` songs (30 per page)."""
    return max(1, (limit + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE)


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


def _listing_url(base: str, listing_path: str, slug: str, page: int) -> str:
    url = base + listing_path.format(slug=slug)
    if page > 1:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}page={page}"
    return url


def _parse_listing_page(
    html: str,
    *,
    base: str,
    row_sel: str,
    title_sel: str,
    artist_sel: str,
    href_sel: str | None,
) -> list[Candidate]:
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
    return out


def list_songs_in_key(
    key: str,
    limit: int,
    *,
    pages: int = 1,
    client: httpx.Client | None = None,
) -> list[Candidate]:
    """Return up to `limit` candidate songs from songkeyfinder's key listing.

  Songkeyfinder paginates with ``?page=N`` (30 songs per page). Pass ``pages``
  to fetch additional listing pages before applying ``limit``.
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
    pages = max(1, pages)

    own = client is None
    client = client or make_client()
    try:
        out: list[Candidate] = []
        seen: set[tuple[str, str]] = set()
        for page_num in range(1, pages + 1):
            url = _listing_url(base, listing_path, slug, page_num)
            html = _client_get(client, url)
            batch = _parse_listing_page(
                html,
                base=base,
                row_sel=row_sel,
                title_sel=title_sel,
                artist_sel=artist_sel,
                href_sel=href_sel,
            )
            if not batch:
                break
            for cand in batch:
                dedupe_key = (cand.title.lower(), cand.artist.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                out.append(cand)
                if len(out) >= limit:
                    return out
        return out
    finally:
        if own:
            client.close()
