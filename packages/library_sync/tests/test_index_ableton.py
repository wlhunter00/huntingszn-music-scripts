"""Tests for Ableton project indexing."""

from pathlib import Path

from library_sync.db import LibraryDB
from library_sync.index_ableton import (
    _get_folder,
    _get_kind,
    index_ableton,
    scan_ableton_projects,
)


class TestHelpers:
    def test_get_folder(self) -> None:
        """Test folder extraction from relative path."""
        assert _get_folder("Ableton/Sessions/MySong.als") == "Sessions"
        assert _get_folder("Ableton/Collabs/Track.als") == "Collabs"
        assert _get_folder("Other/Path.als") == ""

    def test_get_kind_template(self) -> None:
        """Test template detection."""
        assert _get_kind("Ableton/HuntingSzn Template 3.0 Project/song.als") == "template"
        assert _get_kind("Ableton/Crankdat Template/test.als") == "template"
        assert _get_kind("Ableton/mashup template project/song.als") == "template"

    def test_get_kind_project(self) -> None:
        """Test regular project detection."""
        assert _get_kind("Ableton/Sessions/MySong.als") == "project"
        assert _get_kind("Ableton/Collabs/Track.als") == "project"


class TestScanAbletonProjects:
    def test_scans_als_files(self, tmp_path: Path) -> None:
        """Test scanning .als files."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton"

        sessions = ableton / "Sessions"
        sessions.mkdir(parents=True)
        (sessions / "MySong.als").write_bytes(b"ableton")
        (sessions / "Another.als").write_bytes(b"ableton2")

        files = scan_ableton_projects(ableton, drive)
        assert len(files) == 2

        paths = {f[1] for f in files}
        assert "Ableton/Sessions/MySong.als" in paths
        assert "Ableton/Sessions/Another.als" in paths

    def test_scans_uppercase_als(self, tmp_path: Path) -> None:
        drive = tmp_path / "drive"
        sessions = drive / "Ableton" / "Sessions"
        sessions.mkdir(parents=True)
        (sessions / "Live.ALS").write_bytes(b"ableton")
        files = scan_ableton_projects(drive / "Ableton", drive)
        assert len(files) == 1

    def test_skips_backup_folders(self, tmp_path: Path) -> None:
        """Test that Backup folders are skipped."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton"

        project = ableton / "Sessions" / "MyProject"
        project.mkdir(parents=True)
        (project / "MyProject.als").write_bytes(b"main")

        backup = project / "Backup"
        backup.mkdir()
        (backup / "MyProject [2024-01-01].als").write_bytes(b"backup")

        files = scan_ableton_projects(ableton, drive)
        assert len(files) == 1
        assert files[0][1] == "Ableton/Sessions/MyProject/MyProject.als"

    def test_returns_empty_if_no_ableton(self, tmp_path: Path) -> None:
        """Test that missing Ableton folder returns empty list."""
        drive = tmp_path / "drive"
        drive.mkdir()

        files = scan_ableton_projects(drive / "Ableton", drive)
        assert files == []


class TestIndexAbleton:
    def test_indexes_als_files(self, tmp_path: Path) -> None:
        """Test indexing Ableton projects into database."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton"

        sessions = ableton / "Sessions"
        sessions.mkdir(parents=True)
        (sessions / "MySong.als").write_bytes(b"ableton" * 100)

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats = index_ableton(db, drive)

            assert stats["scanned"] == 1
            assert stats["added"] == 1

            projects = db.query_ableton()
            assert len(projects) == 1
            assert projects[0].name == "MySong"
            assert projects[0].folder == "Sessions"
            assert projects[0].kind == "project"

    def test_detects_templates(self, tmp_path: Path) -> None:
        """Test that templates are properly detected."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton"

        template_dir = ableton / "HuntingSzn Template Project"
        template_dir.mkdir(parents=True)
        (template_dir / "Template.als").write_bytes(b"template")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_ableton(db, drive)

            projects = db.query_ableton()
            assert len(projects) == 1
            assert projects[0].kind == "template"

    def test_incremental_skip(self, tmp_path: Path) -> None:
        """Test that unchanged projects are skipped on re-index."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton" / "Sessions"
        ableton.mkdir(parents=True)
        (ableton / "Unchanged.als").write_bytes(b"als")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats1 = index_ableton(db, drive)
            assert stats1["added"] == 1

            stats2 = index_ableton(db, drive)
            assert stats2["skipped"] == 1
            assert stats2["added"] == 0

    def test_marks_missing(self, tmp_path: Path) -> None:
        """Test that removed projects are marked missing."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton" / "Sessions"
        ableton.mkdir(parents=True)
        als_file = ableton / "ToDelete.als"
        als_file.write_bytes(b"als")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_ableton(db, drive)
            assert db.count_ableton(status="present") == 1

            als_file.unlink()

            stats = index_ableton(db, drive)
            assert stats["missing"] == 1
            assert db.count_ableton(status="present") == 0
            assert db.count_ableton(status="missing") == 1

    def test_dry_run_no_write(self, tmp_path: Path) -> None:
        """Test dry run doesn't write to database."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton" / "Sessions"
        ableton.mkdir(parents=True)
        (ableton / "DryRun.als").write_bytes(b"als")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            stats = index_ableton(db, drive, dry_run=True)
            assert stats["added"] == 1
            assert db.count_ableton() == 0


class TestQueryAbleton:
    def test_query_by_text(self, tmp_path: Path) -> None:
        """Test querying projects by name."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton" / "Sessions"
        ableton.mkdir(parents=True)

        for name in ["Mashup Mix", "Original Track", "Remix Version"]:
            (ableton / f"{name}.als").write_bytes(b"als")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_ableton(db, drive)

            results = db.query_ableton(text_search="mashup")
            assert len(results) == 1
            assert results[0].name == "Mashup Mix"

    def test_query_by_kind(self, tmp_path: Path) -> None:
        """Test querying projects by kind."""
        drive = tmp_path / "drive"
        ableton = drive / "Ableton"

        sessions = ableton / "Sessions"
        sessions.mkdir(parents=True)
        (sessions / "Regular.als").write_bytes(b"als")

        template = ableton / "My Template Project"
        template.mkdir(parents=True)
        (template / "Template.als").write_bytes(b"als")

        db_path = tmp_path / "library.sqlite"
        with LibraryDB(db_path) as db:
            index_ableton(db, drive)

            templates = db.query_ableton(kind="template")
            assert len(templates) == 1
            assert templates[0].kind == "template"

            projects = db.query_ableton(kind="project")
            assert len(projects) == 1
            assert projects[0].kind == "project"
