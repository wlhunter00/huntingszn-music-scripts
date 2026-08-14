"""Tests for indexing functionality."""

import os
from pathlib import Path

from library_sync.db import LibraryDB
from library_sync.index import (
    _is_audio_file,
    _should_skip_dir,
    _should_skip_file,
    _to_posix_relative,
    index_files,
    scan_directory,
)


class TestSkipPatterns:
    def test_skip_appledouble(self):
        assert _should_skip_file("._song.mp3")
        assert _should_skip_file("._anything")

    def test_skip_ds_store(self):
        assert _should_skip_file(".DS_Store")

    def test_normal_files_not_skipped(self):
        assert not _should_skip_file("song.mp3")
        assert not _should_skip_file("Artist - Title.wav")

    def test_skip_stem_output(self):
        assert _should_skip_dir("stem-output")

    def test_skip_production_dirs(self):
        assert _should_skip_dir("Producing Sounds")
        assert _should_skip_dir("Ableton")
        assert _should_skip_dir("Instruments")
        assert _should_skip_dir("serum presets")
        assert _should_skip_dir("serum")

    def test_skip_dirs_case_insensitive(self):
        assert _should_skip_dir("ABLETON")
        assert _should_skip_dir("Stem-Output")
        assert _should_skip_dir("Serum Presets")

    def test_index_dirs_not_skipped(self):
        assert not _should_skip_dir("DJ Music")
        assert not _should_skip_dir("Platnium Notes")
        assert not _should_skip_dir("Spotify")


class TestAudioExtensions:
    def test_supported_extensions(self):
        assert _is_audio_file(Path("song.mp3"))
        assert _is_audio_file(Path("song.wav"))
        assert _is_audio_file(Path("song.aiff"))
        assert _is_audio_file(Path("song.aif"))
        assert _is_audio_file(Path("song.flac"))
        assert _is_audio_file(Path("song.m4a"))

    def test_case_insensitive(self):
        assert _is_audio_file(Path("song.MP3"))
        assert _is_audio_file(Path("song.WAV"))
        assert _is_audio_file(Path("song.FLAC"))

    def test_unsupported_extensions(self):
        assert not _is_audio_file(Path("song.txt"))
        assert not _is_audio_file(Path("song.jpg"))
        assert not _is_audio_file(Path("song.als"))


class TestPosixPath:
    def test_converts_to_posix(self):
        root = Path("/drive")
        path = root / "DJ Music" / "Spotify" / "song.mp3"
        result = _to_posix_relative(path, root)
        assert result == "DJ Music/Spotify/song.mp3"
        assert "\\" not in result

    def test_nested_path(self):
        root = Path("/drive")
        path = root / "Platnium Notes" / "Artist" / "Song.mp3"
        result = _to_posix_relative(path, root)
        assert result == "Platnium Notes/Artist/Song.mp3"


class TestScanDirectory:
    def test_scans_audio_files(self, tmp_path):
        dj_music = tmp_path / "DJ Music" / "Spotify"
        dj_music.mkdir(parents=True)

        (dj_music / "song1.mp3").write_bytes(b"fake mp3")
        (dj_music / "song2.wav").write_bytes(b"fake wav")
        (dj_music / "readme.txt").write_bytes(b"text file")

        files = scan_directory(tmp_path / "DJ Music", tmp_path)
        paths = [f[1] for f in files]

        assert "DJ Music/Spotify/song1.mp3" in paths
        assert "DJ Music/Spotify/song2.wav" in paths
        assert "DJ Music/Spotify/readme.txt" not in paths

    def test_skips_stem_output(self, tmp_path):
        stem_output = tmp_path / "Stem Splitting" / "stem-output"
        stem_output.mkdir(parents=True)
        (stem_output / "vocals.mp3").write_bytes(b"fake mp3")

        files = scan_directory(tmp_path / "Stem Splitting", tmp_path)
        paths = [f[1] for f in files]

        assert len(paths) == 0

    def test_skips_appledouble(self, tmp_path):
        dj_music = tmp_path / "DJ Music"
        dj_music.mkdir(parents=True)

        (dj_music / "song.mp3").write_bytes(b"fake mp3")
        (dj_music / "._song.mp3").write_bytes(b"appledouble")
        (dj_music / ".DS_Store").write_bytes(b"ds store")

        files = scan_directory(dj_music, tmp_path)
        filenames = [Path(f[0]).name for f in files]

        assert "song.mp3" in filenames
        assert "._song.mp3" not in filenames
        assert ".DS_Store" not in filenames


class TestIndexFiles:
    def test_incremental_skip_unchanged(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        song_file = dj_music / "song.mp3"
        song_file.write_bytes(b"fake mp3 content")

        with LibraryDB(db_path) as db:
            stats1 = index_files(db, drive_root, [dj_music])
            assert stats1["added"] == 1
            assert stats1["skipped"] == 0

            stats2 = index_files(db, drive_root, [dj_music])
            assert stats2["added"] == 0
            assert stats2["skipped"] == 1

    def test_reindex_on_mtime_change(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        song_file = dj_music / "song.mp3"
        song_file.write_bytes(b"fake mp3 content")

        with LibraryDB(db_path) as db:
            stats1 = index_files(db, drive_root, [dj_music])
            assert stats1["added"] == 1

            song_file.write_bytes(b"modified mp3 content - different size")
            os.utime(song_file, (999999999, 999999999))

            stats2 = index_files(db, drive_root, [dj_music])
            assert stats2["updated"] == 1
            assert stats2["skipped"] == 0

    def test_dry_run_no_write(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        (dj_music / "song.mp3").write_bytes(b"fake mp3")

        with LibraryDB(db_path) as db:
            stats = index_files(db, drive_root, [dj_music], dry_run=True)
            assert stats["added"] == 1
            assert db.count_tracks() == 0

    def test_marks_missing(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)

        song1 = dj_music / "song1.mp3"
        song2 = dj_music / "song2.mp3"
        song1.write_bytes(b"fake mp3 1")
        song2.write_bytes(b"fake mp3 2")

        with LibraryDB(db_path) as db:
            index_files(db, drive_root, [dj_music])
            assert db.count_tracks(status="present") == 2

            song2.unlink()
            stats = index_files(db, drive_root, [dj_music])
            assert stats["missing"] == 1
            assert db.count_tracks(status="present") == 1
            assert db.count_tracks(status="missing") == 1

    def test_missing_root_does_not_mark_other_catalog_missing(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        platinum = drive_root / "Platnium Notes"
        dj_music.mkdir(parents=True)
        platinum.mkdir(parents=True)
        (dj_music / "dj.mp3").write_bytes(b"dj")
        (platinum / "pn.mp3").write_bytes(b"pn")

        with LibraryDB(db_path) as db:
            index_files(db, drive_root, [dj_music, platinum])
            assert db.count_tracks(status="present") == 2

            import shutil

            shutil.rmtree(platinum)
            stats = index_files(db, drive_root, [dj_music, platinum])
            assert stats["missing"] == 0
            paths = {t.relative_path: t.status for t in db.query_tracks(status="present")}
            assert "DJ Music/dj.mp3" in paths
            pn = db.get_track_by_path("Platnium Notes/pn.mp3")
            assert pn is not None
            assert pn.status == "present"

    def test_audio_object_key_is_bucket_relative_path(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)
        (dj_music / "song.mp3").write_bytes(b"fake")

        with LibraryDB(db_path) as db:
            index_files(db, drive_root, [dj_music])
            track = db.get_track_by_path("DJ Music/song.mp3")
            assert track is not None
            assert track.audio_object_key == "DJ Music/song.mp3"

    def test_infers_role_from_filename(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)
        (dj_music / "Artist - Song (Vocal Mix).mp3").write_bytes(b"v")
        (dj_music / "Artist - Song (Instrumental).mp3").write_bytes(b"i")
        (dj_music / "Artist - Song (No Vocals).mp3").write_bytes(b"n")
        (dj_music / "Artist - Song.mp3").write_bytes(b"s")

        with LibraryDB(db_path) as db:
            index_files(db, drive_root, [dj_music])
            roles = {
                t.filename: t.role
                for t in db.query_tracks()
            }
            assert roles["Artist - Song (Vocal Mix).mp3"] == "vocal"
            assert roles["Artist - Song (Instrumental).mp3"] == "drop"
            assert roles["Artist - Song (No Vocals).mp3"] == "drop"
            assert roles["Artist - Song.mp3"] == "unknown"

    def test_dry_run_does_not_create_db_file(self, tmp_path):
        db_path = tmp_path / "data" / "library.sqlite"
        drive_root = tmp_path / "drive"
        dj_music = drive_root / "DJ Music"
        dj_music.mkdir(parents=True)
        (dj_music / "song.mp3").write_bytes(b"fake")

        with LibraryDB(db_path, create=False) as db:
            index_files(db, drive_root, [dj_music], dry_run=True)

        assert not db_path.exists()


class TestCatalogIsolation:
    def test_ableton_and_stems_are_not_library_tracks(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive = tmp_path / "drive"
        dj_music = drive / "DJ Music"
        platinum = drive / "Platnium Notes"
        ableton = drive / "Ableton" / "Sessions"
        stems = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft" / "As It Was"
        nested_ableton = dj_music / "Ableton"
        nested_ableton.mkdir(parents=True)
        platinum.mkdir(parents=True)
        ableton.mkdir(parents=True)
        stems.mkdir(parents=True)

        (dj_music / "keep.mp3").write_bytes(b"dj")
        (platinum / "note.wav").write_bytes(b"pn")
        (nested_ableton / "from-ableton-dir.mp3").write_bytes(b"skip")
        (ableton / "Project.als").write_bytes(b"als")
        (ableton / "bounce.wav").write_bytes(b"ableton-audio")
        (stems / "vocals.wav").write_bytes(b"stem")

        from library_sync.index_ableton import index_ableton
        from library_sync.index_stems import index_stems

        with LibraryDB(db_path) as db:
            index_files(db, drive, [dj_music, platinum])
            index_stems(db, drive)
            index_ableton(db, drive)

            track_paths = {t.relative_path for t in db.query_tracks()}
            assert track_paths == {"DJ Music/keep.mp3", "Platnium Notes/note.wav"}
            assert all(not p.startswith("Ableton/") for p in track_paths)
            assert all("stem-output" not in p for p in track_paths)
            assert all(not p.endswith(".als") for p in track_paths)

            stems_found = db.query_stems()
            assert len(stems_found) == 1
            assert stems_found[0].song_name == "As It Was"
            assert stems_found[0].relative_path.startswith("Stem Splitting/")

            projects = db.query_ableton()
            assert len(projects) == 1
            assert projects[0].relative_path.endswith(".als")

    def test_restores_missing_track_with_same_size_mtime(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        drive = tmp_path / "drive"
        dj_music = drive / "DJ Music"
        dj_music.mkdir(parents=True)
        song = dj_music / "song.mp3"
        payload = b"same-bytes"
        song.write_bytes(payload)
        orig_stat = song.stat()

        with LibraryDB(db_path) as db:
            index_files(db, drive, [dj_music])
            assert db.count_tracks(status="present") == 1

            song.unlink()
            stats_missing = index_files(db, drive, [dj_music])
            assert stats_missing["missing"] == 1
            assert db.get_track_by_path("DJ Music/song.mp3").status == "missing"

            song.write_bytes(payload)
            os.utime(song, (orig_stat.st_atime, orig_stat.st_mtime))
            stats_restore = index_files(db, drive, [dj_music])
            assert stats_restore["updated"] == 1
            assert stats_restore["skipped"] == 0
            restored = db.get_track_by_path("DJ Music/song.mp3")
            assert restored is not None
            assert restored.status == "present"
