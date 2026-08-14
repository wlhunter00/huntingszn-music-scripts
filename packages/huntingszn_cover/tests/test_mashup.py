"""Tests for mashup cover selection, fetch-failure, and OpenAI composite payload."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from click.testing import CliRunner
from openai import OpenAI
from PIL import Image

from huntingszn_cover.cli import cli
from huntingszn_cover.cli import mashup as mashup_cmd
from huntingszn_cover.fetch import FetchedImage
from huntingszn_cover.mashup import (
    MashupError,
    _select_best_cover,
    create_openai_composite,
    create_pillow_composite,
    run_mashup,
)
from huntingszn_cover.transform import FALLBACK_MODEL, PREFERRED_MODEL, TransformResult


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


def _fetched(path: Path, width: int, height: int) -> FetchedImage:
    return FetchedImage(
        url="https://example.com/x.png", local_path=path, width=width, height=height, phash="0"
    )


def test_select_best_cover_prefers_square() -> None:
    square = _fetched(Path("sq.png"), 1000, 1000)
    wide = _fetched(Path("wide.png"), 1600, 900)
    chosen = _select_best_cover([wide, square])
    assert chosen is square


def test_select_best_cover_empty() -> None:
    assert _select_best_cover([]) is None


def test_pillow_composite(tmp_path: Path) -> None:
    a = write_png(tmp_path / "a.png", (100, 100), (255, 0, 0))
    b = write_png(tmp_path / "b.png", (100, 100), (0, 0, 255))
    out = tmp_path / "composite.png"
    create_pillow_composite([a, b], out, size=64)
    img = Image.open(out)
    assert img.size == (64, 64)


def test_create_openai_composite_sends_image_png_not_octet_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    a = write_png(tmp_path / "a.png")
    b = write_png(tmp_path / "b.png", color=(0, 0, 255))
    out = tmp_path / "composite.png"
    cap = CaptureTransport(png_bytes((16, 16)))
    real_client = OpenAI(api_key="sk-test", http_client=httpx2.Client(transport=cap))

    with patch("openai.OpenAI", return_value=real_client):
        path, method = create_openai_composite([a, b], out, "blend these covers")

    assert path == out
    assert method == "gpt-image-1.5"
    assert cap.request is not None
    assert "/images/edits" in str(cap.request.url)
    assert "generations" not in str(cap.request.url)
    body = cap.request.content.decode("latin1")
    assert "Content-Type: image/png" in body
    assert "application/octet-stream" not in body
    assert 'filename="image_0.png"' in body
    assert 'filename="image_1.png"' in body
    assert 'name="image[]"' in body


def test_create_openai_composite_raises_on_edit_failure_without_pillow_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    a = write_png(tmp_path / "a.png")
    b = write_png(tmp_path / "b.png", color=(0, 0, 255))
    out = tmp_path / "composite.png"

    mock_client = MagicMock()
    mock_client.images.edit.side_effect = RuntimeError("api down")

    with (
        patch("openai.OpenAI", return_value=mock_client),
        pytest.raises(MashupError, match="Image edit failed"),
    ):
        create_openai_composite([a, b], out, "blend")

    assert not out.exists()
    assert mock_client.images.edit.call_count == 2
    models = [c.kwargs["model"] for c in mock_client.images.edit.call_args_list]
    assert models == [PREFERRED_MODEL, FALLBACK_MODEL]
    mock_client.images.generate.assert_not_called()
    for call in mock_client.images.edit.call_args_list:
        image_arg = call.kwargs["image"]
        assert isinstance(image_arg, list)
        assert all(part[2] == "image/png" for part in image_arg)


def test_create_openai_composite_falls_back_to_gpt_image_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    a = write_png(tmp_path / "a.png")
    b = write_png(tmp_path / "b.png", color=(0, 0, 255))
    out = tmp_path / "composite.png"

    png_b64 = base64.b64encode(png_bytes((16, 16))).decode("ascii")
    mock_image = MagicMock()
    mock_image.b64_json = png_b64
    mock_image.url = None
    success = MagicMock(data=[mock_image])

    mock_client = MagicMock()
    mock_client.images.edit.side_effect = [RuntimeError("gpt-image-1.5 unavailable"), success]

    with patch("openai.OpenAI", return_value=mock_client):
        path, method = create_openai_composite([a, b], out, "blend")

    assert path == out
    assert method == FALLBACK_MODEL
    assert out.is_file()
    assert mock_client.images.edit.call_count == 2
    assert mock_client.images.edit.call_args_list[0].kwargs["model"] == PREFERRED_MODEL
    assert mock_client.images.edit.call_args_list[1].kwargs["model"] == FALLBACK_MODEL
    mock_client.images.generate.assert_not_called()


def test_fetch_failure_lists_candidate_paths(tmp_path: Path) -> None:
    tracks = ["Olivia Rodrigo:The Cure", "Illenium:Pray"]
    with (
        patch("huntingszn_cover.mashup.fetch_album_covers", return_value=[]),
        pytest.raises(MashupError, match="Candidate images fetched") as exc,
    ):
        run_mashup("The Cure x Pray", tracks, tmp_path)

    message = str(exc.value)
    assert "Olivia Rodrigo:The Cure" in message
    assert "Illenium:Pray" in message
    assert "--image" in message


def test_pick_without_picker_lists_fetched_candidates(tmp_path: Path) -> None:
    tracks = ["Olivia Rodrigo:The Cure", "Illenium:Pray"]
    cure = write_png(tmp_path / "cure.png")
    pray = write_png(tmp_path / "pray.png", color=(0, 255, 0))

    def fake_fetch(artist, title, output_dir, *, target_count, client):
        output_dir.mkdir(parents=True, exist_ok=True)
        src = cure if "Cure" in title else pray
        dest = output_dir / "cover_00.png"
        dest.write_bytes(src.read_bytes())
        return [_fetched(dest, 500, 500)]

    with (
        patch("huntingszn_cover.mashup.fetch_album_covers", side_effect=fake_fetch),
        pytest.raises(MashupError, match="--pick") as exc,
    ):
        run_mashup("The Cure x Pray", tracks, tmp_path, auto=False)

    message = str(exc.value)
    assert "cover_00.png" in message
    assert "--image" in message


def test_pick_with_picker_uses_selected_covers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    tracks = ["Olivia Rodrigo:The Cure", "Illenium:Pray"]
    picked: list[str] = []

    def fake_fetch(artist, title, output_dir, *, target_count, client):
        output_dir.mkdir(parents=True, exist_ok=True)
        dest = output_dir / "cover_00.png"
        write_png(dest)
        return [_fetched(dest, 500, 500)]

    def picker(track: str, images: list[FetchedImage]) -> FetchedImage | None:
        picked.append(track)
        return images[0]

    png_b64 = base64.b64encode(png_bytes((16, 16))).decode("ascii")
    mock_image = MagicMock()
    mock_image.b64_json = png_b64
    mock_image.url = None
    mock_client = MagicMock()
    mock_client.images.edit.return_value = MagicMock(data=[mock_image])

    with (
        patch("huntingszn_cover.mashup.fetch_album_covers", side_effect=fake_fetch),
        patch("openai.OpenAI", return_value=mock_client),
        patch("huntingszn_cover.mashup.get_prompt", side_effect=lambda name: f"HUNTINGSZN EDIT {name}"),
    ):
        manifest = run_mashup("The Cure x Pray", tracks, tmp_path, auto=False, picker=picker)

    assert picked == tracks
    assert manifest.composite_path
    assert manifest.composite_method == PREFERRED_MODEL
    assert Path(manifest.composite_path).is_file()
    mock_client.images.generate.assert_not_called()
    image_arg = mock_client.images.edit.call_args_list[0].kwargs["image"]
    assert isinstance(image_arg, list)
    assert all(part[2] == "image/png" for part in image_arg)
    manifest_json = json.loads((tmp_path / "the-cure-x-pray" / "manifest.json").read_text())
    assert manifest_json["composite_method"] == PREFERRED_MODEL


def test_pick_transforms_selected_cover_not_auto_best(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--pick must reuse the chosen cover for per-track transforms, not re-select squarest."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    tracks = ["Olivia Rodrigo:The Cure", "Illenium:Pray"]
    composite_sources: list[Path] = []
    transform_sources: list[Path] = []

    def fake_fetch(artist, title, output_dir, *, target_count, client):
        output_dir.mkdir(parents=True, exist_ok=True)
        square = output_dir / "cover_00.png"
        picked = output_dir / "cover_01.png"
        write_png(square, (1000, 1000), (255, 0, 0))
        write_png(picked, (400, 400), (0, 255, 0))
        return [_fetched(square, 1000, 1000), _fetched(picked, 400, 400)]

    def picker(track: str, images: list[FetchedImage]) -> FetchedImage | None:
        return images[1]

    def fake_composite(images, output_path, prompt, **kwargs):
        composite_sources.extend(images)
        write_png(output_path, (16, 16))
        return output_path, PREFERRED_MODEL

    def fake_transform(image_path, prompt, output_path, **kwargs):
        transform_sources.append(image_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_png(output_path, (16, 16))
        return TransformResult(image_path, output_path, "clean", PREFERRED_MODEL)

    with (
        patch("huntingszn_cover.mashup.fetch_album_covers", side_effect=fake_fetch),
        patch("huntingszn_cover.mashup.create_openai_composite", side_effect=fake_composite),
        patch("huntingszn_cover.mashup.transform_image", side_effect=fake_transform),
        patch("huntingszn_cover.mashup.get_prompt", side_effect=lambda name: f"HUNTINGSZN EDIT {name}"),
    ):
        run_mashup("The Cure x Pray", tracks, tmp_path, auto=False, picker=picker)

    assert [p.name for p in composite_sources[:2]] == ["cover_01.png", "cover_01.png"]
    track_sources = [p for p in transform_sources if p.name.startswith("cover_")]
    assert track_sources
    assert all(p.name == "cover_01.png" for p in track_sources)


def test_run_mashup_does_not_pillow_split_when_edit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    tracks = ["Olivia Rodrigo:The Cure", "Illenium:Pray"]

    def fake_fetch(artist, title, output_dir, *, target_count, client):
        output_dir.mkdir(parents=True, exist_ok=True)
        dest = output_dir / "cover_00.png"
        write_png(dest)
        return [_fetched(dest, 500, 500)]

    mock_client = MagicMock()
    mock_client.images.edit.side_effect = RuntimeError("api down")

    with (
        patch("huntingszn_cover.mashup.fetch_album_covers", side_effect=fake_fetch),
        patch("openai.OpenAI", return_value=mock_client),
        patch("huntingszn_cover.mashup.get_prompt", side_effect=lambda name: f"HUNTINGSZN EDIT {name}"),
        pytest.raises(MashupError, match="Image edit failed"),
    ):
        run_mashup("The Cure x Pray", tracks, tmp_path)

    mashup_dir = tmp_path / "the-cure-x-pray"
    assert not (mashup_dir / "the-cure-x-pray-composite.png").exists()
    mock_client.images.generate.assert_not_called()


def test_mashup_cli_default_output_is_not_workspace_path() -> None:
    output_opt = next(p for p in mashup_cmd.params if p.name == "output")
    assert "/workspace" not in str(output_opt.default)
    assert Path(output_opt.default) == Path("./covers")

    result = CliRunner().invoke(cli, ["mashup", "--help"])
    assert result.exit_code == 0
    assert "/workspace/" not in result.output

