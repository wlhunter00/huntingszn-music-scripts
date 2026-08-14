"""Tests for stem folder indexing."""

from pathlib import Path

from library_sync.db import LibraryDB
from library_sync.index_stems import _stem_kind, index_stems, scan_stem_folders


class TestScanStemFolders:
    def test_scans_stem_folders(self, tmp_path: Path) -> None:
        """Test scanning stem output folders."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        htdemucs = stem_output / "htdemucs" / "Test Song"
        htdemucs.mkdir(parents=True)
        (htdemucs / "vocals.wav").write_bytes(b"fake")
        (htdemucs / "drums.wav").write_bytes(b"fake")

        htdemucs_ft = stem_output / "htdemucs_ft" / "Another Song"
        htdemucs_ft.mkdir(parents=True)
        (htdemucs_ft / "vocals.wav").write_bytes(b"fake")
        (htdemucs_ft / "no_vocals.wav").write_bytes(b"fake")

        folders = scan_stem_folders(stem_output, drive)
        assert len(folders) == 2

        paths = {f[1] for f in folders}
        assert "Stem Splitting/stem-output/htdemucs/Test Song" in paths
        assert "Stem Splitting/stem-output/htdemucs_ft/Another Song" in paths

    def test_skips_folders_without_stems(self, tmp_path: Path) -> None:
        """Test that folders without stem files are skipped."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        empty = stem_output / "htdemucs" / "Empty Folder"
        empty.mkdir(parents=True)
        (empty / "random.txt").write_text("not a stem")

        folders = scan_stem_folders(stem_output, drive)
        assert len(folders) == 0

    def test_returns_empty_if_no_stem_output(self, tmp_path: Path) -> None:
        """Test that missing stem-output returns empty list."""
        drive = tmp_path / "drive"
        drive.mkdir()

        folders = scan_stem_folders(drive / "Stem Splitting" / "stem-output", drive)
        assert folders == []


class TestPrefixedStemNames:
    def test_scans_stem_split_pipeline_names(self, tmp_path: Path) -> None:
        drive = tmp_path / "drive"
        song_dir = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft" / "As It Was"
        song_dir.mkdir(parents=True)
        (song_dir / "As It Was_vocals.wav").write_bytes(b"v" * 10)
        (song_dir / "As It Was_no_vocals.wav").write_bytes(b"n" * 10)
        (song_dir / "As It Was_drums.wav").write_bytes(b"d" * 10)
        (song_dir / "As It Was_drums_2.wav").write_bytes(b"d2")
        (song_dir / "As It Was_bass.wav").write_bytes(b"b" * 10)
        (song_dir / "As It Was_other.wav").write_bytes(b"o" * 10)

        folders = scan_stem_folders(drive / "Stem Splitting" / "stem-output", drive)
        assert len(folders) == 1

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats = index_stems(db, drive)
            assert stats["added"] == 1
            stems = db.query_stems()
            assert len(stems) == 1
            assert stems[0].has_vocals == 1
            assert stems[0].has_no_vocals == 1
            assert stems[0].has_drums == 1
            assert stems[0].has_bass == 1
            assert stems[0].has_other == 1
            assert stems[0].file_size == 50

    def test_no_vocals_not_classified_as_vocals(self) -> None:
        assert _stem_kind("no_vocals.wav") == "no_vocals"
        assert _stem_kind("As It Was_no_vocals.wav") == "no_vocals"
        assert _stem_kind("As It Was_vocals.wav") == "vocals"
        assert _stem_kind("As It Was_drums_2.wav") is None
        assert _stem_kind("._vocals.wav") is None
        assert _stem_kind("._As It Was_vocals.wav") is None

    def test_skips_appledouble_stem_files(self, tmp_path: Path) -> None:
        drive = tmp_path / "drive"
        real = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft" / "Real Song"
        decoy = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft" / "AppleDouble Only"
        real.mkdir(parents=True)
        decoy.mkdir(parents=True)
        (real / "vocals.wav").write_bytes(b"v")
        (real / "._vocals.wav").write_bytes(b"appledouble")
        (decoy / "._vocals.wav").write_bytes(b"appledouble")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)
            stems = db.query_stems()
            assert {s.song_name for s in stems} == {"Real Song"}
            assert stems[0].has_vocals == 1

    def test_skips_appledouble_stem_directories(self, tmp_path: Path) -> None:
        drive = tmp_path / "drive"
        real_model = drive / "Stem Splitting" / "stem-output" / "htdemucs_ft"
        decoy_model = drive / "Stem Splitting" / "stem-output" / "._htdemucs_ft"
        real_song = real_model / "Real Song"
        decoy_song = real_model / "._Real Song"
        decoy_model_song = decoy_model / "Fake Song"
        real_song.mkdir(parents=True)
        decoy_song.mkdir(parents=True)
        decoy_model_song.mkdir(parents=True)
        (real_song / "vocals.wav").write_bytes(b"v")
        (decoy_song / "vocals.wav").write_bytes(b"appledouble")
        (decoy_model_song / "vocals.wav").write_bytes(b"appledouble")

        folders = scan_stem_folders(drive / "Stem Splitting" / "stem-output", drive)
        assert [f[2] for f in folders] == ["Real Song"]
        assert [f[3] for f in folders] == ["htdemucs_ft"]


class TestIndexStems:
    def test_indexes_stem_folders(self, tmp_path: Path) -> None:
        """Test indexing stem folders into database."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        song_dir = stem_output / "htdemucs_ft" / "My Song"
        song_dir.mkdir(parents=True)
        (song_dir / "vocals.wav").write_bytes(b"v" * 100)
        (song_dir / "drums.wav").write_bytes(b"d" * 50)
        (song_dir / "bass.wav").write_bytes(b"b" * 75)

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats = index_stems(db, drive)

            assert stats["scanned"] == 1
            assert stats["added"] == 1

            stems = db.query_stems()
            assert len(stems) == 1
            assert stems[0].song_name == "My Song"
            assert stems[0].model == "htdemucs_ft"
            assert stems[0].has_vocals == 1
            assert stems[0].has_drums == 1
            assert stems[0].has_bass == 1
            assert stems[0].has_other == 0
            assert stems[0].has_no_vocals == 0
            assert stems[0].file_size == 225

    def test_incremental_skip(self, tmp_path: Path) -> None:
        """Test that unchanged stems are skipped on re-index."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        song_dir = stem_output / "htdemucs" / "Unchanged"
        song_dir.mkdir(parents=True)
        (song_dir / "vocals.wav").write_bytes(b"v" * 100)

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats1 = index_stems(db, drive)
            assert stats1["added"] == 1

            stats2 = index_stems(db, drive)
            assert stats2["skipped"] == 1
            assert stats2["added"] == 0

    def test_marks_missing(self, tmp_path: Path) -> None:
        """Test that removed stems are marked missing."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        song_dir = stem_output / "htdemucs" / "ToBeDeleted"
        song_dir.mkdir(parents=True)
        (song_dir / "vocals.wav").write_bytes(b"v")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)
            assert db.count_stems(status="present") == 1

            import shutil
            shutil.rmtree(song_dir)

            stats = index_stems(db, drive)
            assert stats["missing"] == 1
            assert db.count_stems(status="present") == 0
            assert db.count_stems(status="missing") == 1

    def test_dry_run_no_write(self, tmp_path: Path) -> None:
        """Test dry run doesn't write to database."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        song_dir = stem_output / "htdemucs" / "DryRunSong"
        song_dir.mkdir(parents=True)
        (song_dir / "vocals.wav").write_bytes(b"v")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats = index_stems(db, drive, dry_run=True)
            assert stats["added"] == 1
            assert db.count_stems() == 0


class TestQueryStems:
    def test_query_by_text(self, tmp_path: Path) -> None:
        """Test querying stems by song name."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        for name in ["As It Was", "Blinding Lights", "Shape Of You"]:
            song_dir = stem_output / "htdemucs" / name
            song_dir.mkdir(parents=True)
            (song_dir / "vocals.wav").write_bytes(b"v")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)

            results = db.query_stems(text_search="as it was")
            assert len(results) == 1
            assert results[0].song_name == "As It Was"

    def test_query_by_model(self, tmp_path: Path) -> None:
        """Test querying stems by model."""
        drive = tmp_path / "drive"
        stem_output = drive / "Stem Splitting" / "stem-output"

        for model in ["htdemucs", "htdemucs_ft"]:
            song_dir = stem_output / model / "Test"
            song_dir.mkdir(parents=True)
            (song_dir / "vocals.wav").write_bytes(b"v")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)

            results = db.query_stems(model="htdemucs_ft")
            assert len(results) == 1
            assert results[0].model == "htdemucs_ft"

    def test_missing_stem_output_does_not_mark_missing(self, tmp_path: Path) -> None:
        drive = tmp_path / "drive"
        song_dir = drive / "Stem Splitting" / "stem-output" / "htdemucs" / "Keep"
        song_dir.mkdir(parents=True)
        (song_dir / "vocals.wav").write_bytes(b"v")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)
            assert db.count_stems(status="present") == 1

            import shutil

            shutil.rmtree(drive / "Stem Splitting")
            stats = index_stems(db, drive)
            assert stats["missing"] == 0
            assert db.count_stems(status="present") == 1

    def test_restores_missing_stem_with_same_size_mtime(self, tmp_path: Path) -> None:
        import os

        drive = tmp_path / "drive"
        song_dir = drive / "Stem Splitting" / "stem-output" / "htdemucs" / "Keep"
        song_dir.mkdir(parents=True)
        vocals = song_dir / "vocals.wav"
        payload = b"v" * 40
        vocals.write_bytes(payload)
        orig = vocals.stat()

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_stems(db, drive)
            import shutil

            shutil.rmtree(song_dir)
            index_stems(db, drive)
            assert db.count_stems(status="missing") == 1

            song_dir.mkdir(parents=True)
            vocals.write_bytes(payload)
            os.utime(vocals, (orig.st_atime, orig.st_mtime))
            stats = index_stems(db, drive)
            assert stats["updated"] == 1
            assert stats["skipped"] == 0
            assert db.query_stems()[0].status == "present"
