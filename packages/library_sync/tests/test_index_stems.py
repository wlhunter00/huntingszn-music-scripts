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
