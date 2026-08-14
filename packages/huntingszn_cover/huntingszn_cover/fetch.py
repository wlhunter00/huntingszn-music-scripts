"""Fetch album cover images via SerpAPI Google Images."""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import imagehash
from PIL import Image

if TYPE_CHECKING:
    from collections.abc import Sequence

SERPAPI_BASE_URL = "https://serpapi.com/search"
DEFAULT_TARGET_COUNT = 5
HASH_THRESHOLD = 8


@dataclass
class FetchedImage:
    """Represents a fetched and deduplicated album cover image."""

    url: str
    local_path: Path
    width: int
    height: int
    phash: str


class FetchError(Exception):
    """Raised when image fetching fails."""


def _redact_secret(text: str, secret: str) -> str:
    """Strip a secret from an error string so it cannot leak to logs."""
    if not secret:
        return text
    return text.replace(secret, "***")


def _get_serpapi_key() -> str:
    """Get SerpAPI key from environment.

    Raises:
        FetchError: If SERPAPI_API_KEY is not set.
    """
    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        raise FetchError(
            "SERPAPI_API_KEY environment variable is required for image search. "
            "Get an API key at https://serpapi.com/"
        )
    return key


def search_album_covers(
    artist: str,
    title: str,
    *,
    client: httpx.Client | None = None,
    num_results: int = 20,
) -> list[dict]:
    """Search for album cover images using SerpAPI Google Images.

    Args:
        artist: Artist name.
        title: Track/album title.
        client: Optional httpx client.
        num_results: Number of results to request.

    Returns:
        List of image result dictionaries from SerpAPI.

    Raises:
        FetchError: If the API call fails.
    """
    api_key = _get_serpapi_key()
    query = f"{artist} {title} album cover square"

    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "num": num_results,
        "safe": "off",
        "tbm": "isch",
    }

    should_close = client is None
    client = client or httpx.Client(timeout=30.0)

    try:
        # POST keeps api_key out of the request URL (GET query strings show up in
        # httpx HTTPStatusError messages and tracebacks).
        response = client.post(SERPAPI_BASE_URL, data=params)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            raise FetchError("Invalid JSON in SerpAPI response") from None
    except httpx.HTTPStatusError as e:
        # from None: httpx interpolates the request URL into HTTPStatusError,
        # which used to leak api_key even after the FetchError message was sanitized.
        raise FetchError(
            f"HTTP error during SerpAPI request: {e.response.status_code}"
        ) from None
    except httpx.HTTPError:
        raise FetchError("HTTP error during SerpAPI request") from None
    finally:
        if should_close:
            client.close()

    if "error" in data:
        raise FetchError(_redact_secret(f"SerpAPI error: {data['error']}", api_key))

    return data.get("images_results", [])


def _is_roughly_square(width: int, height: int, tolerance: float = 0.2) -> bool:
    """Check if dimensions are roughly square (within tolerance)."""
    if width == 0 or height == 0:
        return False
    ratio = width / height
    return (1 - tolerance) <= ratio <= (1 + tolerance)


def _compute_phash(img: Image.Image) -> str:
    """Compute perceptual hash for image deduplication."""
    return str(imagehash.phash(img))


def _is_duplicate(new_hash: str, existing_hashes: Sequence[str]) -> bool:
    """Check if the new hash is too similar to existing hashes."""
    new_phash = imagehash.hex_to_hash(new_hash)
    for existing in existing_hashes:
        existing_phash = imagehash.hex_to_hash(existing)
        if new_phash - existing_phash < HASH_THRESHOLD:
            return True
    return False


def download_image(url: str, *, client: httpx.Client | None = None) -> Image.Image | None:
    """Download an image from URL and return as PIL Image.

    Returns:
        PIL Image or None if download fails.
    """
    should_close = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    try:
        response = client.get(url)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except (httpx.HTTPError, OSError):
        return None
    finally:
        if should_close:
            client.close()


def fetch_album_covers(
    artist: str,
    title: str,
    output_dir: Path,
    *,
    target_count: int = DEFAULT_TARGET_COUNT,
    client: httpx.Client | None = None,
) -> list[FetchedImage]:
    """Fetch and deduplicate album cover images for a track.

    Args:
        artist: Artist name.
        title: Track/album title.
        output_dir: Directory to save images.
        target_count: Target number of unique images to fetch.
        client: Optional httpx client.

    Returns:
        List of FetchedImage objects for successfully fetched images.

    Raises:
        FetchError: If API key is missing or search fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    should_close = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    try:
        results = search_album_covers(artist, title, client=client, num_results=target_count * 4)

        fetched: list[FetchedImage] = []
        seen_hashes: list[str] = []

        for i, result in enumerate(results):
            if len(fetched) >= target_count:
                break

            img_url = result.get("original") or result.get("thumbnail")
            if not img_url:
                continue

            img = download_image(img_url, client=client)
            if img is None:
                continue

            width, height = img.size
            if not _is_roughly_square(width, height):
                continue

            phash = _compute_phash(img)
            if _is_duplicate(phash, seen_hashes):
                continue

            seen_hashes.append(phash)

            filename = f"cover_{i:02d}.png"
            local_path = output_dir / filename

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(local_path, "PNG")

            fetched.append(
                FetchedImage(
                    url=img_url,
                    local_path=local_path,
                    width=width,
                    height=height,
                    phash=phash,
                )
            )

        return fetched
    finally:
        if should_close:
            client.close()


def fetch_tracks(
    tracks: list[str],
    output_base: Path,
    *,
    target_count: int = DEFAULT_TARGET_COUNT,
) -> dict[str, list[FetchedImage]]:
    """Fetch album covers for multiple tracks.

    Args:
        tracks: List of tracks in "Artist:Title" format.
        output_base: Base directory for output.
        target_count: Target images per track.

    Returns:
        Dict mapping track string to list of FetchedImage objects.
    """
    from huntingszn_cover.utils import parse_track, track_slug

    results: dict[str, list[FetchedImage]] = {}

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for track in tracks:
            artist, title = parse_track(track)
            slug = track_slug(track)
            track_dir = output_base / slug

            fetched = fetch_album_covers(
                artist,
                title,
                track_dir,
                target_count=target_count,
                client=client,
            )
            results[track] = fetched

    return results
