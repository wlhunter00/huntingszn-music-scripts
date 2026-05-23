"""Shared httpx client factory. Sends realistic browser headers so scraping
targets don't 403 the way Python's default UA would."""

from __future__ import annotations

import httpx

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def make_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=timeout,
    )
