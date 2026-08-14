"""Tests for OpenAI image edit payload encoding and transform behavior."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from openai import OpenAI
from PIL import Image

from huntingszn_cover.transform import (
    PNG_CONTENT_TYPE,
    openai_png_file,
    prepare_openai_image,
    transform_image,
)


def write_png(
    path: Path, size: tuple[int, int] = (32, 32), color: tuple[int, int, int] = (255, 0, 0)
) -> Path:
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


class CaptureTransport(httpx2.BaseTransport):
    """Capture the outbound OpenAI HTTP request for multipart inspection."""

    def __init__(self, response_png: bytes | None = None) -> None:
        self.request: httpx2.Request | None = None
        self._response_png = response_png or png_bytes()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.request = request
        request.read()
        b64 = base64.b64encode(self._response_png).decode("ascii")
        return httpx2.Response(
            200,
            json={"created": 1, "data": [{"b64_json": b64}]},
            request=request,
        )


def _multipart_text(request: httpx2.Request) -> str:
    assert request is not None
    return request.content.decode("latin1")


def test_openai_png_file_tuple() -> None:
    payload = openai_png_file(b"\x89PNG", "cover.png")
    assert payload == ("cover.png", b"\x89PNG", PNG_CONTENT_TYPE)


def test_prepare_openai_image_returns_png_tuple(tmp_path: Path) -> None:
    src = write_png(tmp_path / "cover.jpg")
    filename, data, content_type = prepare_openai_image(src)
    assert filename == "image.png"
    assert content_type == "image/png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_raw_bytes_are_sent_as_octet_stream() -> None:
    """Document the production failure mode: raw bytes => application/octet-stream."""
    png = png_bytes()
    cap = CaptureTransport(png)
    client = OpenAI(api_key="sk-test", http_client=httpx2.Client(transport=cap))
    client.images.edit(model="gpt-image-1", image=png, prompt="x", n=1, size="1024x1024")
    body = _multipart_text(cap.request)
    assert "application/octet-stream" in body
    assert 'filename="upload"' in body
    assert "Content-Type: image/png" not in body


def test_png_tuple_is_sent_as_image_png() -> None:
    png = png_bytes()
    cap = CaptureTransport(png)
    client = OpenAI(api_key="sk-test", http_client=httpx2.Client(transport=cap))
    client.images.edit(
        model="gpt-image-1",
        image=("image.png", png, "image/png"),
        prompt="x",
        n=1,
        size="1024x1024",
    )
    body = _multipart_text(cap.request)
    assert "Content-Type: image/png" in body
    assert "application/octet-stream" not in body
    assert 'filename="image.png"' in body


def test_transform_image_sends_image_png_not_octet_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    src = write_png(tmp_path / "src.png")
    out = tmp_path / "out.png"
    response_png = png_bytes((16, 16))
    cap = CaptureTransport(response_png)
    real_client = OpenAI(api_key="sk-test", http_client=httpx2.Client(transport=cap))

    with patch("openai.OpenAI", return_value=real_client):
        result = transform_image(src, "HUNTINGSZN EDIT prompt", out, model="gpt-image-1")

    assert result.output_path == out
    assert out.is_file()
    assert cap.request is not None
    assert "/images/edits" in str(cap.request.url)
    assert "generations" not in str(cap.request.url)
    body = _multipart_text(cap.request)
    assert "Content-Type: image/png" in body
    assert "application/octet-stream" not in body
    assert 'filename="image.png"' in body


def test_transform_image_does_not_call_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    src = write_png(tmp_path / "src.png")
    out = tmp_path / "out.png"

    mock_client = MagicMock()
    mock_image = MagicMock()
    mock_image.b64_json = base64.b64encode(png_bytes()).decode("ascii")
    mock_image.url = None
    mock_client.images.edit.return_value = MagicMock(data=[mock_image])

    with patch("openai.OpenAI", return_value=mock_client):
        transform_image(src, "HUNTINGSZN EDIT prompt", out, model="gpt-image-1")

    mock_client.images.edit.assert_called_once()
    mock_client.images.generate.assert_not_called()
    image_arg = mock_client.images.edit.call_args.kwargs["image"]
    assert isinstance(image_arg, tuple)
    assert image_arg[0] == "image.png"
    assert image_arg[2] == "image/png"
