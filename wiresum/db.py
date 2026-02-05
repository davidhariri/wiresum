"""SQLite database for feed entries and configuration."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import (
    DEFAULT_INTERESTS,
    DEFAULT_MODEL,
    DEFAULT_SYNC_INTERVAL,
    DEFAULT_USER_CONTEXT,
    get_default_process_after,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    feedbin_id INTEGER UNIQUE NOT NULL,
    feed_name TEXT,
    title TEXT,
    url TEXT,
    content TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    interest TEXT,
    is_signal INTEGER,
    reasoning TEXT,
    read_at TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_feedbin_id ON entries(feedbin_id);
CREATE INDEX IF NOT EXISTS idx_entries_processed ON entries(processed_at);
CREATE INDEX IF NOT EXISTS idx_entries_interest ON entries(interest);
CREATE INDEX IF NOT EXISTS idx_entries_is_signal ON entries(is_signal);
"""

# Migration to rename topic -> interest
MIGRATIONS = [
    # Rename topic column to interest in entries table
    """
    ALTER TABLE entries RENAME COLUMN topic TO interest;
    """,
    # Rename topics table to interests and name to label
    """
    ALTER TABLE topics RENAME TO interests;
    """,
    """
    ALTER TABLE interests RENAME COLUMN name TO label;
    """,
    # Add read_at column for read/unread tracking
    """
    ALTER TABLE entries ADD COLUMN read_at TEXT;
    """,
]


@dataclass
class Entry:
    """A feed entry."""

    id: int | None
    feedbin_id: int
    feed_name: str | None
    title: str | None
    url: str | None
    content: str | None
    author: str | None
    published_at: str | None
    fetched_at: str | None
    processed_at: str | None
    interest: str | None
    is_signal: bool | None
    reasoning: str | None
    read_at: str | None = None


@dataclass
class Interest:
    """A classification interest."""

    id: int | None
    key: str
    label: str
    description: str | None


class Database:
    """SQLite database wrapper for wiresum."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema and seed default data."""
        with self._connect() as conn:
            # Check if we need to migrate from old schema
            self._run_migrations(conn)

            conn.executescript(SCHEMA)

            # Seed default interests if table is empty
            count = conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO interests (key, label, description) VALUES (?, ?, ?)",
                    DEFAULT_INTERESTS,
                )

            # Seed default config if not present
            for key, default in [
                ("user_context", DEFAULT_USER_CONTEXT),
                ("model", DEFAULT_MODEL),
                ("sync_interval", str(DEFAULT_SYNC_INTERVAL)),
                ("process_after", get_default_process_after()),
            ]:
                existing = conn.execute(
                    "SELECT 1 FROM config WHERE key = ?", (key,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO config (key, value) VALUES (?, ?)",
                        (key, default),
                    )

    def _run_migrations(self, conn):
        """Run migrations if needed to update from old schema."""
        # Check if old 'topics' table exists
        old_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='topics'"
        ).fetchone()

        if old_table:
            # Check if entries has 'topic' column (old) vs 'interest' (new)
            columns = conn.execute("PRAGMA table_info(entries)").fetchall()
            column_names = [col[1] for col in columns]

            if "topic" in column_names:
                # Need to migrate entries.topic -> entries.interest
                conn.execute("ALTER TABLE entries RENAME COLUMN topic TO interest")

            # Migrate topics table to interests
            conn.execute("ALTER TABLE topics RENAME TO interests")

            # Check if interests has 'name' column (old) vs 'label' (new)
            columns = conn.execute("PRAGMA table_info(interests)").fetchall()
            column_names = [col[1] for col in columns]

            if "name" in column_names:
                conn.execute("ALTER TABLE interests RENAME COLUMN name TO label")

        # Add read_at column if it doesn't exist (for read/unread tracking)
        # Only run if entries table exists (skip on fresh install)
        entries_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entries'"
        ).fetchone()
        if entries_exists:
            columns = conn.execute("PRAGMA table_info(entries)").fetchall()
            column_names = [col[1] for col in columns]
            if "read_at" not in column_names:
                conn.execute("ALTER TABLE entries ADD COLUMN read_at TEXT")

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- Entry operations ---

    def upsert_entry(self, entry: Entry) -> int:
        """Insert or update an entry, returning its ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO entries (feedbin_id, feed_name, title, url, content, author, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feedbin_id) DO UPDATE SET
                    feed_name = COALESCE(excluded.feed_name, entries.feed_name),
                    title = COALESCE(excluded.title, entries.title),
                    url = COALESCE(excluded.url, entries.url),
                    content = COALESCE(excluded.content, entries.content),
                    author = COALESCE(excluded.author, entries.author),
                    published_at = COALESCE(excluded.published_at, entries.published_at)
                RETURNING id
                """,
                (
                    entry.feedbin_id,
                    entry.feed_name,
                    entry.title,
                    entry.url,
                    entry.content,
                    entry.author,
                    entry.published_at,
                ),
            )
            return cursor.fetchone()[0]

    def get_entry(self, entry_id: int) -> Entry | None:
        """Get an entry by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()
            return self._row_to_entry(row) if row else None

    def get_entries(
        self,
        processed: bool | None = None,
        interest: str | None = None,
        is_signal: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        since_hours: int | None = None,
        date: str | None = None,
    ) -> list[Entry]:
        """Get entries with optional filters.

        Args:
            date: Filter to a specific date (YYYY-MM-DD format).
        """
        conditions = []
        params = []

        if processed is True:
            conditions.append("processed_at IS NOT NULL")
        elif processed is False:
            conditions.append("processed_at IS NULL")

        if interest is not None:
            conditions.append("interest = ?")
            params.append(interest)

        if is_signal is not None:
            conditions.append("is_signal = ?")
            params.append(1 if is_signal else 0)

        if date is not None:
            # Filter to entries published on this specific date (UTC)
            conditions.append("date(published_at) = ?")
            params.append(date)
        elif since_hours is not None:
            conditions.append("published_at >= datetime('now', ?)")
            params.append(f"-{since_hours} hours")

        query = "SELECT * FROM entries"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def get_unprocessed_entries(self, limit: int = 10) -> list[Entry]:
        """Get entries that haven't been classified yet.

        Respects the 'process_after' config value to skip old entries.
        """
        process_after = self.get_config("process_after")

        with self._connect() as conn:
            if process_after:
                rows = conn.execute(
                    """
                    SELECT * FROM entries
                    WHERE processed_at IS NULL AND published_at >= ?
                    ORDER BY fetched_at ASC
                    LIMIT ?
                    """,
                    (process_after, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM entries
                    WHERE processed_at IS NULL
                    ORDER BY fetched_at ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def update_entry_classification(
        self,
        entry_id: int,
        interest: str | None,
        is_signal: bool,
        reasoning: str,
    ):
        """Update an entry with classification results."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE entries
                SET interest = ?, is_signal = ?, reasoning = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (interest, 1 if is_signal else 0, reasoning, entry_id),
            )

    def clear_entry_classification(self, entry_id: int):
        """Clear classification for reprocessing."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE entries
                SET interest = NULL, is_signal = NULL, reasoning = NULL, processed_at = NULL
                WHERE id = ?
                """,
                (entry_id,),
            )

    def update_entry_content(self, entry_id: int, content: str):
        """Update an entry's content (e.g., after fetching from URL)."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE entries
                SET content = ?
                WHERE id = ?
                """,
                (content, entry_id),
            )

    def mark_entry_read(self, entry_id: int):
        """Mark an entry as read."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE entries
                SET read_at = CURRENT_TIMESTAMP
                WHERE id = ? AND read_at IS NULL
                """,
                (entry_id,),
            )

    def requeue_entries(self, since_hours: int = 24) -> int:
        """Mark entries for reprocessing by clearing their processed status.

        Returns the number of entries requeued.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE entries
                SET interest = NULL, is_signal = NULL, reasoning = NULL, processed_at = NULL
                WHERE published_at >= datetime('now', ?)
                """,
                (f"-{since_hours} hours",),
            )
            return cursor.rowcount

    def get_entry_counts_by_interest(self) -> dict[str | None, int]:
        """Get count of signal entries per interest."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT interest, COUNT(*) as count
                FROM entries
                WHERE is_signal = 1 AND processed_at IS NOT NULL
                GROUP BY interest
                """
            ).fetchall()
            return {row["interest"]: row["count"] for row in rows}

    def get_latest_feedbin_id(self) -> int | None:
        """Get the most recent feedbin_id we've synced."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(feedbin_id) as max_id FROM entries"
            ).fetchone()
            return row["max_id"] if row else None

    # --- Config operations ---

    def get_config(self, key: str) -> str | None:
        """Get a config value."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_config(self, key: str, value: str):
        """Set a config value."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_all_config(self) -> dict[str, str]:
        """Get all config values."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
            return {row["key"]: row["value"] for row in rows}

    # --- Interest operations ---

    def get_interests(self) -> list[Interest]:
        """Get all interests."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM interests ORDER BY label"
            ).fetchall()
            return [self._row_to_interest(row) for row in rows]

    def get_interest(self, key: str) -> Interest | None:
        """Get an interest by key."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM interests WHERE key = ?", (key,)
            ).fetchone()
            return self._row_to_interest(row) if row else None

    def create_interest(self, key: str, label: str, description: str | None = None) -> int:
        """Create a new interest."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO interests (key, label, description) VALUES (?, ?, ?) RETURNING id",
                (key, label, description),
            )
            return cursor.fetchone()[0]

    def update_interest(self, key: str, label: str | None = None, description: str | None = None):
        """Update an existing interest."""
        updates = []
        params = []

        if label is not None:
            updates.append("label = ?")
            params.append(label)
        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            return

        params.append(key)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE interests SET {', '.join(updates)} WHERE key = ?",
                params,
            )

    def delete_interest(self, key: str):
        """Delete an interest."""
        with self._connect() as conn:
            conn.execute("DELETE FROM interests WHERE key = ?", (key,))

    # --- Stats ---

    def get_stats(self, since_hours: int | None = None) -> dict:
        """Get database statistics.

        Unprocessed count respects the 'process_after' config value.
        """
        process_after = self.get_config("process_after")

        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

            if process_after:
                unprocessed = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE processed_at IS NULL AND published_at >= ?",
                    (process_after,),
                ).fetchone()[0]
            else:
                unprocessed = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE processed_at IS NULL"
                ).fetchone()[0]

            # Signal count (optionally filtered by time)
            if since_hours:
                signal = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE is_signal = 1 AND published_at >= datetime('now', ?)",
                    (f"-{since_hours} hours",),
                ).fetchone()[0]
            else:
                signal = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE is_signal = 1"
                ).fetchone()[0]

            return {
                "total_entries": total,
                "unprocessed": unprocessed,
                "signal": signal,
            }

    # --- Helpers ---

    def _row_to_entry(self, row: sqlite3.Row) -> Entry:
        """Convert a database row to an Entry."""
        return Entry(
            id=row["id"],
            feedbin_id=row["feedbin_id"],
            feed_name=row["feed_name"],
            title=row["title"],
            url=row["url"],
            content=row["content"],
            author=row["author"],
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            processed_at=row["processed_at"],
            interest=row["interest"],
            is_signal=bool(row["is_signal"]) if row["is_signal"] is not None else None,
            reasoning=row["reasoning"],
            read_at=row["read_at"] if "read_at" in row.keys() else None,
        )

    def _row_to_interest(self, row: sqlite3.Row) -> Interest:
        """Convert a database row to an Interest."""
        return Interest(
            id=row["id"],
            key=row["key"],
            label=row["label"],
            description=row["description"],
        )
