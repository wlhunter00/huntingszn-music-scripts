"""
Populated post-recon. Edits here are the ONLY place selectors live.

Until the values below are filled in from real captured HTML, the
production scraper (`songkeyfinder.py`) and API client (`getsongbpm.py`)
refuse to run. See README §Recon-first.

Workflow:
1. `python -m mashup_pop_finder recon search --title ... --artist ...`
2. `python -m mashup_pop_finder recon key --key "B minor"`
3. `python -m mashup_pop_finder recon analyze` → reads recon-output/SUMMARY.md
4. Copy the "best-guess block" from SUMMARY.md into this file.
"""

from __future__ import annotations

# --- songkeyfinder.com -------------------------------------------------------
# Populated from recon against https://songkeyfinder.com (2026-05).
SONGKEYFINDER_BASE_URL: str | None = "https://songkeyfinder.com"

SONGKEYFINDER_SEARCH_PATH: str | None = None  # not used yet
SONGKEYFINDER_KEY_LISTING_PATH: str | None = "/songs-in-key/{slug}"

SONG_PAGE_KEY_SELECTOR: str | None = None
SONG_PAGE_BPM_SELECTOR: str | None = None

LISTING_ROW_SELECTOR: str | None = "table.searchresults tr"
LISTING_TITLE_SELECTOR: str | None = "td:nth-child(2) a"
LISTING_ARTIST_SELECTOR: str | None = "td:nth-child(1) a"
LISTING_DETAIL_HREF_SELECTOR: str | None = "td:nth-child(2) a"

# --- getsongbpm.com API ------------------------------------------------------
GETSONGBPM_API_BASE: str | None = "https://api.getsongbpm.com"

GETSONGBPM_SEARCH_PATH: str | None = "/search/"
GETSONGBPM_API_KEY_PARAM: str | None = "api_key"
GETSONGBPM_LOOKUP_PARAM: str | None = "lookup"

GETSONGBPM_RESULT_LIST_PATH: str | None = "search"
GETSONGBPM_RESULT_TITLE_KEY: str | None = "title"
GETSONGBPM_RESULT_ARTIST_KEY: str | None = "name"
GETSONGBPM_RESULT_BPM_KEY: str | None = "tempo"


def require(name: str, value: str | None) -> str:
    """Raise a clear error if a selector hasn't been filled in yet."""
    if value is None or value == "":
        raise RuntimeError(
            f"{name} is not configured. Run `python -m mashup_pop_finder recon` and "
            f"fill in mashup_pop_finder/selectors.py — see README §Recon-first."
        )
    return value
