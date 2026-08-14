"""Tests for fetch module with mocked SerpAPI responses."""

import traceback
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from huntingszn_cover.fetch import (
    SERPAPI_BASE_URL,
    FetchError,
    _get_serpapi_key,
    _is_duplicate,
    _is_roughly_square,
    fetch_album_covers,
    search_album_covers,
)


class TestIsSerpApiKeyRequired:
    """Tests for API key requirement."""

    def test_missing_key_raises(self) -> None:
        """Should raise FetchError when SERPAPI_API_KEY is not set."""
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(FetchError, match="SERPAPI_API_KEY"),
        ):
            _get_serpapi_key()

    def test_key_present(self) -> None:
        """Should return key when set."""
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key-123"}):
            key = _get_serpapi_key()
            assert key == "test-key-123"


class TestIsRoughlySquare:
    """Tests for square image detection."""

    def test_perfect_square(self) -> None:
        assert _is_roughly_square(500, 500) is True

    def test_within_tolerance(self) -> None:
        assert _is_roughly_square(500, 450) is True
        assert _is_roughly_square(450, 500) is True

    def test_outside_tolerance(self) -> None:
        assert _is_roughly_square(500, 300) is False
        assert _is_roughly_square(300, 500) is False

    def test_zero_dimension(self) -> None:
        assert _is_roughly_square(0, 500) is False
        assert _is_roughly_square(500, 0) is False


class TestIsDuplicate:
    """Tests for perceptual hash deduplication."""

    def test_identical_hashes(self) -> None:
        """Identical hashes should be detected as duplicates."""
        hash1 = "f8f8f8f8f8f8f8f8"
        existing = ["f8f8f8f8f8f8f8f8"]
        assert _is_duplicate(hash1, existing) is True

    def test_very_different_hashes(self) -> None:
        """Very different hashes should not be duplicates."""
        hash1 = "0000000000000000"
        existing = ["ffffffffffffffff"]
        assert _is_duplicate(hash1, existing) is False

    def test_empty_existing_list(self) -> None:
        """Empty existing list should never match."""
        hash1 = "f8f8f8f8f8f8f8f8"
        assert _is_duplicate(hash1, []) is False


class TestSearchAlbumCoversMocked:
    """Tests for SerpAPI search with mocked responses."""

    @pytest.fixture
    def mock_serpapi_response(self) -> dict:
        """Sample SerpAPI response."""
        return {
            "images_results": [
                {
                    "original": "https://example.com/cover1.jpg",
                    "thumbnail": "https://example.com/thumb1.jpg",
                    "title": "Album Cover 1",
                },
                {
                    "original": "https://example.com/cover2.jpg",
                    "thumbnail": "https://example.com/thumb2.jpg",
                    "title": "Album Cover 2",
                },
            ]
        }

    def test_search_returns_results(self, mock_serpapi_response: dict) -> None:
        """Should parse and return image results from mocked response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_serpapi_response
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            results = search_album_covers("Artist", "Title", client=mock_client)

            assert len(results) == 2
            assert results[0]["original"] == "https://example.com/cover1.jpg"
            mock_client.get.assert_called_once()
            mock_client.post.assert_not_called()
            _args, kwargs = mock_client.get.call_args
            assert _args[0] == SERPAPI_BASE_URL
            assert kwargs["params"]["engine"] == "google_images"
            assert kwargs["params"]["q"] == "Artist Title album cover square"
            assert kwargs["params"]["api_key"] == "test-key"
            assert kwargs["params"]["tbm"] == "isch"

    def test_search_handles_api_error(self) -> None:
        """Should raise FetchError on API error response."""
        error_response = {"error": "Invalid API key"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = error_response
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with (
            patch.dict("os.environ", {"SERPAPI_API_KEY": "bad-key"}),
            pytest.raises(FetchError, match="SerpAPI error"),
        ):
            search_album_covers("Artist", "Title", client=mock_client)

    def test_search_handles_empty_results(self) -> None:
        """Should return empty list when no results."""
        empty_response = {"images_results": []}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            results = search_album_covers("Unknown", "Track", client=mock_client)

            assert results == []


def _png_bytes(size: tuple[int, int], *, seed: int) -> bytes:
    """Patterned PNG so perceptual hashes differ across seeds (solid colors do not)."""
    img = Image.new("RGB", size)
    pixels = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            pixels[x, y] = ((x * seed) % 256, (y * (seed + 3)) % 256, (x + y + seed) % 256)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_search_http_error_does_not_leak_api_key() -> None:
    secret = "super-secret-serpapi-key"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        patch.dict("os.environ", {"SERPAPI_API_KEY": secret}),
        pytest.raises(FetchError, match="HTTP error during SerpAPI request: 401") as exc,
    ):
        search_album_covers("Artist", "Title", client=client)

    tb = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    assert seen and seen[0].method == "GET"
    assert secret in str(seen[0].url)
    assert secret not in str(exc.value)
    assert "api_key=" not in str(exc.value)
    assert secret not in tb
    assert "api_key=" not in tb
    assert exc.value.__cause__ is None


def test_search_connect_error_does_not_leak_api_key() -> None:
    secret = "super-secret-serpapi-key"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        patch.dict("os.environ", {"SERPAPI_API_KEY": secret}),
        pytest.raises(FetchError, match="HTTP error during SerpAPI request") as exc,
    ):
        search_album_covers("Artist", "Title", client=client)

    tb = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    assert secret not in str(exc.value)
    assert secret not in tb
    assert "api_key=" not in tb
    assert exc.value.__cause__ is None


def test_search_json_error_redacts_api_key() -> None:
    secret = "super-secret-serpapi-key"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": f"Invalid API key: {secret}"}
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.get.return_value = mock_response

    with (
        patch.dict("os.environ", {"SERPAPI_API_KEY": secret}),
        pytest.raises(FetchError, match="SerpAPI error") as exc,
    ):
        search_album_covers("Artist", "Title", client=mock_client)

    assert secret not in str(exc.value)
    assert "***" in str(exc.value)


def test_search_uses_get_google_images() -> None:
    """Live-compatible fetch: GET google_images with api_key as a query param."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"images_results": []}
    mock_response.raise_for_status.return_value = None
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response

    with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
        search_album_covers("Artist", "Title", client=mock_client)

    mock_client.post.assert_not_called()
    mock_client.get.assert_called_once()
    assert mock_client.get.call_args.args[0] == SERPAPI_BASE_URL
    params = mock_client.get.call_args.kwargs["params"]
    assert params["engine"] == "google_images"
    assert params["api_key"] == "test-key"


def test_fetch_album_covers_uses_google_images_saves_square_pngs(tmp_path: Path) -> None:
    square = _png_bytes((120, 120), seed=1)
    wide = _png_bytes((200, 80), seed=2)
    duplicate = _png_bytes((120, 120), seed=1)
    unique = _png_bytes((100, 100), seed=9)
    serpapi_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "serpapi.com" in url:
            serpapi_calls.append(request)
            return httpx.Response(
                200,
                json={
                    "images_results": [
                        {"original": "https://cdn.example.com/square.png"},
                        {"original": "https://cdn.example.com/wide.png"},
                        {"original": "https://cdn.example.com/dup.png"},
                        {"original": "https://cdn.example.com/unique.png"},
                    ]
                },
                request=request,
            )
        if url.endswith("wide.png"):
            return httpx.Response(200, content=wide, request=request)
        if url.endswith("dup.png"):
            return httpx.Response(200, content=duplicate, request=request)
        if url.endswith("unique.png"):
            return httpx.Response(200, content=unique, request=request)
        return httpx.Response(200, content=square, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
        fetched = fetch_album_covers(
            "Olivia Rodrigo", "The Cure", tmp_path, target_count=5, client=client
        )

    assert len(serpapi_calls) == 1
    req = serpapi_calls[0]
    assert req.method == "GET"
    params = req.url.params
    assert params["engine"] == "google_images"
    assert params["q"] == "Olivia Rodrigo The Cure album cover square"
    assert "google_images" in params["engine"]
    assert len(fetched) == 2
    assert fetched[0].local_path.is_file()
    assert fetched[1].local_path.is_file()
    assert Image.open(fetched[0].local_path).size == (120, 120)
    assert Image.open(fetched[1].local_path).size == (100, 100)
    names = {f.local_path.name for f in fetched}
    assert "cover_00.png" in names
    assert all(p.suffix == ".png" for p in [f.local_path for f in fetched])
