"""Probe songkeyfinder.com for "songs in this key" listing pages."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

import httpx
from rich.console import Console

from mashup_pop_finder.http import make_client

_BASE = "https://songkeyfinder.com"


# Candidate slug shapes for a key like "B minor":
#   "b-minor", "B-minor", "B_minor", "B+minor", "B%20minor", "Bmin", "Bmaj"
def _key_slugs(key: str) -> list[str]:
    k = key.strip()
    quality = "minor" if "min" in k.lower() else ("major" if "maj" in k.lower() else "")
    note = re.split(r"\s+", k, maxsplit=1)[0]
    note_low = note.lower()
    candidates: list[str] = []
    if quality:
        for n in {note, note_low}:
            candidates += [
                f"{n}-{quality}",
                f"{n.lower()}-{quality}",
                f"{n}_{quality}",
                f"{n}+{quality}",
                f"{n}{quality[:3]}",
                urllib.parse.quote(f"{n} {quality}"),
            ]
    candidates += [k, urllib.parse.quote(k), k.replace(" ", "-"), k.replace(" ", "+")]
    # de-dup, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in candidates:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


_CANDIDATE_PATHS: tuple[str, ...] = (
    "/key/{slug}",
    "/keys/{slug}",
    "/songs-in-key/{slug}",
    "/in-key/{slug}",
    "/k/{slug}",
    "/?key={slug}",
)


def run(key: str, output_dir: Path, console: Console | None = None) -> dict[str, object]:
    console = console or Console()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {"key": key, "tried": [], "saved": []}
    console.print(f"[bold]recon key[/bold]  key=[cyan]{key}[/cyan]")
    with make_client() as client:
        for slug in _key_slugs(key):
            for tpl in _CANDIDATE_PATHS:
                path = tpl.format(slug=slug)
                url = _BASE + path
                row: dict[str, object] = {
                    "url": url,
                    "status": None,
                    "saved_to": None,
                    "error": None,
                }
                try:
                    resp = client.get(url)
                    row["status"] = resp.status_code
                    if resp.status_code == 200 and resp.text:
                        fname = _safe_filename(f"key__{slug}__{_slug_path(tpl)}.html")
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


def _slug_path(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:200]
