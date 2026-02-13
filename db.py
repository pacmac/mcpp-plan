"""SQLite helpers for V2 context management."""

from __future__ import annotations

import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


LATEST_SCHEMA_VERSION = 6


def apply_schema_patches(conn: sqlite3.Connection, current_version: int) -> int:
    patches_dir = Path(__file__).resolve().parent / "schema_patches"
    if not patches_dir.exists():
        return current_version

    patches = []
    for path in patches_dir.glob("patch-*.sql"):
        match = re.match(r"patch-(\d+)\.sql", path.name)
        if not match:
            continue
        patches.append((int(match.group(1)), path))

    for version, path in sorted(patches):
        if version <= current_version:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        set_schema_version(conn, version)
        current_version = version

    return current_version

def get_schema_version(conn: sqlite3.Connection) -> Optional[int]:
    try:
        row = conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return int(row["version"])


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (id, version, updated_at) VALUES (1, ?, ?)",
        (version, utc_now_iso()),
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    conn.executescript(schema_path.read_text(encoding="utf-8"))

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "task_number" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN task_number INTEGER;")

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(changelog)").fetchall()}
    if "task_id" not in columns:
        conn.execute("ALTER TABLE changelog ADD COLUMN task_id INTEGER;")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_changelog_task_created "
        "ON changelog(task_id, created_at);"
    )

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "is_deleted" in columns:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_context_deleted "
            "ON tasks(context_id, is_deleted);"
        )

    # Schema version tracking (for migrations).
    version = get_schema_version(conn)
    if version is None:
        # If this is a fresh DB with latest schema, set directly.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "is_deleted" in columns:
            set_schema_version(conn, LATEST_SCHEMA_VERSION)
            version = LATEST_SCHEMA_VERSION
        else:
            # Assume legacy DB; start at version 1 and apply patches.
            set_schema_version(conn, 1)
            version = 1

    if version < LATEST_SCHEMA_VERSION:
        version = apply_schema_patches(conn, version)

    # Backfill missing task numbers per context in id order.
    conn.execute(
        """
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY context_id ORDER BY id) AS rn
            FROM tasks
        )
        UPDATE tasks
        SET task_number = (
            SELECT rn FROM ordered WHERE ordered.id = tasks.id
        )
        WHERE task_number IS NULL;
        """
    )

    # Backfill: assign orphan contexts (user_id IS NULL) to the current OS user.
    orphan = conn.execute(
        "SELECT COUNT(*) AS n FROM contexts WHERE user_id IS NULL"
    ).fetchone()
    if orphan and orphan["n"] > 0:
        user_id = get_or_create_user(conn, get_os_user())
        conn.execute(
            "UPDATE contexts SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )
        # Migrate global_state -> user_state for this user.
        gs = conn.execute(
            "SELECT active_context_id FROM global_state WHERE id = 1"
        ).fetchone()
        if gs and gs["active_context_id"]:
            upsert_user_state(conn, user_id, gs["active_context_id"])


def upsert_global_state(conn: sqlite3.Connection, context_id: Optional[int]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO global_state (id, active_context_id, updated_at) VALUES (1, ?, ?)",
        (context_id, utc_now_iso()),
    )


def get_active_context_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT active_context_id FROM global_state WHERE id = 1"
    ).fetchone()
    if not row:
        return None
    return row["active_context_id"]


# ── User helpers ──

def get_os_user() -> str:
    """Return the current OS login name."""
    import os
    return os.environ.get("USER") or os.environ.get("USERNAME") or "default"


def get_or_create_user(conn: sqlite3.Connection, name: str) -> int:
    """Return user id, creating the row if it doesn't exist."""
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO users (name, created_at) VALUES (?, ?)",
        (name, utc_now_iso()),
    )
    return int(cur.lastrowid)


def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    """Return user dict or None."""
    row = conn.execute(
        "SELECT id, name, display_name, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def set_user_display_name(conn: sqlite3.Connection, user_id: int, display_name: str) -> dict:
    """Set display_name for a user. Returns updated user dict."""
    conn.execute(
        "UPDATE users SET display_name = ? WHERE id = ?",
        (display_name, user_id),
    )
    return get_user(conn, user_id)


def get_user_display(conn: sqlite3.Connection, user_id: int) -> str:
    """Return display_name if set, otherwise name."""
    row = conn.execute(
        "SELECT name, display_name FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return "unknown"
    return row["display_name"] or row["name"]


def upsert_user_state(conn: sqlite3.Connection, user_id: int, context_id: Optional[int]) -> None:
    """Set the active context for a user."""
    conn.execute(
        "INSERT OR REPLACE INTO user_state (user_id, active_context_id, updated_at) VALUES (?, ?, ?)",
        (user_id, context_id, utc_now_iso()),
    )


def get_active_context_id_for_user(conn: sqlite3.Connection, user_id: int) -> Optional[int]:
    """Get the active context for a specific user."""
    row = conn.execute(
        "SELECT active_context_id FROM user_state WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return row["active_context_id"]
