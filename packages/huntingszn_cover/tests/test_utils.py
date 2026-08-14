"""Tests for utility functions."""

import pytest

from huntingszn_cover.utils import parse_track, slugify, track_slug


class TestSlugify:
    """Tests for slugify function."""

    def test_basic_slugify(self) -> None:
        assert slugify("The Cure x Pray") == "the-cure-x-pray"

    def test_colon_conversion(self) -> None:
        assert slugify("Olivia Rodrigo: The Cure") == "olivia-rodrigo-the-cure"

    def test_special_characters(self) -> None:
        assert slugify("Artist (feat. Other)") == "artist-feat-other"

    def test_multiple_spaces(self) -> None:
        assert slugify("Track   With   Spaces") == "track-with-spaces"

    def test_unicode_normalization(self) -> None:
        assert slugify("Café Résumé") == "cafe-resume"

    def test_empty_string(self) -> None:
        assert slugify("") == ""

    def test_only_special_chars(self) -> None:
        assert slugify("!!!@@@###") == ""


class TestTrackSlug:
    """Tests for track_slug function."""

    def test_artist_title_format(self) -> None:
        assert track_slug("Olivia Rodrigo:The Cure") == "olivia-rodrigo-the-cure"

    def test_with_spaces(self) -> None:
        assert track_slug("Illenium:Pray") == "illenium-pray"


class TestParseTrack:
    """Tests for parse_track function."""

    def test_valid_format(self) -> None:
        artist, title = parse_track("Olivia Rodrigo:The Cure")
        assert artist == "Olivia Rodrigo"
        assert title == "The Cure"

    def test_with_spaces(self) -> None:
        artist, title = parse_track("  Artist Name  :  Song Title  ")
        assert artist == "Artist Name"
        assert title == "Song Title"

    def test_missing_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="must be in 'Artist:Title' format"):
            parse_track("No Colon Here")

    def test_empty_artist_raises(self) -> None:
        with pytest.raises(ValueError, match="must be non-empty"):
            parse_track(":Title Only")

    def test_empty_title_raises(self) -> None:
        with pytest.raises(ValueError, match="must be non-empty"):
            parse_track("Artist Only:")
