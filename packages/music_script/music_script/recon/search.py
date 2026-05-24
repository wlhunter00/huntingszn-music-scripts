"""Probe songkeyfinder.com with candidate search-URL shapes.

Saves every 200-OK response body to disk, prints a short report.
Does NOT parse — that's `analyze.py`'s job."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

import httpx
from rich.console import Console

from music_script.http import make_client

_BASE = "https://songkeyfinder.com"

# Candidate URL shapes. We try each; whichever returns 200 gets saved.
# This list is intentionally broad — recon is where we figure out the right one.
_CANDIDATE_PATHS: tuple[str, ...] = (
    "/search?q={q}",
    "/search/?q={q}",
    "/?q={q}",
    "/?s={q}",
    "/?search={q}",
    "/songs?q={q}",
    "/find?q={q}",
    "/{q}",
)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"\s+", "-", s)


def run(
    title: str, artist: str, output_dir: Path, console: Console | None = None
) -> dict[str, object]:
    console = console or Console()
    output_dir.mkdir(parents=True, exist_ok=True)
    query = f"{title} {artist}".strip()
    encoded = urllib.parse.quote_plus(query)
    summary: dict[str, object] = {
        "query": query,
        "tried": [],
        "saved": [],
    }
    console.print(f"[bold]recon search[/bold]  query=[cyan]{query}[/cyan]")
    with make_client() as client:
        for tpl in _CANDIDATE_PATHS:
            path = tpl.format(q=encoded)
            url = _BASE + path
            row: dict[str, object] = {"url": url, "status": None, "saved_to": None, "error": None}
            try:
                resp = client.get(url)
                row["status"] = resp.status_code
                if resp.status_code == 200 and resp.text:
                    fname = _safe_filename(
                        f"search__{_slug(title)}__{_slug(artist)}__{_slug(tpl)}.html"
                    )
                    out = output_dir / fname
                    out.write_text(resp.text, encoding="utf-8")
                    row["saved_to"] = str(out)
                    summary["saved"].append(str(out))  # type: ignore[attr-defined]
                    console.print(f"  [green]200[/green] {url}  → {out}")
                else:
                    console.print(f"  [yellow]{resp.status_code}[/yellow] {url}")
            except httpx.HTTPError as exc:
                row["error"] = repr(exc)
                console.print(f"  [red]ERROR[/red] {url}  {exc!r}")
            summary["tried"].append(row)  # type: ignore[attr-defined]
    return summary


def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:200]
