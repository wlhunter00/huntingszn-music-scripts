"""Tests for query module with harmonic mixing rules."""

import pytest
from library_sync.db import LibraryDB, Track, utc_now_iso
from library_sync.query import bpm_matches, query_tracks


class TestBpmMatches:
    def test_exact_match(self):
        assert bpm_matches(140, 140)
        assert bpm_matches(128, 128)

    def test_within_tolerance(self):
        assert bpm_matches(140, 134)  # -6
        assert bpm_matches(140, 146)  # +6
        assert not bpm_matches(140, 133)  # -7
        assert not bpm_matches(140, 147)  # +7

    def test_half_time(self):
        assert bpm_matches(140, 70)
        assert bpm_matches(140, 64)  # 70 - 6
        assert bpm_matches(140, 76)  # 70 + 6
        assert not bpm_matches(140, 63)  # 70 - 7

    def test_double_time(self):
        assert bpm_matches(70, 140)
        assert bpm_matches(70, 134)  # 140 - 6
        assert bpm_matches(70, 146)  # 140 + 6
        assert not bpm_matches(70, 133)  # 140 - 7

    def test_none_bpm(self):
        assert not bpm_matches(140, None)


class TestQueryTracks:
    @pytest.fixture
    def db_with_tracks(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        db = LibraryDB(db_path)
        db.connect()

        tracks = [
            ("8A", 140, "Artist1", "Song1"),
            ("8B", 140, "Artist2", "Song2"),
            ("7A", 135, "Artist3", "Song3"),
            ("9A", 145, "Artist4", "Song4"),
            ("5A", 128, "Artist5", "Halo"),
            ("8A", 70, "Artist6", "Half Time"),
            ("8A", 280, "Artist7", "Double Time"),
            ("8A", None, "Artist8", "No BPM"),
            (None, 140, "Artist9", "No Key"),
        ]

        for i, (camelot, bpm, artist, title) in enumerate(tracks):
            track = Track(
                id=f"id{i}",
                relative_path=f"DJ Music/{title}.mp3",
                filename=f"{title}.mp3",
                artist=artist,
                title=title,
                bpm=float(bpm) if bpm else None,
                camelot_key=camelot,
                file_size=1000,
                mtime=12345.0,
                audio_object_key=f"audio/DJ Music/{title}.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            db.upsert_track(track)

        yield db
        db.close()

    def test_camelot_compatible_keys(self, db_with_tracks):
        results = query_tracks(db_with_tracks, camelot="8A")
        camelot_keys = {t.camelot_key for t in results}
        assert "8A" in camelot_keys
        assert "8B" in camelot_keys
        assert "7A" in camelot_keys
        assert "9A" in camelot_keys
        assert "5A" not in camelot_keys
        titles = {t.title for t in results}
        assert "No Key" not in titles

    def test_invalid_camelot_returns_empty(self, db_with_tracks):
        assert query_tracks(db_with_tracks, camelot="not-a-key") == []

    def test_bpm_with_half_double(self, db_with_tracks):
        results = query_tracks(db_with_tracks, bpm=140)
        bpms = {t.bpm for t in results if t.bpm}
        assert 140 in bpms
        assert 135 in bpms  # within ±6
        assert 145 in bpms  # within ±6
        assert 70 in bpms  # half time
        assert 280 in bpms  # double time
        assert 128 not in bpms

    def test_combined_camelot_and_bpm(self, db_with_tracks):
        results = query_tracks(db_with_tracks, camelot="8A", bpm=140)
        assert len(results) > 0
        titles = {t.title for t in results}
        assert "Song1" in titles  # 8A @ 140
        assert "Song2" in titles  # 8B relative @ 140
        assert "Song3" in titles  # 7A ±1 @ 135
        assert "Song4" in titles  # 9A ±1 @ 145
        assert "Half Time" in titles  # 8A @ 70 (0.5×)
        assert "Double Time" in titles  # 8A @ 280 (2×)
        assert "Halo" not in titles  # 5A @ 128
        assert "No BPM" not in titles
        assert "No Key" not in titles
        for t in results:
            assert t.camelot_key in {"8A", "8B", "7A", "9A"}
            if t.bpm:
                assert bpm_matches(140, t.bpm)

    def test_matches_camelot_key_column_not_key(self, db_with_tracks):
        """Production rows have camelot_key populated and key almost empty.

        A decoy in `key` must not match; only camelot_key ±1 / relative does.
        """
        db_with_tracks.upsert_track(
            Track(
                id="key-only",
                relative_path="DJ Music/key-only.mp3",
                filename="key-only.mp3",
                artist="Decoy",
                title="Key Only",
                bpm=140.0,
                key="8A",
                camelot_key=None,
                file_size=1000,
                mtime=12345.0,
                audio_object_key="DJ Music/key-only.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )
        db_with_tracks.upsert_track(
            Track(
                id="camelot-only",
                relative_path="DJ Music/camelot-only.mp3",
                filename="camelot-only.mp3",
                artist="Real",
                title="Camelot Only",
                bpm=140.0,
                key=None,
                camelot_key="8A",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="DJ Music/camelot-only.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )
        db_with_tracks.upsert_track(
            Track(
                id="wrong-camelot",
                relative_path="DJ Music/wrong-camelot.mp3",
                filename="wrong-camelot.mp3",
                artist="Wrong",
                title="Musical Key Decoy",
                bpm=140.0,
                key="A minor",
                camelot_key="5A",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="DJ Music/wrong-camelot.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
        )

        sqls: list[str] = []
        db_with_tracks.connect().set_trace_callback(sqls.append)
        results = query_tracks(db_with_tracks, camelot="8A")
        titles = {t.title for t in results}
        assert "Camelot Only" in titles
        assert "Key Only" not in titles
        assert "Musical Key Decoy" not in titles

        select_sql = "\n".join(s for s in sqls if s.lstrip().upper().startswith("SELECT"))
        assert "camelot_key IN" in select_sql
        assert " key IN" not in select_sql
        assert "key =" not in select_sql.replace("camelot_key", "")

    def test_text_search(self, db_with_tracks):
        results = query_tracks(db_with_tracks, text_search="halo")
        assert len(results) == 1
        assert results[0].title == "Halo"

    def test_null_bpm_excluded(self, db_with_tracks):
        results = query_tracks(db_with_tracks, bpm=140)
        for t in results:
            assert t.bpm is not None

    def test_limit(self, db_with_tracks):
        results = query_tracks(db_with_tracks, limit=2)
        assert len(results) == 2

    def test_open_key_query(self, db_with_tracks):
        results = query_tracks(db_with_tracks, camelot="1m")
        camelot_keys = {t.camelot_key for t in results}
        assert "8A" in camelot_keys
        assert "5A" not in camelot_keys
