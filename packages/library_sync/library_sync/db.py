"""SQLite database schema and operations for the library catalog."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
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
"""


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


def compute_track_id(relative_path: str, file_size: int) -> str:
    """Compute stable hash ID from path + size."""
    data = f"{relative_path}\0{file_size}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(UTC).isoformat()


class LibraryDB:
    """SQLite database wrapper for the library catalog."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LibraryDB:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

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
    ) -> tuple[int | None, float | None]:
        """Get file_size and mtime for incremental update check.

        Returns (file_size, mtime) or (None, None) if not found.
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT file_size, mtime FROM tracks WHERE relative_path = ?",
            (relative_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None, None
        return row["file_size"], row["mtime"]

    def upsert_track(self, track: Track) -> None:
        """Insert or update a track record."""
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
        conn.commit()

    def mark_missing(self, relative_paths: set[str]) -> int:
        """Mark tracks as missing if their paths are in the given set.

        Returns count of tracks marked missing.
        """
        if not relative_paths:
            return 0
        conn = self.connect()
        placeholders = ",".join("?" for _ in relative_paths)
        cursor = conn.execute(
            f"""
            UPDATE tracks SET status = 'missing', updated_at = ?
            WHERE relative_path IN ({placeholders}) AND status = 'present'
            """,
            (utc_now_iso(), *relative_paths),
        )
        conn.commit()
        return cursor.rowcount

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
        text_search: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        status: str = "present",
    ) -> list[Track]:
        """Query tracks with various filters.

        Args:
            camelot_keys: Set of Camelot keys to match
            bpm_range: (min_bpm, max_bpm) tuple
            text_search: Case-insensitive search in artist/title/filename
            role: Filter by role (vocal, drop, unknown)
            limit: Maximum results to return
            status: Track status filter (default: 'present')
        """
        conn = self.connect()
        conditions = ["status = ?"]
        params: list[object] = [status]

        if camelot_keys:
            placeholders = ",".join("?" for _ in camelot_keys)
            conditions.append(f"camelot_key IN ({placeholders})")
            params.extend(camelot_keys)

        if bpm_range:
            conditions.append("bpm >= ? AND bpm <= ?")
            params.extend(bpm_range)

        if text_search:
            conditions.append(
                "(artist LIKE ? OR title LIKE ? OR filename LIKE ?)"
            )
            pattern = f"%{text_search}%"
            params.extend([pattern, pattern, pattern])

        if role:
            conditions.append("role = ?")
            params.append(role)

        sql = "SELECT * FROM tracks WHERE " + " AND ".join(conditions)
        if limit:
            sql += f" LIMIT {limit}"

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
        """Get the most recent updated_at timestamp."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT MAX(updated_at) FROM tracks WHERE status = 'present'"
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
