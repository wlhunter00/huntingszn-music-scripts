"""Tests for filename metadata parsing."""

from library_tools.metadata import parse_song_info


def test_known_artist_not_split():
    info = parse_song_info("Kendrick Lamar - Humble.mp3")
    assert info is not None
    assert info["title"] == "Humble"
    assert "Kendrick Lamar" in info["contributing_artists"]


def test_feat_in_title():
    info = parse_song_info("Drake - God's Plan feat Another Artist.mp3")
    assert info is not None
    assert "Another Artist" in info["contributing_artists"]


def test_remix_in_title():
    info = parse_song_info("Artist - Song Name Flip.mp3")
    assert info is not None
    assert "Flip" in info["title"]


def test_evaluation_edits():
    info = parse_song_info("Title (Evalution Mix) - Artist One vs Artist Two.mp3")
    assert info is not None
    assert "Evalution" in info["title"]
    assert len(info["contributing_artists"]) >= 1


def test_pn_suffix_stripped():
    info = parse_song_info("Artist - Title_PN.mp3")
    assert info is not None
    assert info["title"] == "Title"


def test_bpm_stripped_from_title():
    info = parse_song_info("Artist - My Song Bb 145.mp3")
    assert info is not None
    assert info["title"] == "My Song"


def test_label_brackets_stripped():
    info = parse_song_info("Artist - My Song [Some Label].mp3")
    assert info is not None
    assert info["title"] == "My Song"
