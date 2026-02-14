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


LATEST_SCHEMA_VERSION = 10


# ── Central DB path ──

def default_db_path() -> Path:
    """Return the central DB path (plan.db in this module's directory)."""
    return Path(__file__).resolve().parent / "plan.db"


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
        # Disable FK checks for migrations that recreate tables.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
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
        ctx_columns = {row["name"] for row in conn.execute("PRAGMA table_info(contexts)").fetchall()}
        if "project_id" in ctx_columns:
            set_schema_version(conn, LATEST_SCHEMA_VERSION)
            version = LATEST_SCHEMA_VERSION
        elif "is_deleted" in columns:
            set_schema_version(conn, 6)
            version = 6
        else:
            # Assume legacy DB; start at version 1 and apply patches.
            set_schema_version(conn, 1)
            version = 1

    if version < LATEST_SCHEMA_VERSION:
        version = apply_schema_patches(conn, version)

    # Post-patch indexes (safe to run after project_id column exists).
    ctx_columns = {row["name"] for row in conn.execute("PRAGMA table_info(contexts)").fetchall()}
    if "project_id" in ctx_columns:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contexts_project ON contexts(project_id);")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contexts_project_name ON contexts(project_id, name);")

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
            # Get project_id from the context to scope user_state correctly.
            ctx_row = conn.execute(
                "SELECT project_id FROM contexts WHERE id = ?",
                (gs["active_context_id"],),
            ).fetchone()
            project_id = ctx_row["project_id"] if ctx_row and ctx_row["project_id"] else None
            if project_id:
                upsert_user_state(conn, user_id, project_id, gs["active_context_id"])


    # Post-patch-9: split notes containing ## Goal / ## Plan headers into typed rows.
    cn_columns = {row["name"] for row in conn.execute("PRAGMA table_info(context_notes)").fetchall()}
    if "kind" in cn_columns:
        _backfill_goal_plan_notes(conn)


def _backfill_goal_plan_notes(conn: sqlite3.Connection) -> None:
    """Parse notes with ## Goal / ## Plan headers, split into typed rows, remove placeholders."""
    import re
    rows = conn.execute(
        "SELECT id, context_id, note_md, created_at, actor FROM context_notes "
        "WHERE kind = 'note' AND (note_md LIKE '%## Goal%' OR note_md LIKE '%## Plan%')"
    ).fetchall()
    if not rows:
        return

    now = utc_now_iso()
    for row in rows:
        text = row["note_md"]
        context_id = row["context_id"]
        created_at = row["created_at"]
        actor = row["actor"]

        # Extract sections
        goal_match = re.search(r'## Goal\s*\n(.*?)(?=\n## |\Z)', text, re.DOTALL)
        plan_match = re.search(r'## Plan\s*\n(.*?)(?=\n## |\Z)', text, re.DOTALL)

        if goal_match:
            goal_text = goal_match.group(1).strip()
            if goal_text:
                conn.execute(
                    "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) VALUES (?, ?, ?, ?, 'goal')",
                    (context_id, goal_text, created_at, actor),
                )
                # Remove migration placeholder for this context
                conn.execute(
                    "DELETE FROM context_notes WHERE context_id = ? AND kind = 'goal' AND note_md LIKE '(migrated%'",
                    (context_id,),
                )

        if plan_match:
            plan_text = plan_match.group(1).strip()
            if plan_text:
                conn.execute(
                    "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) VALUES (?, ?, ?, ?, 'plan')",
                    (context_id, plan_text, created_at, actor),
                )
                conn.execute(
                    "DELETE FROM context_notes WHERE context_id = ? AND kind = 'plan' AND note_md LIKE '(migrated%'",
                    (context_id,),
                )

        # Reclassify the original note — remove the ## Goal/## Plan sections, keep remainder as 'note'
        remainder = re.sub(r'## Goal\s*\n.*?(?=\n## |\Z)', '', text, flags=re.DOTALL)
        remainder = re.sub(r'## Plan\s*\n.*?(?=\n## |\Z)', '', remainder, flags=re.DOTALL)
        remainder = remainder.strip()
        if remainder:
            conn.execute("UPDATE context_notes SET note_md = ? WHERE id = ?", (remainder, row["id"]))
        else:
            conn.execute("DELETE FROM context_notes WHERE id = ?", (row["id"],))


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
    """Return the current OS login name, normalised to lowercase."""
    import os
    return (os.environ.get("USER") or os.environ.get("USERNAME") or "default").lower()


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


def upsert_user_state(conn: sqlite3.Connection, user_id: int, project_id: int, context_id: Optional[int]) -> None:
    """Set the active context for a user within a project."""
    conn.execute(
        "INSERT OR REPLACE INTO user_state (user_id, project_id, active_context_id, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, project_id, context_id, utc_now_iso()),
    )


def get_active_context_id_for_user(conn: sqlite3.Connection, user_id: int, project_id: int | None = None) -> Optional[int]:
    """Get the active context for a user, optionally scoped to a project."""
    if project_id is not None:
        row = conn.execute(
            "SELECT active_context_id FROM user_state WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT active_context_id FROM user_state WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return row["active_context_id"]


# ── Project helpers ──

def get_or_create_project(conn: sqlite3.Connection, absolute_path: str, project_name: str | None = None) -> int:
    """Return project id, creating the row if it doesn't exist."""
    row = conn.execute(
        "SELECT id FROM project WHERE absolute_path = ?",
        (absolute_path,),
    ).fetchone()
    if row:
        return int(row["id"])
    name = project_name or Path(absolute_path).name or "unnamed"
    cur = conn.execute(
        "INSERT INTO project (project_name, absolute_path, description_md, created_at) "
        "VALUES (?, ?, NULL, ?)",
        (name, absolute_path, utc_now_iso()),
    )
    return int(cur.lastrowid)


def get_project_by_id(conn: sqlite3.Connection, project_id: int) -> Optional[dict]:
    """Return project dict or None."""
    row = conn.execute(
        "SELECT id, project_name, absolute_path, description_md, created_at FROM project WHERE id = ?",
        (project_id,),
    ).fetchone()
    return dict(row) if row else None
