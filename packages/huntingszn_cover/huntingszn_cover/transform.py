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
PNG_CONTENT_TYPE = "image/png"

# OpenAI FileTypes: (filename, bytes, content_type). Raw bytes are sent as
# application/octet-stream with filename="upload", which images.edit rejects.
OpenAIPngFile = tuple[str, bytes, str]


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


def openai_png_file(image_bytes: bytes, filename: str = "image.png") -> OpenAIPngFile:
    """Build an OpenAI/httpx file tuple with an explicit PNG content type.

    Passing raw bytes makes the SDK send ``application/octet-stream``.
    """
    return (filename, image_bytes, PNG_CONTENT_TYPE)


def prepare_openai_image(image_path: Path, *, filename: str = "image.png") -> OpenAIPngFile:
    """Prepare image for OpenAI images.edit: convert to PNG, resize if needed.

    Returns:
        ``(filename, png_bytes, "image/png")`` suitable for ``client.images.edit``.
    """
    try:
        img = Image.open(image_path)
    except OSError as e:
        raise TransformError(f"Cannot read image {image_path}: {e}") from e

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    max_size = 1024
    if img.width > max_size or img.height > max_size:
        ratio = min(max_size / img.width, max_size / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return openai_png_file(buffer.getvalue(), filename)


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

    image_file = prepare_openai_image(image_path)

    def _edit(model_name: str) -> object:
        return client.images.edit(
            model=model_name,
            image=image_file,
            prompt=prompt,
            n=1,
            size=OUTPUT_SIZE,
        )

    def _image_from_response(response: object) -> Image.Image:
        data = getattr(response, "data", None)
        if not data:
            raise TransformError("No image data returned from API")
        image_data = data[0]
        if getattr(image_data, "b64_json", None):
            img_bytes = base64.b64decode(image_data.b64_json)
            return Image.open(BytesIO(img_bytes))
        if getattr(image_data, "url", None):
            import httpx

            with httpx.Client(timeout=60.0) as http_client:
                img_response = http_client.get(image_data.url)
                img_response.raise_for_status()
                return Image.open(BytesIO(img_response.content))
        raise TransformError("No image data or URL in API response")

    try:
        img = _image_from_response(_edit(model_to_use))
    except Exception as e:
        if model is None and model_to_use != FALLBACK_MODEL:
            try:
                img = _image_from_response(_edit(FALLBACK_MODEL))
                model_to_use = FALLBACK_MODEL
            except Exception as fallback_e:
                raise TransformError(
                    f"Image edit failed with both {PREFERRED_MODEL} and {FALLBACK_MODEL}: {fallback_e}"
                ) from fallback_e
        else:
            raise TransformError(f"Image edit failed: {e}") from e

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
