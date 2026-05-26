"""Probe GetSongBPM's API docs page and (if a key is configured) hit a
sample search to capture the JSON response shape.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from music_script.http import make_client

_DOCS_URL = "https://getsongbpm.com/api"

# Best-guess search endpoint shape based on common public-API patterns.
# This is the ONE place where a guess lives — and only for recon, never
# production. If the guess is wrong, the api-probe will 404 and the
# response body will tell you what to use.
_GUESSED_SEARCH_URL = "https://api.getsongbpm.com/search/"


def run(
    title: str | None,
    artist: str | None,
    output_dir: Path,
    api_key: str | None = None,
    console: Console | None = None,
) -> dict[str, object]:
    console = console or Console()
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = api_key or os.getenv("GETSONGBPM_API_KEY")
    summary: dict[str, object] = {"docs": None, "probe": None}
    console.print("[bold]recon api-probe[/bold]")

    with make_client() as client:
        # 1. Fetch docs page
        try:
            resp = client.get(_DOCS_URL)
            docs_path = output_dir / "getsongbpm_api_docs.html"
            docs_path.write_text(resp.text, encoding="utf-8")
            console.print(f"  docs: [green]{resp.status_code}[/green] {_DOCS_URL}  → {docs_path}")
            summary["docs"] = {"status": resp.status_code, "saved_to": str(docs_path)}
        except httpx.HTTPError as exc:
            console.print(f"  docs: [red]ERROR[/red] {exc!r}")
            summary["docs"] = {"error": repr(exc)}

        # 2. If we have a key and a title, hit the guessed endpoint.
        if api_key and title:
            lookup = f"{title} {artist}".strip() if artist else title
            params: dict[str, str] = {"api_key": api_key, "lookup": lookup, "type": "both"}
            try:
                resp = client.get(_GUESSED_SEARCH_URL, params=params)
                probe_path = output_dir / "getsongbpm_search_probe.json"
                # Try to pretty-print JSON; fall back to raw bytes.
                body: Any
                try:
                    body = resp.json()
                    probe_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
                except Exception:
                    probe_path = output_dir / "getsongbpm_search_probe.raw"
                    probe_path.write_bytes(resp.content)
                console.print(
                    f"  probe: [green]{resp.status_code}[/green] "
                    f"{_GUESSED_SEARCH_URL}?lookup={lookup!r}  → {probe_path}"
                )
                summary["probe"] = {
                    "status": resp.status_code,
                    "url": str(resp.request.url),
                    "saved_to": str(probe_path),
                }
            except httpx.HTTPError as exc:
                console.print(f"  probe: [red]ERROR[/red] {exc!r}")
                summary["probe"] = {"error": repr(exc)}
        elif not api_key:
            console.print(
                "  probe: [yellow]skipped[/yellow] "
                "(no GETSONGBPM_API_KEY in .env — get one at https://getsongbpm.com/api)"
            )
        else:
            console.print("  probe: [yellow]skipped[/yellow] (no --title given)")

    return summary
