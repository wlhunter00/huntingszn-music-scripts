"""Tests for Spotify URL parsing, matching, filenames, and manifest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from downloads.metadata import (
    DownloadManifest,
    HistoryEntry,
    artist_title_filename,
    sanitize_filename,
)
from downloads.source_resolver import (
    SourceCandidate,
    normalize_text,
    resolve_source,
    score_candidate,
)
from downloads.spotify_api import TrackMeta, parse_spotify_ref, track_from_api


def test_parse_track_url():
    ref = parse_spotify_ref(
        "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl?si=abc"
    )
    assert ref.kind == "track"
    assert ref.id == "11dFghVXANMlKmJXsNCbNl"


def test_parse_playlist_intl_url():
    ref = parse_spotify_ref(
        "https://open.spotify.com/intl-en/playlist/37i9dQZF1DXcBWIGoYBM5M"
    )
    assert ref.kind == "playlist"
    assert ref.id == "37i9dQZF1DXcBWIGoYBM5M"


def test_parse_uri_and_bare_id():
    assert parse_spotify_ref("spotify:album:4aawyAB9wcqUwMPfGnXlsu").kind == "album"
    assert parse_spotify_ref("11dFghVXANMlKmJXsNCbNl").kind == "track"


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_spotify_ref("https://example.com/track/abc")


def test_track_from_api_normalizes():
    obj = {
        "id": "11dFghVXANMlKmJXsNCbNl",
        "uri": "spotify:track:11dFghVXANMlKmJXsNCbNl",
        "name": "Cut To The Feeling",
        "artists": [{"name": "Carly Rae Jepsen"}],
        "album": {
            "name": "Cut To The Feeling",
            "release_date": "2017-05-26",
            "images": [{"url": "https://example.com/c.jpg", "width": 640}],
        },
        "duration_ms": 207959,
        "explicit": False,
        "track_number": 1,
        "disc_number": 1,
        "external_ids": {"isrc": "USUM71703861"},
    }
    t = track_from_api(obj)
    assert t.primary_artist == "Carly Rae Jepsen"
    assert t.duration_s == pytest.approx(207.959)
    assert t.artwork_url.endswith("c.jpg")
    assert "Carly Rae Jepsen" in t.search_query


def test_sanitize_and_filename():
    assert ":" not in sanitize_filename('a:b/c|d?e*"')
    track = TrackMeta(
        id="x" * 22,
        uri="spotify:track:" + "x" * 22,
        name="Song/Title",
        artists=("A", "B"),
        album="Alb",
        duration_ms=1000,
        explicit=False,
        track_number=1,
        disc_number=1,
        release_date="2020",
        artwork_url=None,
    )
    name = artist_title_filename(track)
    assert name.startswith("A, B - SongTitle") or "Song" in name
    assert name.endswith(".mp3")


def test_score_prefers_duration_and_artist():
    track = TrackMeta(
        id="y" * 22,
        uri="spotify:track:" + "y" * 22,
        name="Mr. Brightside",
        artists=("The Killers",),
        album="Hot Fuss",
        duration_ms=222000,
        explicit=False,
        track_number=1,
        disc_number=1,
        release_date="2004",
        artwork_url=None,
    )
    good, _ = score_candidate(
        track,
        title="The Killers - Mr. Brightside (Official Audio)",
        uploader="The Killers",
        duration_s=222.0,
        source="youtube",
    )
    bad, _ = score_candidate(
        track,
        title="Mr. Brightside Karaoke Instrumental",
        uploader="Random",
        duration_s=400.0,
        source="youtube",
    )
    assert good > bad
    assert good >= 55


def test_score_penalizes_extra_remix_marker():
    track = TrackMeta(
        id="z" * 22,
        uri="spotify:track:" + "z" * 22,
        name="Levitating",
        artists=("Dua Lipa",),
        album="Future Nostalgia",
        duration_ms=203000,
        explicit=False,
        track_number=1,
        disc_number=1,
        release_date="2020",
        artwork_url=None,
    )
    clean, _ = score_candidate(
        track,
        title="Dua Lipa - Levitating",
        uploader="Dua Lipa",
        duration_s=203,
        source="youtube",
    )
    remix, _ = score_candidate(
        track,
        title="Dua Lipa - Levitating (Remix)",
        uploader="Dua Lipa",
        duration_s=203,
        source="youtube",
    )
    assert clean > remix


def test_resolve_rejects_low_score(monkeypatch):
    track = TrackMeta(
        id="a" * 22,
        uri="spotify:track:" + "a" * 22,
        name="Unique Song XYZ",
        artists=("Rare Artist QQ",),
        album="Alb",
        duration_ms=180000,
        explicit=False,
        track_number=1,
        disc_number=1,
        release_date=None,
        artwork_url=None,
    )
    weak = SourceCandidate(
        source="youtube",
        url="https://youtube.com/watch?v=1",
        title="Completely Different Track",
        uploader="Someone",
        duration_s=60,
        score=10,
        reason="test",
    )

    monkeypatch.setattr(
        "downloads.source_resolver.search_youtube",
        lambda *_a, **_k: [weak],
    )
    monkeypatch.setattr(
        "downloads.source_resolver.search_soundcloud",
        lambda *_a, **_k: [],
    )
    result = resolve_source(track, source="youtube", min_score=55)
    assert result.candidate is None
    assert result.error and "below threshold" in result.error


def test_manifest_resume(tmp_path: Path):
    path = tmp_path / "sp-dl-history.json"
    m = DownloadManifest(path)
    out = tmp_path / "A - B.mp3"
    out.write_bytes(b"x")
    m.record(
        HistoryEntry(
            spotify_id="id1",
            title="B",
            artists="A",
            status="ok",
            output_path=str(out),
            confidence=90,
            source="youtube",
            source_url="https://example.com",
        )
    )
    m2 = DownloadManifest(path)
    assert m2.is_done("id1")
    assert not m2.is_done("missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["entries"][0]["spotify_id"] == "id1"


def test_normalize_text():
    assert normalize_text("  Foo-Bar!! ") == "foo bar"


def test_expand_inputs_dedupes(monkeypatch):
    from downloads import spotify_api

    track = TrackMeta(
        id="b" * 22,
        uri="spotify:track:" + "b" * 22,
        name="T",
        artists=("A",),
        album="Alb",
        duration_ms=1000,
        explicit=False,
        track_number=1,
        disc_number=1,
        release_date=None,
        artwork_url=None,
    )

    monkeypatch.setattr(
        spotify_api,
        "fetch_tracks_for_ref",
        lambda ref, **_k: [track],
    )
    out = spotify_api.expand_inputs(
        [
            "https://open.spotify.com/track/" + "b" * 22,
            "spotify:track:" + "b" * 22,
        ]
    )
    assert len(out) == 1


def test_cli_help():
    from downloads.spotify import main
    with patch("sys.argv", ["sp-dl", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
