"""Tests for folder-aware filename metadata."""

from pathlib import Path

from library_tools.metadata import (
    MODE_DASH,
    MODE_TITLE_KEEP_ARTIST,
    desired_from_stem,
    format_existing_artist,
    infer_mode,
    parse_song_info,
    process_folder,
)
from mutagen.easyid3 import EasyID3


def test_infer_mode_from_folder_name():
    root = Path("/music/Platnium Notes")
    assert infer_mode(root / "make it bump" / "track.mp3", root) == MODE_DASH
    assert infer_mode(root / "spotify" / "track.mp3", root) == MODE_DASH
    assert infer_mode(root / "huntingszn" / "track.mp3", root) == MODE_TITLE_KEEP_ARTIST
    assert infer_mode(root / "track.mp3", root) == MODE_DASH
    # Volume name HuntingSzn must not trigger huntingszn mode.
    vol = Path("/Volumes/HuntingSzn/Platnium Notes")
    assert infer_mode(vol / "spotify" / "track.mp3", vol) == MODE_DASH


def test_make_it_bump_keeps_collab_and_title_literally():
    stem = (
        "LMFAO x Alex Razo x TYNAN x Stray Kids - "
        "Party Rock Anthem x Ceremony (Make it Bump Mashup)"
    )
    title, artist = desired_from_stem(stem, MODE_DASH)
    assert artist == "LMFAO x Alex Razo x TYNAN x Stray Kids"
    assert title == "Party Rock Anthem x Ceremony (Make it Bump Mashup)"


def test_first_dash_only_in_title():
    title, artist = desired_from_stem("Artist - Song - Extra", MODE_DASH)
    assert artist == "Artist"
    assert title == "Song - Extra"


def test_vs_in_title_is_not_parsed():
    title, artist = desired_from_stem(
        "Ariana Grande vs. Riot - Break Free vs. Down With Your Love (Make it Bump Mashup)",
        MODE_DASH,
    )
    assert artist == "Ariana Grande vs. Riot"
    assert title == "Break Free vs. Down With Your Love (Make it Bump Mashup)"


def test_huntingszn_title_is_whole_filename():
    stem = "Beautiful Soul x Lonely [HuntingSzn Edit]"
    title, artist = desired_from_stem(stem, MODE_TITLE_KEEP_ARTIST)
    assert title == stem
    assert artist is None


def test_spotify_title_only_does_not_invent_artist():
    title, artist = desired_from_stem("A Better World", MODE_DASH)
    assert title == "A Better World"
    assert artist is None


def test_pn_suffix_stripped():
    title, artist = desired_from_stem("Artist - Title_PN", MODE_DASH)
    assert title == "Title"
    assert artist == "Artist"


def test_parse_song_info_does_not_title_case_or_split():
    info = parse_song_info(
        "Illenium x Dabin x Said the Sky - In My Arms (Make it Bump x Miscliqued Intro Edit).mp3"
    )
    assert info["title"] == "In My Arms (Make it Bump x Miscliqued Intro Edit)"
    assert info["contributing_artists"] == ["Illenium x Dabin x Said the Sky"]


def test_format_slash_joined_artist():
    assert (
        format_existing_artist("Taylor Swift/Virtual Riot")
        == "Taylor Swift x Virtual Riot"
    )
    assert format_existing_artist("Illenium x Jesse McCartney") == (
        "Illenium x Jesse McCartney"
    )


def _tiny_mp3(path: Path) -> None:
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
    audio = EasyID3()
    audio.save(path)


def test_process_folder_skips_appledouble_and_matches_filename(tmp_path: Path):
    bump = tmp_path / "make it bump"
    bump.mkdir()
    track = bump / (
        "LMFAO x Alex Razo x TYNAN x Stray Kids - "
        "Party Rock Anthem x Ceremony (Make it Bump Mashup).mp3"
    )
    sidecar = bump / ("._" + track.name)
    _tiny_mp3(track)
    sidecar.write_bytes(b"not audio")

    audio = EasyID3(track)
    audio["title"] = "wrong"
    audio["artist"] = "LMFAO"
    audio.save(track)

    process_folder(tmp_path, force=False, dry_run=False)

    tagged = EasyID3(track)
    assert tagged["title"] == ["Party Rock Anthem x Ceremony (Make it Bump Mashup)"]
    assert tagged["artist"] == ["LMFAO x Alex Razo x TYNAN x Stray Kids"]


def test_process_folder_huntingszn_keeps_formatted_artist(tmp_path: Path):
    folder = tmp_path / "huntingszn"
    folder.mkdir()
    track = folder / "Beautiful Soul x Lonely [HuntingSzn Edit].mp3"
    _tiny_mp3(track)
    audio = EasyID3(track)
    audio["title"] = "Beautiful Soul x Lonely [HuntingSzn Mashup]"
    audio["artist"] = "Illenium/Jesse McCartney"
    audio.save(track)

    process_folder(tmp_path, force=False, dry_run=False)

    tagged = EasyID3(track)
    assert tagged["title"] == ["Beautiful Soul x Lonely [HuntingSzn Edit]"]
    assert tagged["artist"] == ["Illenium x Jesse McCartney"]


def test_process_folder_skips_when_already_matching(tmp_path: Path, capsys):
    folder = tmp_path / "spotify"
    folder.mkdir()
    track = folder / "Artist Name - Song Title.mp3"
    _tiny_mp3(track)
    audio = EasyID3(track)
    audio["title"] = "Song Title"
    audio["artist"] = "Artist Name"
    audio.save(track)

    process_folder(tmp_path, force=False, dry_run=False)
    out = capsys.readouterr().out
    assert "update:" not in out
    assert "already_ok=1" in out
