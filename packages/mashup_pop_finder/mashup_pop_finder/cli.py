"""Click CLI: `mashup-pop-finder recon ...` + `mashup-pop-finder match ...`."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from mashup_pop_finder import bpm, getsongbpm, songbpm_com, songkeyfinder
from mashup_pop_finder.http import make_client
from mashup_pop_finder.matching import classify_match_type, is_harmonic_match, ratio_to_base
from mashup_pop_finder.models import MatchResult, SongMeta
from mashup_pop_finder.output import print_table, write_csv
from mashup_pop_finder.recon import analyze as recon_analyze
from mashup_pop_finder.recon import api_probe as recon_api_probe
from mashup_pop_finder.recon import key_listing as recon_key_listing
from mashup_pop_finder.recon import search as recon_search

console = Console()


@click.group()
def cli() -> None:
    """mashup-pop-finder — mashup/pop key + BPM matcher."""
    load_dotenv()


# ---------- recon ------------------------------------------------------------


@cli.group()
def recon() -> None:
    """Capture real pages so production selectors can be pinned against
    observed HTML. See README §Recon-first."""


@recon.command("search")
@click.option("--title", required=True)
@click.option("--artist", required=True)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("./recon-output"),
    show_default=True,
)
def recon_search_cmd(title: str, artist: str, output_dir: Path) -> None:
    """Probe songkeyfinder.com with candidate search-URL shapes."""
    recon_search.run(title=title, artist=artist, output_dir=output_dir, console=console)
    console.print("\n[bold]Done.[/bold] Now run `python -m mashup_pop_finder recon analyze`.")


@recon.command("key")
@click.option("--key", "key_str", required=True, help='e.g. "B minor"')
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("./recon-output"),
    show_default=True,
)
def recon_key_cmd(key_str: str, output_dir: Path) -> None:
    """Probe songkeyfinder.com for "songs in this key" listing pages."""
    recon_key_listing.run(key=key_str, output_dir=output_dir, console=console)
    console.print("\n[bold]Done.[/bold] Now run `python -m mashup_pop_finder recon analyze`.")


@recon.command("api-probe")
@click.option("--title", default=None)
@click.option("--artist", default=None)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("./recon-output"),
    show_default=True,
)
def recon_api_probe_cmd(title: str | None, artist: str | None, output_dir: Path) -> None:
    """Fetch GetSongBPM's docs + (if a key is configured) hit a sample search."""
    recon_api_probe.run(
        title=title,
        artist=artist,
        output_dir=output_dir,
        api_key=os.getenv("GETSONGBPM_API_KEY"),
        console=console,
    )


@recon.command("analyze")
@click.option(
    "--input-dir",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("./recon-output"),
    show_default=True,
)
def recon_analyze_cmd(input_dir: Path) -> None:
    """Parse every saved HTML file in --input-dir and write SUMMARY.md."""
    analyses, _summary = recon_analyze.run(input_dir)
    console.print(f"Analyzed {len(analyses)} HTML file(s).")
    console.print(f"Wrote {input_dir / 'SUMMARY.md'}")
    if analyses:
        console.print(
            "\nShare SUMMARY.md (and a couple of the HTML files it references) "
            "back so selectors can be finalized."
        )


# ---------- match ------------------------------------------------------------


@cli.command()
@click.option("--title", required=True)
@click.option("--artist", required=True)
@click.option("--base-key", default=None, help="Skip the songkeyfinder lookup and use this key.")
@click.option("--base-bpm", type=float, default=None, help="Skip the base BPM lookup.")
@click.option("--tolerance", type=float, default=0.20, show_default=True)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option(
    "--pages",
    type=int,
    default=None,
    help="Songkeyfinder listing pages to fetch (30 songs/page). "
    "Default: enough pages for --limit.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("./matches.csv"),
    show_default=True,
)
@click.option(
    "--bpm-source",
    type=click.Choice(["songbpm", "getsongbpm"], case_sensitive=False),
    default="songbpm",
    show_default=True,
    help="Where to look up tempo (songbpm.com needs no API key).",
)
@click.option("--rate-limit-sleep", type=float, default=1.5, show_default=True)
@click.option("--debug", is_flag=True)
def match(
    title: str,
    artist: str,
    base_key: str | None,
    base_bpm: float | None,
    tolerance: float,
    limit: int,
    pages: int | None,
    output: Path,
    bpm_source: str,
    rate_limit_sleep: float,
    debug: bool,
) -> None:
    """Find songs in the same key as (title, artist) whose BPM matches harmonically."""
    source: bpm.BpmSource = bpm_source.lower()  # type: ignore[assignment]
    console.print(f"[dim]{bpm.attribution(source)}[/dim]")
    try:
        with make_client() as client:
            # 1. Resolve base song's key
            if base_key:
                base = SongMeta(title=title, artist=artist, key=base_key)
                console.print(f"Using provided base key: [cyan]{base_key}[/cyan]")
            else:
                console.print(f"Looking up base on songkeyfinder: {title} — {artist}")
                base = songkeyfinder.resolve_base_song(title, artist, client=client)
                console.print(f"  → key = [cyan]{base.key}[/cyan] ({base.source_url})")

            # 2. Resolve base BPM
            base_bpm_val: float
            if base_bpm is not None:
                base_bpm_val = base_bpm
                console.print(f"Using provided base BPM: [cyan]{base_bpm_val}[/cyan]")
            else:
                console.print(f"Looking up base BPM ({source})...")
                base_meta = bpm.lookup(title, artist, source=source, client=client)
                if base_meta is None or base_meta.bpm is None:
                    raise click.ClickException(
                        f"No BPM for {title!r} / {artist!r} via {source}. "
                        f"Pass --base-bpm to bypass."
                    )
                base_bpm_val = base_meta.bpm
                console.print(f"  → bpm = [cyan]{base_bpm_val}[/cyan]")

            base = SongMeta(title=base.title, artist=base.artist, key=base.key, bpm=base_bpm_val)

            # 3. Candidates in same key
            assert base.key is not None
            page_count = pages if pages is not None else songkeyfinder.pages_for_limit(limit)
            console.print(
                f"Listing songs in key [cyan]{base.key}[/cyan] "
                f"({page_count} page(s), limit {limit})..."
            )
            candidates = songkeyfinder.list_songs_in_key(
                base.key, limit=limit, pages=page_count, client=client
            )
            console.print(f"  → {len(candidates)} candidate(s)")

            # 4. Look up BPM for each, filter, classify
            matches: list[MatchResult] = []
            for i, c in enumerate(candidates, start=1):
                if i > 1:
                    time.sleep(rate_limit_sleep)
                try:
                    meta = bpm.lookup_candidate(c, source=source, client=client)
                except (songbpm_com.SongbpmComError, getsongbpm.GetSongBpmError) as exc:
                    console.print(f"  [yellow]skip[/yellow] {c.title} — {c.artist}: {exc}")
                    continue
                if meta is None or meta.bpm is None:
                    console.print(f"  [dim]no bpm[/dim] {c.title} — {c.artist}")
                    continue
                if not is_harmonic_match(base_bpm_val, meta.bpm, tolerance):
                    continue
                matches.append(
                    MatchResult(
                        candidate=c,
                        bpm=meta.bpm,
                        ratio=ratio_to_base(base_bpm_val, meta.bpm),
                        match_type=classify_match_type(base_bpm_val, meta.bpm, tolerance),
                        key=base.key,
                    )
                )

            # 5. Output
            matches.sort(key=lambda m: abs(m.ratio - round(m.ratio)))
            print_table(base, matches, console=console)
            n = write_csv(output, base, matches)
            console.print(f"\nWrote {n} match(es) to [bold]{output}[/bold].")
    except (
        songkeyfinder.SongkeyfinderError,
        songbpm_com.SongbpmComError,
        getsongbpm.GetSongBpmError,
        RuntimeError,
    ) as exc:
        if debug:
            raise
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(2)


if __name__ == "__main__":
    cli()
