"""Click CLI: huntingszn-cover fetch, transform, mashup."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli() -> None:
    """huntingszn-cover — album cover fetch, transform, and mashup tool."""
    load_dotenv()


@cli.command()
@click.option(
    "--tracks",
    "-t",
    multiple=True,
    required=True,
    help='Track in "Artist:Title" format. Can be specified multiple times.',
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("./covers"),
    show_default=True,
    help="Output directory for fetched images.",
)
@click.option(
    "--count",
    "-n",
    type=int,
    default=5,
    show_default=True,
    help="Target number of unique covers per track.",
)
def fetch(tracks: tuple[str, ...], output: Path, count: int) -> None:
    """Fetch album cover images via SerpAPI Google Images.

    Searches for square album covers, deduplicates using perceptual hashing,
    and saves originals to the output directory.

    Requires SERPAPI_API_KEY environment variable.

    Example:
        huntingszn-cover fetch --tracks "Olivia Rodrigo:The Cure" --tracks "Illenium:Pray"
    """
    from huntingszn_cover.fetch import FetchError, fetch_tracks

    try:
        console.print(f"[bold]Fetching album covers for {len(tracks)} track(s)...[/bold]")

        results = fetch_tracks(list(tracks), output, target_count=count)

        table = Table(title="Fetched Album Covers")
        table.add_column("Track", style="cyan")
        table.add_column("Images", justify="right")
        table.add_column("Directory", style="dim")

        for track, images in results.items():
            if images:
                table.add_row(track, str(len(images)), str(images[0].local_path.parent))
            else:
                table.add_row(track, "0", "-")

        console.print(table)

        total = sum(len(imgs) for imgs in results.values())
        console.print(f"\n[green]Fetched {total} unique image(s) total.[/green]")

    except (FetchError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--image",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to source image to transform.",
)
@click.option(
    "--prompts",
    "-p",
    multiple=True,
    required=True,
    type=click.Choice(["clean", "crystal"]),
    help="Prompt type(s) to apply. Can be specified multiple times.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (defaults to same directory as input).",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="OpenAI model to use (default: gpt-image-1.5 with fallback to gpt-image-1).",
)
def transform(
    image: Path,
    prompts: tuple[str, ...],
    output: Path | None,
    model: str | None,
) -> None:
    """Transform an image using OpenAI image edit API.

    Applies transformation prompts (clean, crystal) to create stylized versions.
    This uses OpenAI's images.edit endpoint with the source image as input.

    Requires OPENAI_API_KEY environment variable.
    Prompts are loaded from files in order: env var, workspace assets,
    /Volumes/HuntingSzn/Thumbnails/, then package prompts/ as fallback only.

    Example:
        huntingszn-cover transform --image cover.png --prompts clean --prompts crystal
    """
    from huntingszn_cover.prompts import get_prompt
    from huntingszn_cover.transform import TransformError, transform_with_prompts

    output_dir = output or image.parent

    try:
        prompt_texts: list[str] = []
        prompt_names: list[str] = []

        for p in prompts:
            console.print(f"Loading prompt: [cyan]{p}[/cyan]")
            prompt_text = get_prompt(p)  # type: ignore[arg-type]
            prompt_texts.append(prompt_text)
            prompt_names.append(p)
            console.print(f"  Prompt loaded ({len(prompt_text)} chars)")

        console.print(f"\n[bold]Transforming {image.name}...[/bold]")

        results = transform_with_prompts(
            image,
            output_dir,
            prompt_texts,
            prompt_names,
            model=model,
        )

        table = Table(title="Transformation Results")
        table.add_column("Prompt", style="cyan")
        table.add_column("Model", style="yellow")
        table.add_column("Output", style="green")

        for result in results:
            table.add_row(
                result.prompt_type,
                result.model_used,
                str(result.output_path),
            )

        console.print(table)
        console.print(f"\n[green]Created {len(results)} transformed image(s).[/green]")

    except (TransformError, FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--mashup",
    "-m",
    required=True,
    help='Mashup name (e.g., "The Cure x Pray").',
)
@click.option(
    "--tracks",
    "-t",
    multiple=True,
    required=True,
    help='Track in "Artist:Title" format. Can be specified multiple times.',
)
@click.option(
    "--pick",
    is_flag=True,
    help="Manually pick covers instead of auto-selecting best square cover.",
)
@click.option(
    "--image",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Override: use these local images instead of fetching. Rare use only.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("./covers"),
    show_default=True,
    help="Output directory base.",
)
@click.option(
    "--count",
    "-n",
    type=int,
    default=5,
    show_default=True,
    help="Number of covers to fetch per track.",
)
@click.option(
    "--volume",
    type=click.Path(path_type=Path),
    default=None,
    help="Volume path to copy results to (e.g., /Volumes/HuntingSzn/Thumbnails/Releases).",
)
def mashup(
    mashup: str,
    tracks: tuple[str, ...],
    pick: bool,
    image: tuple[Path, ...],
    output: Path,
    count: int,
    volume: Path | None,
) -> None:
    """Create a mashup album cover composite.

    ALWAYS fetches fresh album covers via SerpAPI Google Images (default behavior).
    Auto-selects the best square cover per track, then creates a composite via
    OpenAI multi-image edit (gpt-image-1.5, falling back to gpt-image-1) and
    transforms with clean + crystal prompts.

    Does NOT read from or overwrite existing Releases folders - those are finished work only.
    Use --image only as a rare override when fetch returns unusable results.

    Requires both SERPAPI_API_KEY and OPENAI_API_KEY environment variables.

    Example:
        huntingszn-cover mashup \\
            --mashup "The Cure x Pray" \\
            --tracks "Olivia Rodrigo:The Cure" \\
            --tracks "Illenium:Pray"
    """
    from huntingszn_cover.fetch import FetchedImage, FetchError
    from huntingszn_cover.mashup import MashupError, run_mashup
    from huntingszn_cover.transform import TransformError

    volume_path = volume
    if volume_path is None:
        default_volume = Path("/Volumes/HuntingSzn/Thumbnails/Releases")
        if default_volume.exists():
            volume_path = default_volume

    override_images = list(image) if image else None

    def _cli_picker(track: str, images: list[FetchedImage]) -> FetchedImage | None:
        if not images:
            return None
        if len(images) == 1:
            console.print(
                f"Only one cover for [cyan]{track}[/cyan], using {images[0].local_path.name}"
            )
            return images[0]

        console.print(f"\n[bold]Select cover for {track}:[/bold]")
        for i, img in enumerate(images):
            console.print(f"  [{i}] {img.local_path} ({img.width}x{img.height})")

        if not sys.stdin.isatty():
            raise MashupError(
                "Cannot use --pick without an interactive terminal. "
                "Re-run with --image using two of the candidate paths listed above."
            )

        idx = click.prompt("Index", type=click.IntRange(0, len(images) - 1))
        return images[idx]

    try:
        console.print(f"[bold]Creating mashup: {mashup}[/bold]")
        console.print(f"Tracks: {', '.join(tracks)}")
        if override_images:
            console.print(f"[yellow]Using override images:[/yellow] {override_images}")
        else:
            console.print("[dim]Fetching fresh covers via SerpAPI (default)[/dim]")
        console.print(f"Output: {output}")
        if volume_path:
            console.print(f"Will copy to volume: {volume_path}")
        console.print()

        manifest = run_mashup(
            mashup,
            list(tracks),
            output,
            auto=not pick,
            target_covers=count,
            volume_path=volume_path,
            override_images=override_images,
            picker=_cli_picker if pick and not override_images else None,
        )

        console.print("\n[bold green]Mashup complete![/bold green]")
        console.print(f"Slug: [cyan]{manifest.slug}[/cyan]")
        console.print(f"Output directory: [dim]{manifest.output_dir}[/dim]")

        if manifest.originals:
            console.print("\n[bold]Original covers:[/bold]")
            for track, paths in manifest.originals.items():
                console.print(f"  {track}: {len(paths)} image(s)")

        if manifest.composite_path:
            method = manifest.composite_method or "unknown"
            console.print(f"\n[bold]Composite:[/bold] {manifest.composite_path} [{method}]")

        if manifest.transformed:
            console.print("\n[bold]Transformed images:[/bold]")
            for key, paths in manifest.transformed.items():
                console.print(f"  {key}: {len(paths)} image(s)")

        if manifest.copied_to_volume:
            console.print(f"\n[green]Copied to volume:[/green] {manifest.copied_to_volume}")
        elif volume_path is not None:
            existing = volume_path / mashup
            if existing.exists():
                console.print(
                    f"\n[yellow]Skipped volume copy; release folder already exists "
                    f"(finished work, not overwritten):[/yellow] {existing}"
                )

        console.print(f"\n[dim]Manifest: {manifest.output_dir}/manifest.json[/dim]")

    except (FetchError, TransformError, MashupError, FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
