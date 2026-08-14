"""Tests for duplicate detection helpers."""

import os
from pathlib import Path

from library_tools.duplicate import (
    DuplicateCandidate,
    SongTags,
    _primary_reason,
    base_title,
    choose_keep,
    choose_keep_pair,
    consolidate_candidates,
    extract_version_signature,
    format_song_label,
    normalize_token,
    tags_match_exact,
    tags_match_fuzzy,
    tracks_are_duplicates,
)


def _set_mtime(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_normalize_token_strips_noise():
    assert normalize_token("  Song!!!  ") == "song"
    assert normalize_token("Artist Name") == "artist name"


def test_base_title_strips_brackets_but_keeps_feat_in_parens():
    assert base_title("Good Things Fall Apart (with Jon Bellion)") == "good things fall apart"
    assert (
        base_title("Good Things Fall Apart (with Jon Bellion) [Tiësto Remix]")
        == "good things fall apart"
    )


def test_extract_version_signature_detects_remix():
    assert extract_version_signature("Song [Tiësto Remix]").endswith("remix")
    assert extract_version_signature("Song (with Artist)") == ""


def test_tags_match_exact_ignores_case_and_punctuation():
    left = SongTags(artist="The Weeknd", title="Blinding Lights")
    right = SongTags(artist="the weeknd", title="blinding lights")
    left_path = Path("Blinding Lights.flac")
    right_path = Path("The Weeknd - Blinding Lights.mp3")
    assert tags_match_exact(left, right, left_path=left_path, right_path=right_path)


def test_tags_match_fuzzy_allows_small_differences():
    left = SongTags(artist="Kendrick Lamar", title="HUMBLE.")
    right = SongTags(artist="Kendrick Lamar", title="Humble")
    left_path = Path("HUMBLE..flac")
    right_path = Path("HUMBLE.mp3")
    assert tags_match_fuzzy(
        left, right, left_path=left_path, right_path=right_path, threshold=0.85
    )


def test_tags_match_fuzzy_rejects_different_songs():
    left = SongTags(artist="Artist A", title="Song One")
    right = SongTags(artist="Artist B", title="Song Two")
    left_path = Path("Song One.flac")
    right_path = Path("Song Two.flac")
    assert not tags_match_fuzzy(
        left, right, left_path=left_path, right_path=right_path, threshold=0.85
    )


def test_original_and_remix_are_not_duplicates(tmp_path: Path):
    original = tmp_path / "Good Things Fall Apart (with Jon Bellion).flac"
    remix = tmp_path / "Good Things Fall Apart (with Jon Bellion) [Tiësto Remix].flac"
    original_tags = SongTags(
        artist="ILLENIUM, Jon Bellion",
        title="Good Things Fall Apart (with Jon Bellion)",
    )
    remix_tags = SongTags(
        artist="ILLENIUM, Jon Bellion, Tiësto",
        title="Good Things Fall Apart (with Jon Bellion) [Tiësto Remix]",
    )
    cache = {original: original_tags, remix: remix_tags}
    assert not tracks_are_duplicates(original, remix, cache, threshold=0.85)


def test_different_remixes_are_not_duplicates(tmp_path: Path):
    a = tmp_path / "Song [Alesso Remix].flac"
    b = tmp_path / "Song [Don Diablo Remix].flac"
    tags_a = SongTags(artist="Artist", title="Song [Alesso Remix]")
    tags_b = SongTags(artist="Artist", title="Song [Don Diablo Remix]")
    cache = {a: tags_a, b: tags_b}
    assert not tracks_are_duplicates(a, b, cache, threshold=0.85)


def test_primary_reason_prefers_exact_over_fuzzy():
    assert _primary_reason({"metadata-exact", "metadata-fuzzy"}) == "metadata-exact"
    assert _primary_reason({"metadata-fuzzy"}) == "metadata-fuzzy"
    assert _primary_reason({"filename-extension", "metadata-exact"}) == "metadata-exact"


def test_consolidate_candidates_keeps_oldest_file(tmp_path: Path):
    older = tmp_path / "Song.flac"
    newer = tmp_path / "Artist - Song.mp3"
    older.touch()
    newer.touch()
    _set_mtime(older, 1_000.0)
    _set_mtime(newer, 2_000.0)

    candidates = [
        DuplicateCandidate(keep=newer, dup=older, reason="metadata-fuzzy"),
        DuplicateCandidate(keep=older, dup=newer, reason="metadata-exact"),
    ]
    consolidated = consolidate_candidates(candidates)
    assert len(consolidated) == 1
    assert consolidated[0].keep == older
    assert consolidated[0].dup == newer


def test_format_song_label_includes_version(tmp_path: Path):
    path = tmp_path / "Song [Alesso Remix].flac"
    tags = SongTags(artist="Artist", title="Song [Alesso Remix]")
    cache = {path: tags}
    label = format_song_label(path, cache)
    assert label is not None
    assert "Artist - Song" in label
    assert "version: alesso remix" in label


def test_choose_keep_prefers_older_file(tmp_path: Path):
    older = tmp_path / "Song.flac"
    newer = tmp_path / "Song.mp3"
    older.touch()
    newer.touch()
    _set_mtime(older, 1_000.0)
    _set_mtime(newer, 2_000.0)
    assert choose_keep([newer, older]) == older


def test_choose_keep_pair_returns_newer_as_dup(tmp_path: Path):
    older = tmp_path / "Song.flac"
    newer = tmp_path / "Song.mp3"
    older.touch()
    newer.touch()
    _set_mtime(older, 1_000.0)
    _set_mtime(newer, 2_000.0)
    keep, dup = choose_keep_pair(newer, older)
    assert keep == older
    assert dup == newer
