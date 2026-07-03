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


def test_parenthetical_remix_not_doubled():
    info = parse_song_info("Djo - End of Beginning (Vandelux Remix) 6.0.mp3")
    assert info is not None
    assert info["title"] == "End Of Beginning (Vandelux Remix) 6.0"
    assert "((" not in info["title"]


def test_final_after_paren_stripped():
    info = parse_song_info("Drake - STFU Janice (SPOONE Flip)Final.mp3")
    assert info is not None
    assert info["title"] == "STFU Janice (SPOONE Flip)"


def test_parenthetical_flip_with_final():
    info = parse_song_info("Better and the Moonrocks - Freakin Out (Spoone Flip) Final.mp3")
    assert info is not None
    assert info["title"] == "Freakin Out (Spoone Flip)"


def test_free_dl_stripped():
    info = parse_song_info("Artist - Song Name (FREE DL).mp3")
    assert info is not None
    assert info["title"] == "Song Name"
    info = parse_song_info("Artist - Song Name FREE DL.mp3")
    assert info is not None
    assert info["title"] == "Song Name"


def test_known_artist_kept_on_parenthetical_flip():
    from library_tools.pn_filename import sanitize_stem

    filename = "Kendrick Lamar - Bitch, Don't Kill My Vibe (Mersiv Flip).mp3"
    stem = sanitize_stem(filename[:-4], flip_style=True)
    info = parse_song_info(stem + ".mp3")
    assert stem.startswith("Kendrick Lamar - ")
    assert info is not None
    assert info["title"] == "Bitch, Don't Kill My Vibe (Mersiv Flip)"
    assert "Kendrick Lamar" in info["contributing_artists"]


def test_no_artist_separator_leaves_artist_empty():
    info = parse_song_info("Don't Stop the Music (NGHTMRE Remix) [DnB].mp3")
    assert info is not None
    assert info["title"] == "Don't Stop The Music (NGHTMRE Remix)"
    assert info["contributing_artists"] == []

    info = parse_song_info("Where Have You Been x Pressure x Thrash (RAFAEL Edit) 5A 145.mp3")
    assert info is not None
    assert info["title"] == "Where Have You Been X Pressure X Thrash (RAFAEL Edit)"
    assert info["contributing_artists"] == []
