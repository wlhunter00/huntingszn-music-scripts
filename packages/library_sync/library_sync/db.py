"""SQLite database schema and operations for the library catalog."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    filename TEXT,
    artist TEXT,
    title TEXT,
    album TEXT,
    genre TEXT,
    duration_sec REAL,
    bpm REAL,
    key TEXT,
    camelot_key TEXT,
    file_size INTEGER,
    mtime REAL,
    audio_object_key TEXT,
    mik_analyzed_at TEXT,
    updated_at TEXT,
    role TEXT,
    source_root TEXT,
    status TEXT DEFAULT 'present'
);

CREATE INDEX IF NOT EXISTS idx_tracks_camelot ON tracks(camelot_key);
CREATE INDEX IF NOT EXISTS idx_tracks_bpm ON tracks(bpm);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_tracks_source_root ON tracks(source_root);

CREATE TABLE IF NOT EXISTS stems (
    id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    song_name TEXT,
    model TEXT,
    has_vocals INTEGER DEFAULT 0,
    has_drums INTEGER DEFAULT 0,
    has_bass INTEGER DEFAULT 0,
    has_other INTEGER DEFAULT 0,
    has_no_vocals INTEGER DEFAULT 0,
    file_size INTEGER,
    mtime REAL,
    updated_at TEXT,
    status TEXT DEFAULT 'present'
);

CREATE INDEX IF NOT EXISTS idx_stems_model ON stems(model);
CREATE INDEX IF NOT EXISTS idx_stems_status ON stems(status);
CREATE INDEX IF NOT EXISTS idx_stems_song_name ON stems(song_name);

CREATE TABLE IF NOT EXISTS ableton_projects (
    id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    name TEXT,
    folder TEXT,
    kind TEXT,
    file_size INTEGER,
    mtime REAL,
    updated_at TEXT,
    status TEXT DEFAULT 'present'
);

CREATE INDEX IF NOT EXISTS idx_ableton_folder ON ableton_projects(folder);
CREATE INDEX IF NOT EXISTS idx_ableton_kind ON ableton_projects(kind);
CREATE INDEX IF NOT EXISTS idx_ableton_status ON ableton_projects(status);
"""

# Stay well under SQLite's default SQLITE_MAX_VARIABLE_NUMBER (999).
IN_CLAUSE_CHUNK = 500


@dataclass
class Track:
    """A track record from the library database."""

    id: str
    relative_path: str
    filename: str
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    genre: str | None = None
    duration_sec: float | None = None
    bpm: float | None = None
    key: str | None = None
    camelot_key: str | None = None
    file_size: int = 0
    mtime: float = 0.0
    audio_object_key: str = ""
    mik_analyzed_at: str | None = None
    updated_at: str = ""
    role: str | None = None
    source_root: str = ""
    status: str = "present"


@dataclass
class Stem:
    """A stem folder record from the library database."""

    id: str
    relative_path: str
    song_name: str
    model: str
    has_vocals: int = 0
    has_drums: int = 0
    has_bass: int = 0
    has_other: int = 0
    has_no_vocals: int = 0
    file_size: int = 0
    mtime: float = 0.0
    updated_at: str = ""
    status: str = "present"


@dataclass
class AbletonProject:
    """An Ableton project record from the library database."""

    id: str
    relative_path: str
    name: str
    folder: str
    kind: str
    file_size: int = 0
    mtime: float = 0.0
    updated_at: str = ""
    status: str = "present"


def compute_track_id(relative_path: str, file_size: int) -> str:
    """Compute stable hash ID from path + size."""
    data = f"{relative_path}\0{file_size}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def is_present_and_unchanged(
    existing_size: int | None,
    existing_mtime: float | None,
    existing_status: str | None,
    file_size: int,
    mtime: float,
) -> bool:
    """True when a present row matches size and mtime (safe to skip re-read).

    Missing rows must not skip: restoring a file with the same size/mtime
    (rclone, rsync -a, USB remount) has to mark it present again.
    """
    return (
        existing_status == "present"
        and existing_size == file_size
        and existing_mtime == mtime
    )


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(UTC).isoformat()


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user search is literal."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class LibraryDB:
    """SQLite database wrapper for the library catalog."""

    def __init__(self, db_path: Path, *, create: bool = True):
        self.db_path = db_path
        self._create = create
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            exists = self.db_path.exists()
            if not exists and not self._create:
                self._conn = sqlite3.connect(":memory:")
            else:
                if not exists:
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout=5000")
            # DELETE journal: WAL sidecars on a USB drive are easy to copy torn.
            if self._create:
                self._conn.execute("PRAGMA journal_mode=DELETE")
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self, *, commit: bool = True) -> None:
        """Close the connection. Commit on success; rollback on failure."""
        if self._conn is not None:
            if commit:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LibraryDB:
        self.connect()
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.close(commit=exc_type is None)

    def prepare_for_copy(self) -> None:
        """Checkpoint any leftover WAL and switch to DELETE before file copy."""
        conn = self.connect()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for transactions."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def get_track_by_path(self, relative_path: str) -> Track | None:
        """Get a track by its relative path."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM tracks WHERE relative_path = ?", (relative_path,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_track(row)

    def get_track_for_update_check(
        self, relative_path: str
    ) -> tuple[int | None, float | None, str | None]:
        """Get file_size, mtime, and status for incremental update check.

        Returns (file_size, mtime, status) or (None, None, None) if not found.
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT file_size, mtime, status FROM tracks WHERE relative_path = ?",
            (relative_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None, None, None
        return row["file_size"], row["mtime"], row["status"]

    def upsert_track(self, track: Track) -> None:
        """Insert or update a track record. Caller commits (transaction or close)."""
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO tracks (
                id, relative_path, filename, artist, title, album, genre,
                duration_sec, bpm, key, camelot_key, file_size, mtime,
                audio_object_key, mik_analyzed_at, updated_at, role, source_root, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relative_path) DO UPDATE SET
                id = excluded.id,
                filename = excluded.filename,
                artist = excluded.artist,
                title = excluded.title,
                album = excluded.album,
                genre = excluded.genre,
                duration_sec = excluded.duration_sec,
                bpm = excluded.bpm,
                key = excluded.key,
                camelot_key = excluded.camelot_key,
                file_size = excluded.file_size,
                mtime = excluded.mtime,
                audio_object_key = excluded.audio_object_key,
                mik_analyzed_at = excluded.mik_analyzed_at,
                updated_at = excluded.updated_at,
                role = excluded.role,
                source_root = excluded.source_root,
                status = excluded.status
            """,
            (
                track.id,
                track.relative_path,
                track.filename,
                track.artist,
                track.title,
                track.album,
                track.genre,
                track.duration_sec,
                track.bpm,
                track.key,
                track.camelot_key,
                track.file_size,
                track.mtime,
                track.audio_object_key,
                track.mik_analyzed_at,
                track.updated_at,
                track.role,
                track.source_root,
                track.status,
            ),
        )

    def _mark_missing_table(
        self, table: str, relative_paths: Iterable[str], chunk_size: int = IN_CLAUSE_CHUNK
    ) -> int:
        paths = list(relative_paths)
        if not paths:
            return 0
        conn = self.connect()
        now = utc_now_iso()
        total = 0
        for chunk in _chunks(paths, chunk_size):
            placeholders = ",".join("?" for _ in chunk)
            cursor = conn.execute(
                f"""
                UPDATE {table} SET status = 'missing', updated_at = ?
                WHERE relative_path IN ({placeholders}) AND status = 'present'
                """,
                (now, *chunk),
            )
            total += cursor.rowcount
        return total

    def mark_missing(
        self, relative_paths: set[str], *, chunk_size: int = IN_CLAUSE_CHUNK
    ) -> int:
        """Mark tracks as missing if their paths are in the given set."""
        return self._mark_missing_table("tracks", relative_paths, chunk_size)

    def get_all_present_paths(self) -> set[str]:
        """Get all relative paths of present (non-missing) tracks."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT relative_path FROM tracks WHERE status = 'present'"
        )
        return {row["relative_path"] for row in cursor.fetchall()}

    def query_tracks(
        self,
        *,
        camelot_keys: set[str] | None = None,
        bpm_range: tuple[float, float] | None = None,
        bpm_ranges: list[tuple[float, float]] | None = None,
        text_search: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        status: str = "present",
    ) -> list[Track]:
        """Query tracks with various filters.

        Args:
            camelot_keys: Set of Camelot keys to match
            bpm_range: Single (min_bpm, max_bpm) window
            bpm_ranges: Multiple BPM windows combined with OR
            text_search: Case-insensitive search in artist/title/filename
            role: Filter by role (vocal, drop, unknown)
            limit: Maximum results to return
            status: Track status filter (default: 'present')
        """
        conn = self.connect()
        conditions = ["status = ?"]
        params: list[object] = [status]

        if camelot_keys:
            # Match camelot_key only. Production `key` is almost empty and is not queried.
            placeholders = ",".join("?" for _ in camelot_keys)
            conditions.append(f"camelot_key IN ({placeholders})")
            params.extend(camelot_keys)

        windows = list(bpm_ranges) if bpm_ranges else []
        if bpm_range:
            windows.append(bpm_range)
        if windows:
            bpm_clauses = []
            for low, high in windows:
                bpm_clauses.append("(bpm >= ? AND bpm <= ?)")
                params.extend([low, high])
            conditions.append("(" + " OR ".join(bpm_clauses) + ")")

        if text_search:
            conditions.append(
                "(artist LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' "
                "OR filename LIKE ? ESCAPE '\\')"
            )
            pattern = f"%{escape_like(text_search)}%"
            params.extend([pattern, pattern, pattern])

        if role:
            conditions.append("role = ?")
            params.append(role)

        sql = "SELECT * FROM tracks WHERE " + " AND ".join(conditions)
        sql += " ORDER BY relative_path"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        cursor = conn.execute(sql, params)
        return [self._row_to_track(row) for row in cursor.fetchall()]

    def count_tracks(self, status: str | None = None) -> int:
        """Count tracks, optionally filtered by status."""
        conn = self.connect()
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE status = ?", (status,)
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM tracks")
        return cursor.fetchone()[0]

    def get_last_updated(self) -> str | None:
        """Get the most recent updated_at across tracks, stems, and Ableton."""
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT MAX(ts) FROM (
                SELECT MAX(updated_at) AS ts FROM tracks WHERE status = 'present'
                UNION ALL
                SELECT MAX(updated_at) AS ts FROM stems WHERE status = 'present'
                UNION ALL
                SELECT MAX(updated_at) AS ts FROM ableton_projects
                    WHERE status = 'present'
            )
            """
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def _row_to_track(self, row: sqlite3.Row) -> Track:
        """Convert a database row to a Track object."""
        return Track(
            id=row["id"],
            relative_path=row["relative_path"],
            filename=row["filename"],
            artist=row["artist"],
            title=row["title"],
            album=row["album"],
            genre=row["genre"],
            duration_sec=row["duration_sec"],
            bpm=row["bpm"],
            key=row["key"],
            camelot_key=row["camelot_key"],
            file_size=row["file_size"],
            mtime=row["mtime"],
            audio_object_key=row["audio_object_key"],
            mik_analyzed_at=row["mik_analyzed_at"],
            updated_at=row["updated_at"],
            role=row["role"],
            source_root=row["source_root"],
            status=row["status"],
        )

    def get_stem_for_update_check(
        self, relative_path: str
    ) -> tuple[int | None, float | None, str | None]:
        """Get file_size, mtime, and status for incremental stem update check."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT file_size, mtime, status FROM stems WHERE relative_path = ?",
            (relative_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None, None, None
        return row["file_size"], row["mtime"], row["status"]

    def upsert_stem(self, stem: Stem) -> None:
        """Insert or update a stem record. Caller commits."""
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO stems (
                id, relative_path, song_name, model,
                has_vocals, has_drums, has_bass, has_other, has_no_vocals,
                file_size, mtime, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relative_path) DO UPDATE SET
                id = excluded.id,
                song_name = excluded.song_name,
                model = excluded.model,
                has_vocals = excluded.has_vocals,
                has_drums = excluded.has_drums,
                has_bass = excluded.has_bass,
                has_other = excluded.has_other,
                has_no_vocals = excluded.has_no_vocals,
                file_size = excluded.file_size,
                mtime = excluded.mtime,
                updated_at = excluded.updated_at,
                status = excluded.status
            """,
            (
                stem.id,
                stem.relative_path,
                stem.song_name,
                stem.model,
                stem.has_vocals,
                stem.has_drums,
                stem.has_bass,
                stem.has_other,
                stem.has_no_vocals,
                stem.file_size,
                stem.mtime,
                stem.updated_at,
                stem.status,
            ),
        )

    def mark_stems_missing(
        self, relative_paths: set[str], *, chunk_size: int = IN_CLAUSE_CHUNK
    ) -> int:
        """Mark stems as missing."""
        return self._mark_missing_table("stems", relative_paths, chunk_size)

    def get_all_present_stem_paths(self) -> set[str]:
        """Get all relative paths of present stems."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT relative_path FROM stems WHERE status = 'present'"
        )
        return {row["relative_path"] for row in cursor.fetchall()}

    def query_stems(
        self,
        *,
        text_search: str | None = None,
        model: str | None = None,
        limit: int | None = None,
        status: str = "present",
    ) -> list[Stem]:
        """Query stems with filters."""
        conn = self.connect()
        conditions = ["status = ?"]
        params: list[object] = [status]

        if text_search:
            conditions.append("song_name LIKE ? ESCAPE '\\'")
            params.append(f"%{escape_like(text_search)}%")

        if model:
            conditions.append("model = ?")
            params.append(model)

        sql = "SELECT * FROM stems WHERE " + " AND ".join(conditions)
        sql += " ORDER BY song_name, relative_path"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        cursor = conn.execute(sql, params)
        return [self._row_to_stem(row) for row in cursor.fetchall()]

    def count_stems(self, status: str | None = None) -> int:
        """Count stems, optionally filtered by status."""
        conn = self.connect()
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM stems WHERE status = ?", (status,)
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM stems")
        return cursor.fetchone()[0]

    def _row_to_stem(self, row: sqlite3.Row) -> Stem:
        """Convert a database row to a Stem object."""
        return Stem(
            id=row["id"],
            relative_path=row["relative_path"],
            song_name=row["song_name"],
            model=row["model"],
            has_vocals=row["has_vocals"],
            has_drums=row["has_drums"],
            has_bass=row["has_bass"],
            has_other=row["has_other"],
            has_no_vocals=row["has_no_vocals"],
            file_size=row["file_size"],
            mtime=row["mtime"],
            updated_at=row["updated_at"],
            status=row["status"],
        )

    def get_ableton_for_update_check(
        self, relative_path: str
    ) -> tuple[int | None, float | None, str | None]:
        """Get file_size, mtime, and status for incremental Ableton update check."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT file_size, mtime, status FROM ableton_projects WHERE relative_path = ?",
            (relative_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None, None, None
        return row["file_size"], row["mtime"], row["status"]

    def upsert_ableton(self, project: AbletonProject) -> None:
        """Insert or update an Ableton project record. Caller commits."""
        conn = self.connect()
        conn.execute(
            """
            INSERT INTO ableton_projects (
                id, relative_path, name, folder, kind,
                file_size, mtime, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relative_path) DO UPDATE SET
                id = excluded.id,
                name = excluded.name,
                folder = excluded.folder,
                kind = excluded.kind,
                file_size = excluded.file_size,
                mtime = excluded.mtime,
                updated_at = excluded.updated_at,
                status = excluded.status
            """,
            (
                project.id,
                project.relative_path,
                project.name,
                project.folder,
                project.kind,
                project.file_size,
                project.mtime,
                project.updated_at,
                project.status,
            ),
        )

    def mark_ableton_missing(
        self, relative_paths: set[str], *, chunk_size: int = IN_CLAUSE_CHUNK
    ) -> int:
        """Mark Ableton projects as missing."""
        return self._mark_missing_table("ableton_projects", relative_paths, chunk_size)

    def get_all_present_ableton_paths(self) -> set[str]:
        """Get all relative paths of present Ableton projects."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT relative_path FROM ableton_projects WHERE status = 'present'"
        )
        return {row["relative_path"] for row in cursor.fetchall()}

    def query_ableton(
        self,
        *,
        text_search: str | None = None,
        kind: str | None = None,
        limit: int | None = None,
        status: str = "present",
    ) -> list[AbletonProject]:
        """Query Ableton projects with filters."""
        conn = self.connect()
        conditions = ["status = ?"]
        params: list[object] = [status]

        if text_search:
            conditions.append("(name LIKE ? ESCAPE '\\' OR folder LIKE ? ESCAPE '\\')")
            pattern = f"%{escape_like(text_search)}%"
            params.extend([pattern, pattern])

        if kind:
            conditions.append("kind = ?")
            params.append(kind)

        sql = "SELECT * FROM ableton_projects WHERE " + " AND ".join(conditions)
        sql += " ORDER BY name, relative_path"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        cursor = conn.execute(sql, params)
        return [self._row_to_ableton(row) for row in cursor.fetchall()]

    def count_ableton(self, status: str | None = None) -> int:
        """Count Ableton projects, optionally filtered by status."""
        conn = self.connect()
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM ableton_projects WHERE status = ?", (status,)
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM ableton_projects")
        return cursor.fetchone()[0]

    def _row_to_ableton(self, row: sqlite3.Row) -> AbletonProject:
        """Convert a database row to an AbletonProject object."""
        return AbletonProject(
            id=row["id"],
            relative_path=row["relative_path"],
            name=row["name"],
            folder=row["folder"],
            kind=row["kind"],
            file_size=row["file_size"],
            mtime=row["mtime"],
            updated_at=row["updated_at"],
            status=row["status"],
        )
