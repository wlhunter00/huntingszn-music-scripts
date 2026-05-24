"""
Populated post-recon. Edits here are the ONLY place selectors live.

Until the values below are filled in from real captured HTML, the
production scraper (`songkeyfinder.py`) and API client (`getsongbpm.py`)
refuse to run. See README §Recon-first.

Workflow:
1. `python -m music_script recon search --title ... --artist ...`
2. `python -m music_script recon key --key "B minor"`
3. `python -m music_script recon analyze` → reads recon-output/SUMMARY.md
4. Copy the "best-guess block" from SUMMARY.md into this file.
"""

from __future__ import annotations

# --- songkeyfinder.com -------------------------------------------------------
# Base URL (no trailing slash). e.g. "https://songkeyfinder.com"
SONGKEYFINDER_BASE_URL: str | None = None

# Path templates with {placeholders}.
# e.g. "/search?q={query}", "/key/{slug}"
SONGKEYFINDER_SEARCH_PATH: str | None = None
SONGKEYFINDER_KEY_LISTING_PATH: str | None = None

# CSS selectors on a song detail page.
# e.g. ".song-key", "[data-bpm]"
SONG_PAGE_KEY_SELECTOR: str | None = None
SONG_PAGE_BPM_SELECTOR: str | None = None

# CSS selectors on a "songs in this key" listing page.
# LISTING_ROW_SELECTOR matches each repeating song row/card.
# TITLE/ARTIST are scoped within each row.
LISTING_ROW_SELECTOR: str | None = None
LISTING_TITLE_SELECTOR: str | None = None
LISTING_ARTIST_SELECTOR: str | None = None
LISTING_DETAIL_HREF_SELECTOR: str | None = None  # optional; "a" if rows are anchored

# --- getsongbpm.com API ------------------------------------------------------
# Base URL for the API (no trailing slash). e.g. "https://api.getsongbpm.com"
GETSONGBPM_API_BASE: str | None = None

# Search endpoint path + query-param names.
# e.g. "/search/", with params {"type": "both", "lookup": "<title> <artist>", "api_key": "<key>"}
GETSONGBPM_SEARCH_PATH: str | None = None
GETSONGBPM_API_KEY_PARAM: str | None = None  # e.g. "api_key"
GETSONGBPM_LOOKUP_PARAM: str | None = None  # e.g. "lookup"

# JSON paths (dot-notation) inside the search response.
# e.g. "search.0.tempo", "search.0.title", "search.0.artist.name"
GETSONGBPM_RESULT_LIST_PATH: str | None = None  # e.g. "search"
GETSONGBPM_RESULT_TITLE_KEY: str | None = None  # e.g. "title" (within each result)
GETSONGBPM_RESULT_ARTIST_KEY: str | None = None  # e.g. "artist.name"
GETSONGBPM_RESULT_BPM_KEY: str | None = None  # e.g. "tempo"


def require(name: str, value: str | None) -> str:
    """Raise a clear error if a selector hasn't been filled in yet."""
    if value is None or value == "":
        raise RuntimeError(
            f"{name} is not configured. Run `python -m music_script recon` and "
            f"fill in music_script/selectors.py — see README §Recon-first."
        )
    return value
