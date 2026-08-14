"""Tests for tags module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from library_sync.tags import parse_filename_artist_title, read_tags
from mutagen.id3 import ID3, TBPM, TIT2, TKEY, TPE1


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
        assert tags.title == "fake"


class TestReadTagsExceptionHandling:
    """Test general exception handling in read_tags."""

    def test_returns_empty_on_mutagen_none(self, tmp_path: Path) -> None:
        """Verify read_tags returns empty TrackTags when MutagenFile returns None."""
        with patch("library_sync.tags.MutagenFile", return_value=None):
            tags = read_tags(tmp_path / "fake.mp3")
        assert tags.artist is None
        assert tags.title == "fake"
        assert tags.bpm is None

    def test_returns_empty_on_mutagen_exception(self, tmp_path: Path) -> None:
        """Verify read_tags falls back to filename when MutagenFile raises."""
        with patch("library_sync.tags.MutagenFile", side_effect=Exception("corrupt file")):
            tags = read_tags(tmp_path / "Artist - Song.mp3")
        assert tags.artist == "Artist"
        assert tags.title == "Song"


class TestFilenameFallback:
    def test_parse_artist_title(self) -> None:
        assert parse_filename_artist_title("Beyonce - Halo.mp3") == ("Beyonce", "Halo")
        assert parse_filename_artist_title("JustTitle.wav") == (None, "JustTitle")


class TestWavAiffId3:
    def test_reads_id3_from_wav(self, tmp_path: Path) -> None:
        id3 = ID3()
        id3.add(TPE1(encoding=3, text=["WAV Artist"]))
        id3.add(TIT2(encoding=3, text=["WAV Title"]))
        id3.add(TBPM(encoding=3, text=["128"]))
        id3.add(TKEY(encoding=3, text=["8A"]))

        fake_audio = MagicMock()
        fake_audio.tags = id3
        fake_audio.info = MagicMock()
        fake_audio.info.length = 12.0

        with patch("library_sync.tags.MutagenFile", return_value=fake_audio):
            with patch("library_sync.tags.MP3", new=type("FakeMP3", (), {})):
                tags = read_tags(tmp_path / "song.wav")

        assert tags.artist == "WAV Artist"
        assert tags.title == "WAV Title"
        assert tags.bpm == 128.0
        assert tags.camelot_key == "8A"
        assert tags.duration_sec == 12.0
