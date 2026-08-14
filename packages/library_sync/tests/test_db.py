"""Tests for SQLite database operations."""


from library_sync.db import LibraryDB, Track, compute_track_id, utc_now_iso


def test_compute_track_id():
    id1 = compute_track_id("DJ Music/song.mp3", 1000)
    id2 = compute_track_id("DJ Music/song.mp3", 1000)
    id3 = compute_track_id("DJ Music/song.mp3", 1001)
    id4 = compute_track_id("DJ Music/other.mp3", 1000)

    assert id1 == id2
    assert id1 != id3
    assert id1 != id4


def test_utc_now_iso():
    ts = utc_now_iso()
    assert "T" in ts
    assert "+" in ts or "Z" in ts or ts.endswith("+00:00")


class TestLibraryDB:
    def test_create_and_upsert(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            track = Track(
                id="abc123",
                relative_path="DJ Music/test.mp3",
                filename="test.mp3",
                artist="Test Artist",
                title="Test Title",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="audio/DJ Music/test.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            db.upsert_track(track)

            retrieved = db.get_track_by_path("DJ Music/test.mp3")
            assert retrieved is not None
            assert retrieved.artist == "Test Artist"
            assert retrieved.title == "Test Title"

    def test_update_check(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            track = Track(
                id="abc123",
                relative_path="DJ Music/test.mp3",
                filename="test.mp3",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="audio/DJ Music/test.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            db.upsert_track(track)

            size, mtime = db.get_track_for_update_check("DJ Music/test.mp3")
            assert size == 1000
            assert mtime == 12345.0

            size, mtime = db.get_track_for_update_check("nonexistent.mp3")
            assert size is None
            assert mtime is None

    def test_mark_missing(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            for i in range(3):
                track = Track(
                    id=f"id{i}",
                    relative_path=f"DJ Music/song{i}.mp3",
                    filename=f"song{i}.mp3",
                    file_size=1000,
                    mtime=12345.0,
                    audio_object_key=f"audio/DJ Music/song{i}.mp3",
                    updated_at=utc_now_iso(),
                    source_root="DJ Music",
                )
                db.upsert_track(track)

            count = db.mark_missing({"DJ Music/song0.mp3", "DJ Music/song1.mp3"})
            assert count == 2

            assert db.count_tracks(status="present") == 1
            assert db.count_tracks(status="missing") == 2

    def test_query_by_camelot(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            for camelot in ["8A", "8B", "7A", "9A", "5A"]:
                track = Track(
                    id=f"id_{camelot}",
                    relative_path=f"DJ Music/{camelot}.mp3",
                    filename=f"{camelot}.mp3",
                    camelot_key=camelot,
                    file_size=1000,
                    mtime=12345.0,
                    audio_object_key=f"audio/DJ Music/{camelot}.mp3",
                    updated_at=utc_now_iso(),
                    source_root="DJ Music",
                )
                db.upsert_track(track)

            results = db.query_tracks(camelot_keys={"8A", "8B", "7A", "9A"})
            assert len(results) == 4

            results = db.query_tracks(camelot_keys={"5A"})
            assert len(results) == 1

    def test_query_by_bpm_range(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            for bpm in [128, 140, 150, 175]:
                track = Track(
                    id=f"id_{bpm}",
                    relative_path=f"DJ Music/{bpm}.mp3",
                    filename=f"{bpm}.mp3",
                    bpm=float(bpm),
                    file_size=1000,
                    mtime=12345.0,
                    audio_object_key=f"audio/DJ Music/{bpm}.mp3",
                    updated_at=utc_now_iso(),
                    source_root="DJ Music",
                )
                db.upsert_track(track)

            results = db.query_tracks(bpm_range=(135, 145))
            assert len(results) == 1
            assert results[0].bpm == 140

    def test_query_text_search(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            track1 = Track(
                id="id1",
                relative_path="DJ Music/halo.mp3",
                filename="halo.mp3",
                artist="Beyonce",
                title="Halo",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="audio/DJ Music/halo.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            track2 = Track(
                id="id2",
                relative_path="DJ Music/other.mp3",
                filename="other.mp3",
                artist="Other",
                title="Other Song",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="audio/DJ Music/other.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            db.upsert_track(track1)
            db.upsert_track(track2)

            results = db.query_tracks(text_search="halo")
            assert len(results) == 1
            assert results[0].title == "Halo"

            results = db.query_tracks(text_search="HALO")
            assert len(results) == 1

    def test_posix_relative_path(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            track = Track(
                id="id1",
                relative_path="DJ Music/Spotify/song.mp3",
                filename="song.mp3",
                file_size=1000,
                mtime=12345.0,
                audio_object_key="audio/DJ Music/Spotify/song.mp3",
                updated_at=utc_now_iso(),
                source_root="DJ Music",
            )
            db.upsert_track(track)

            retrieved = db.get_track_by_path("DJ Music/Spotify/song.mp3")
            assert retrieved is not None
            assert "/" in retrieved.relative_path
            assert "\\" not in retrieved.relative_path

    def test_like_wildcards_are_literal(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            db.upsert_track(
                Track(
                    id="id1",
                    relative_path="DJ Music/100%.mp3",
                    filename="100%.mp3",
                    title="100%",
                    file_size=1,
                    mtime=1.0,
                    updated_at=utc_now_iso(),
                    source_root="DJ Music",
                )
            )
            db.upsert_track(
                Track(
                    id="id2",
                    relative_path="DJ Music/halo.mp3",
                    filename="halo.mp3",
                    title="Halo",
                    file_size=1,
                    mtime=1.0,
                    updated_at=utc_now_iso(),
                    source_root="DJ Music",
                )
            )
            results = db.query_tracks(text_search="100%")
            assert len(results) == 1
            assert results[0].title == "100%"

    def test_mark_missing_chunks(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        with LibraryDB(db_path) as db:
            paths = set()
            for i in range(12):
                rel = f"DJ Music/song{i}.mp3"
                paths.add(rel)
                db.upsert_track(
                    Track(
                        id=f"id{i}",
                        relative_path=rel,
                        filename=f"song{i}.mp3",
                        file_size=1,
                        mtime=1.0,
                        updated_at=utc_now_iso(),
                        source_root="DJ Music",
                    )
                )
            count = db.mark_missing(paths, chunk_size=5)
            assert count == 12
            assert db.count_tracks(status="missing") == 12
