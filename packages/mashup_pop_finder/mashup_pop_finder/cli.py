"""Click CLI: `music-script recon ...` + `music-script match ...`."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from music_script import getsongbpm, songkeyfinder
from music_script.http import make_client
from music_script.matching import classify_match_type, is_harmonic_match, ratio_to_base
from music_script.models import MatchResult, SongMeta
from music_script.output import print_table, write_csv
from music_script.recon import analyze as recon_analyze
from music_script.recon import api_probe as recon_api_probe
from music_script.recon import key_listing as recon_key_listing
from music_script.recon import search as recon_search

console = Console()


@click.group()
def cli() -> None:
    """music-script — harmonic key + BPM matcher."""
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
    console.print("\n[bold]Done.[/bold] Now run `python -m music_script recon analyze`.")


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
    console.print("\n[bold]Done.[/bold] Now run `python -m music_script recon analyze`.")


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
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("./matches.csv"),
    show_default=True,
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
    output: Path,
    rate_limit_sleep: float,
    debug: bool,
) -> None:
    """Find songs in the same key as (title, artist) whose BPM matches harmonically."""
    console.print("[dim]Powered by GetSongBPM — https://getsongbpm.com[/dim]")
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
                console.print("Looking up base BPM on GetSongBPM...")
                base_meta = getsongbpm.lookup(title, artist, client=client)
                if base_meta is None or base_meta.bpm is None:
                    raise click.ClickException(
                        f"GetSongBPM had no BPM for {title!r} / {artist!r}. "
                        f"Pass --base-bpm to bypass."
                    )
                base_bpm_val = base_meta.bpm
                console.print(f"  → bpm = [cyan]{base_bpm_val}[/cyan]")

            base = SongMeta(title=base.title, artist=base.artist, key=base.key, bpm=base_bpm_val)

            # 3. Candidates in same key
            assert base.key is not None
            console.print(f"Listing songs in key [cyan]{base.key}[/cyan] (limit {limit})...")
            candidates = songkeyfinder.list_songs_in_key(base.key, limit=limit, client=client)
            console.print(f"  → {len(candidates)} candidate(s)")

            # 4. Look up BPM for each, filter, classify
            matches: list[MatchResult] = []
            for i, c in enumerate(candidates, start=1):
                if i > 1:
                    time.sleep(rate_limit_sleep)
                try:
                    meta = getsongbpm.lookup_candidate(c, client=client)
                except getsongbpm.GetSongBpmError as exc:
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
    except (songkeyfinder.SongkeyfinderError, getsongbpm.GetSongBpmError, RuntimeError) as exc:
        if debug:
            raise
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(2)


if __name__ == "__main__":
    cli()
