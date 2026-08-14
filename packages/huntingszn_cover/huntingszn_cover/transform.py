"""Transform images using OpenAI image edit API."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

PREFERRED_MODEL = "gpt-image-1.5"
FALLBACK_MODEL = "gpt-image-1"
OUTPUT_SIZE = "1024x1024"


@dataclass
class TransformResult:
    """Result of an image transformation."""

    source_path: Path
    output_path: Path
    prompt_type: str
    model_used: str


class TransformError(Exception):
    """Raised when image transformation fails."""


def _get_openai_key() -> str:
    """Get OpenAI API key from environment.

    Raises:
        TransformError: If OPENAI_API_KEY is not set.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise TransformError(
            "OPENAI_API_KEY environment variable is required for image transformation. "
            "Get an API key at https://platform.openai.com/"
        )
    return key


def _prepare_image_for_api(image_path: Path) -> tuple[bytes, str]:
    """Prepare image for OpenAI API: convert to PNG, resize if needed.

    Returns:
        Tuple of (image bytes, filename).
    """
    img = Image.open(image_path)

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    max_size = 1024
    if img.width > max_size or img.height > max_size:
        ratio = min(max_size / img.width, max_size / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue(), "image.png"


def _image_to_base64_data_url(image_path: Path) -> str:
    """Convert image to base64 data URL for API."""
    img_bytes, _ = _prepare_image_for_api(image_path)
    b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def transform_image(
    image_path: Path,
    prompt: str,
    output_path: Path,
    *,
    model: str | None = None,
) -> TransformResult:
    """Transform an image using OpenAI's image edit API.

    This uses the images.edit endpoint, NOT text-to-image generation.

    Args:
        image_path: Path to source image.
        prompt: Transformation prompt.
        output_path: Path for output image.
        model: Model to use (defaults to gpt-image-1.5 with fallback to gpt-image-1).

    Returns:
        TransformResult with details of the transformation.

    Raises:
        TransformError: If transformation fails.
    """
    from openai import OpenAI

    _get_openai_key()
    client = OpenAI()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    model_to_use = model or PREFERRED_MODEL

    img_bytes, _filename = _prepare_image_for_api(image_path)

    try:
        response = client.images.edit(
            model=model_to_use,
            image=img_bytes,
            prompt=prompt,
            n=1,
            size=OUTPUT_SIZE,
        )
    except Exception as e:
        if model is None and model_to_use != FALLBACK_MODEL:
            try:
                response = client.images.edit(
                    model=FALLBACK_MODEL,
                    image=img_bytes,
                    prompt=prompt,
                    n=1,
                    size=OUTPUT_SIZE,
                )
                model_to_use = FALLBACK_MODEL
            except Exception as fallback_e:
                raise TransformError(
                    f"Image edit failed with both {PREFERRED_MODEL} and {FALLBACK_MODEL}: {fallback_e}"
                ) from fallback_e
        else:
            raise TransformError(f"Image edit failed: {e}") from e

    if not response.data:
        raise TransformError("No image data returned from API")

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
        raise TransformError("No image data or URL in API response")

    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(output_path, "PNG")

    return TransformResult(
        source_path=image_path,
        output_path=output_path,
        prompt_type=prompt[:50] + "..." if len(prompt) > 50 else prompt,
        model_used=model_to_use,
    )


def transform_with_prompts(
    image_path: Path,
    output_dir: Path,
    prompts: list[str],
    prompt_names: list[str],
    *,
    model: str | None = None,
) -> list[TransformResult]:
    """Transform an image with multiple prompts.

    Args:
        image_path: Source image path.
        output_dir: Output directory for transformed images.
        prompts: List of prompt texts.
        prompt_names: List of names for output files (e.g., ["clean", "crystal"]).
        model: Optional model override.

    Returns:
        List of TransformResult objects.
    """
    results: list[TransformResult] = []
    stem = image_path.stem

    for prompt, name in zip(prompts, prompt_names, strict=True):
        output_path = output_dir / f"{stem}-{name}.png"
        result = transform_image(image_path, prompt, output_path, model=model)
        results.append(result)

    return results
