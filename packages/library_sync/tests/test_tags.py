"""Tests for tags module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from library_sync.tags import read_tags


class RaisingDict(dict):
    """A dict-like mapping whose .get() raises ValueError for certain keys."""

    def __init__(self, raise_keys: set[str]):
        super().__init__()
        self._raise_keys = raise_keys

    def get(self, key, default=None):
        if key in self._raise_keys:
            raise ValueError(f"Simulated mutagen ValueError for key: {key}")
        return super().get(key, default)


class TestGetTagValueError:
    """Test that get_tag handles ValueError from mutagen gracefully."""

    def test_get_tag_catches_valueerror(self, tmp_path: Path) -> None:
        """Verify ValueError from audio_tags.get() does not crash read_tags."""
        fake_audio = MagicMock()
        fake_audio.tags = RaisingDict(raise_keys={"album", "ALBUM", "\xa9alb", "TALB"})
        fake_audio.tags["artist"] = ["Test Artist"]
        fake_audio.tags["title"] = ["Test Title"]
        fake_audio.info = MagicMock()
        fake_audio.info.length = 180.5

        with patch("library_sync.tags.MutagenFile", return_value=fake_audio):
            with patch("library_sync.tags.MP3", new=type("FakeMP3", (), {})):
                tags = read_tags(tmp_path / "fake.flac")

        assert tags.artist == "Test Artist"
        assert tags.title == "Test Title"
        assert tags.album is None
        assert tags.duration_sec == 180.5

    def test_get_tag_continues_after_valueerror(self, tmp_path: Path) -> None:
        """Verify that if one key raises, later keys are still checked."""
        fake_audio = MagicMock()
        fake_tags = RaisingDict(raise_keys={"artist"})
        fake_tags["ARTIST"] = ["Fallback Artist"]
        fake_audio.tags = fake_tags
        fake_audio.info = None

        with patch("library_sync.tags.MutagenFile", return_value=fake_audio):
            with patch("library_sync.tags.MP3", new=type("FakeMP3", (), {})):
                tags = read_tags(tmp_path / "fake.flac")

        assert tags.artist == "Fallback Artist"

    def test_get_tag_all_keys_raise(self, tmp_path: Path) -> None:
        """Verify that if all keys raise, result is None (not crash)."""
        fake_audio = MagicMock()
        fake_audio.tags = RaisingDict(
            raise_keys={"artist", "ARTIST", "\xa9ART", "TPE1", "title", "TITLE", "\xa9nam", "TIT2"}
        )
        fake_audio.info = None

        with patch("library_sync.tags.MutagenFile", return_value=fake_audio):
            with patch("library_sync.tags.MP3", new=type("FakeMP3", (), {})):
                tags = read_tags(tmp_path / "fake.flac")

        assert tags.artist is None
        assert tags.title is None


class TestReadTagsExceptionHandling:
    """Test general exception handling in read_tags."""

    def test_returns_empty_on_mutagen_none(self, tmp_path: Path) -> None:
        """Verify read_tags returns empty TrackTags when MutagenFile returns None."""
        with patch("library_sync.tags.MutagenFile", return_value=None):
            tags = read_tags(tmp_path / "fake.mp3")
        assert tags.artist is None
        assert tags.title is None
        assert tags.bpm is None

    def test_returns_empty_on_mutagen_exception(self, tmp_path: Path) -> None:
        """Verify read_tags returns empty TrackTags when MutagenFile raises."""
        with patch("library_sync.tags.MutagenFile", side_effect=Exception("corrupt file")):
            tags = read_tags(tmp_path / "fake.mp3")
        assert tags.artist is None
        assert tags.title is None
