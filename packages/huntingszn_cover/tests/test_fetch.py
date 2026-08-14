"""Tests for fetch module with mocked SerpAPI responses."""

from unittest.mock import MagicMock, patch

import pytest

from huntingszn_cover.fetch import (
    FetchError,
    _get_serpapi_key,
    _is_duplicate,
    _is_roughly_square,
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
        mock_response.json.return_value = mock_serpapi_response
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            results = search_album_covers("Artist", "Title", client=mock_client)

            assert len(results) == 2
            assert results[0]["original"] == "https://example.com/cover1.jpg"
            mock_client.get.assert_called_once()
            _args, kwargs = mock_client.get.call_args
            assert kwargs["params"]["engine"] == "google_images"
            assert kwargs["params"]["q"] == "Artist Title album cover square"
            assert kwargs["params"]["api_key"] == "test-key"

    def test_search_handles_api_error(self) -> None:
        """Should raise FetchError on API error response."""
        error_response = {"error": "Invalid API key"}

        mock_response = MagicMock()
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
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            results = search_album_covers("Unknown", "Track", client=mock_client)

            assert results == []
