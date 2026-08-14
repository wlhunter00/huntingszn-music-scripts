"""Mashup composite creation: combine album covers and transform."""

from __future__ import annotations

import base64
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

from huntingszn_cover.fetch import FetchedImage, fetch_album_covers
from huntingszn_cover.prompts import get_prompt
from huntingszn_cover.transform import (
    OUTPUT_SIZE,
    PREFERRED_MODEL,
    transform_image,
)
from huntingszn_cover.utils import parse_track, slugify, track_slug


@dataclass
class MashupManifest:
    """Manifest tracking all files created for a mashup."""

    mashup_name: str
    slug: str
    tracks: list[str]
    created_at: str
    originals: dict[str, list[str]] = field(default_factory=dict)
    composite_path: str | None = None
    transformed: dict[str, list[str]] = field(default_factory=dict)
    output_dir: str = ""
    copied_to_volume: str | None = None


class MashupError(Exception):
    """Raised when mashup creation fails."""


def _select_best_cover(images: list[FetchedImage]) -> FetchedImage | None:
    """Select the best (most square) cover from fetched images."""
    if not images:
        return None

    def squareness(img: FetchedImage) -> float:
        if img.width == 0 or img.height == 0:
            return 0.0
        ratio = min(img.width, img.height) / max(img.width, img.height)
        return ratio * max(img.width, img.height)

    return max(images, key=squareness)


def create_pillow_composite(
    images: list[Path],
    output_path: Path,
    size: int = 1024,
) -> Path:
    """Create a 50/50 split composite using Pillow.

    Args:
        images: List of image paths (uses first two).
        output_path: Output path for composite.
        size: Output size (square).

    Returns:
        Path to created composite.
    """
    if len(images) < 2:
        raise MashupError("Need at least 2 images for composite")

    img1 = Image.open(images[0]).convert("RGB")
    img2 = Image.open(images[1]).convert("RGB")

    half_width = size // 2
    img1_resized = img1.resize((half_width, size), Image.Resampling.LANCZOS)
    img2_resized = img2.resize((half_width, size), Image.Resampling.LANCZOS)

    composite = Image.new("RGB", (size, size))
    composite.paste(img1_resized, (0, 0))
    composite.paste(img2_resized, (half_width, 0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(output_path, "PNG")
    return output_path


def create_openai_composite(
    images: list[Path],
    output_path: Path,
    prompt: str,
    *,
    model: str | None = None,
) -> tuple[Path, str]:
    """Create composite using OpenAI multi-image edit (gpt-image-1.5).

    Falls back to Pillow composite if multi-image edit fails.

    Args:
        images: List of source image paths.
        output_path: Output path for composite.
        prompt: Prompt for the composite edit.
        model: Model to use.

    Returns:
        Tuple of (output path, model/method used).
    """
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise MashupError("OPENAI_API_KEY required for composite creation")

    model_to_use = model or PREFERRED_MODEL
    client = OpenAI()

    def prepare_image(path: Path) -> bytes:
        img = Image.open(path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        if img.width > 1024 or img.height > 1024:
            ratio = min(1024 / img.width, 1024 / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    try:
        image_bytes_list = [prepare_image(p) for p in images[:2]]

        response = client.images.edit(
            model=model_to_use,
            image=image_bytes_list,
            prompt=prompt,
            n=1,
            size=OUTPUT_SIZE,
        )

        if not response.data:
            raise MashupError("No composite data returned")

        image_data = response.data[0]

        if hasattr(image_data, "b64_json") and image_data.b64_json:
            img_bytes = base64.b64decode(image_data.b64_json)
            img = Image.open(BytesIO(img_bytes))
        elif hasattr(image_data, "url") and image_data.url:
            import httpx

            with httpx.Client(timeout=60.0) as http_client:
                img_response = http_client.get(image_data.url)
                img_response.raise_for_status()
                img = Image.open(BytesIO(img_response.content))
        else:
            raise MashupError("No image data in response")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output_path, "PNG")
        return output_path, model_to_use

    except Exception:
        create_pillow_composite(images, output_path)
        return output_path, "pillow-split"


def run_mashup(
    mashup_name: str,
    tracks: list[str],
    output_dir: Path,
    *,
    auto: bool = True,
    target_covers: int = 5,
    volume_path: Path | None = None,
    override_images: list[Path] | None = None,
) -> MashupManifest:
    """Run the full mashup pipeline: fetch, composite, transform.

    ALWAYS fetches fresh covers via SerpAPI unless override_images is provided.
    Does NOT read from existing Releases folders - those are finished work only.

    Args:
        mashup_name: Name for the mashup (e.g., "The Cure x Pray").
        tracks: List of tracks in "Artist:Title" format.
        output_dir: Output directory.
        auto: If True (default), auto-select best square covers for composite.
        target_covers: Number of covers to fetch per track.
        volume_path: Optional path to copy results (e.g., /Volumes/HuntingSzn/Thumbnails/Releases).
        override_images: Optional list of local image paths to use instead of fetching.
                        Rare override only - use when fetch returns unusable results.

    Returns:
        MashupManifest documenting all created files.

    Raises:
        MashupError: If fetch returns no usable square covers and no override provided.
    """
    slug = slugify(mashup_name)
    mashup_dir = output_dir / slug
    mashup_dir.mkdir(parents=True, exist_ok=True)

    manifest = MashupManifest(
        mashup_name=mashup_name,
        slug=slug,
        tracks=tracks,
        created_at=datetime.now().isoformat(),
        output_dir=str(mashup_dir),
    )

    best_covers: list[Path] = []

    if override_images:
        best_covers = override_images
        manifest.originals["override"] = [str(p) for p in override_images]
    else:
        import httpx

        track_images: dict[str, list[FetchedImage]] = {}
        failed_tracks: list[str] = []
        all_candidates: dict[str, list[str]] = {}

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            for track in tracks:
                artist, title = parse_track(track)
                tslug = track_slug(track)
                track_dir = mashup_dir / "originals" / tslug

                fetched = fetch_album_covers(
                    artist, title, track_dir, target_count=target_covers, client=client
                )
                track_images[track] = fetched
                manifest.originals[track] = [str(f.local_path) for f in fetched]
                all_candidates[track] = [str(f.local_path) for f in fetched]

                if auto:
                    best = _select_best_cover(fetched)
                    if best:
                        best_covers.append(best.local_path)
                    else:
                        failed_tracks.append(track)

        if auto and len(best_covers) < 2:
            candidate_info = "\n".join(
                f"  {track}: {paths if paths else '(no images fetched)'}"
                for track, paths in all_candidates.items()
            )
            raise MashupError(
                f"Fetch did not return usable square covers for all tracks.\n"
                f"Need at least 2 covers for composite, got {len(best_covers)}.\n"
                f"Failed tracks: {failed_tracks}\n"
                f"Candidate images fetched:\n{candidate_info}\n\n"
                f"Options:\n"
                f"  1. Re-run with different track names\n"
                f"  2. Use --image to provide local images as override"
            )

    if len(best_covers) < 2:
        raise MashupError(
            f"Need at least 2 images for composite, got {len(best_covers)}. "
            f"Provide more tracks or use --image override."
        )

    composite_path = mashup_dir / f"{slug}-composite.png"

    composite_prompt = (
        f"Create a seamless mashup album cover blending these two album art images. "
        f"This is for '{mashup_name}'. Create an artistic composite that merges "
        f"the visual elements of both covers into one cohesive design."
    )

    composite_path, _method = create_openai_composite(
        best_covers, composite_path, composite_prompt
    )
    manifest.composite_path = str(composite_path)

    prompt_clean = get_prompt("clean")
    prompt_crystal = get_prompt("crystal")

    composite_results = []
    for prompt, ptype in [(prompt_clean, "clean"), (prompt_crystal, "crystal")]:
        out_path = mashup_dir / f"{slug}-composite-{ptype}.png"
        result = transform_image(composite_path, prompt, out_path)
        composite_results.append(result)

    manifest.transformed["composite"] = [str(r.output_path) for r in composite_results]

    if not override_images:
        for track in tracks:
            fetched = track_images.get(track, [])
            best = _select_best_cover(fetched)
            if best:
                tslug = track_slug(track)
                track_results = []
                for prompt, ptype in [(prompt_clean, "clean"), (prompt_crystal, "crystal")]:
                    out_path = mashup_dir / "transformed" / tslug / f"{tslug}-{ptype}.png"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    result = transform_image(best.local_path, prompt, out_path)
                    track_results.append(result)
                manifest.transformed[track] = [str(r.output_path) for r in track_results]

    if volume_path and volume_path.exists():
        dest = volume_path / mashup_name
        if mashup_dir.exists():
            shutil.copytree(mashup_dir, dest, dirs_exist_ok=True)
            manifest.copied_to_volume = str(dest)

    manifest_path = mashup_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(
            {
                "mashup_name": manifest.mashup_name,
                "slug": manifest.slug,
                "tracks": manifest.tracks,
                "created_at": manifest.created_at,
                "originals": manifest.originals,
                "composite_path": manifest.composite_path,
                "transformed": manifest.transformed,
                "output_dir": manifest.output_dir,
                "copied_to_volume": manifest.copied_to_volume,
            },
            f,
            indent=2,
        )

    return manifest
