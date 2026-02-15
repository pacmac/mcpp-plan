#!/usr/bin/env python3
"""Tests for the backup.py safety pipeline.

Proves that:
1. Verified backups are created with correct checksums.
2. Trial migration on a copy catches data loss from destructive patches.
3. The live database is NEVER touched when trial migration fails.
4. safe_migrate aborts and reports clearly on data loss.
5. Non-destructive migrations pass through cleanly.

Usage:
    python test_backup.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

# Import backup module directly.
import importlib.util
MODULE_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("backup", MODULE_DIR / "backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def make_test_db(db_path: Path, schema_version: int = 6) -> None:
    """Create a test DB at the given schema version with real data.

    At version 6: contexts has user_id but NOT project_id (added by patch-7).
    The user_state is a simple user_id PK table (patch-7 recreates it as composite).
    The project table has a CHECK (id = 1) singleton constraint.

    This simulates a database that has data in contexts, user_state, and
    project tables — the exact tables that patch-7.sql's DROP TABLE
    statements would destroy.
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = OFF")

    # Create tables as they existed at version 6.
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE project (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            project_name TEXT NOT NULL,
            absolute_path TEXT NOT NULL UNIQUE,
            description_md TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            description_md TEXT,
            user_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE context_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_id INTEGER NOT NULL,
            note_md TEXT NOT NULL,
            created_at TEXT NOT NULL,
            actor TEXT,
            FOREIGN KEY (context_id) REFERENCES contexts(id)
        );

        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_id INTEGER NOT NULL,
            task_number INTEGER,
            title TEXT NOT NULL,
            description_md TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            is_deleted INTEGER NOT NULL DEFAULT 0,
            parent_id INTEGER,
            sort_index INTEGER,
            sub_index INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (context_id) REFERENCES contexts(id)
        );

        CREATE TABLE task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            note_md TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE context_state (
            context_id INTEGER PRIMARY KEY,
            active_task_id INTEGER,
            last_task_id INTEGER,
            next_step TEXT,
            status_label TEXT,
            last_event TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (context_id) REFERENCES contexts(id)
        );

        CREATE TABLE global_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_context_id INTEGER,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (active_context_id) REFERENCES contexts(id)
        );

        CREATE TABLE user_state (
            user_id INTEGER NOT NULL PRIMARY KEY,
            active_context_id INTEGER,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_id INTEGER,
            task_id INTEGER,
            action TEXT NOT NULL,
            details_md TEXT,
            created_at TEXT NOT NULL,
            actor TEXT,
            FOREIGN KEY (context_id) REFERENCES contexts(id)
        );
    """)

    # Insert real data — this is the data that would be LOST.
    conn.execute("INSERT INTO users (name, created_at) VALUES ('testuser', '2026-01-01T00:00:00')")
    conn.execute("INSERT INTO project (id, project_name, absolute_path, created_at) VALUES (1, 'myproject', '/test/project', '2026-01-01T00:00:00')")
    conn.execute("INSERT INTO contexts (name, status, user_id, created_at, updated_at) VALUES ('task-1', 'active', 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')")
    conn.execute("INSERT INTO contexts (name, status, user_id, created_at, updated_at) VALUES ('task-2', 'active', 1, '2026-01-02T00:00:00', '2026-01-02T00:00:00')")
    conn.execute("INSERT INTO contexts (name, status, user_id, created_at, updated_at) VALUES ('task-3', 'active', 1, '2026-01-03T00:00:00', '2026-01-03T00:00:00')")
    conn.execute("INSERT INTO tasks (context_id, title, status, created_at, updated_at) VALUES (1, 'Step A', 'planned', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO tasks (context_id, title, status, created_at, updated_at) VALUES (1, 'Step B', 'planned', '2026-01-01', '2026-01-01')")
    conn.execute("INSERT INTO tasks (context_id, title, status, created_at, updated_at) VALUES (2, 'Step C', 'complete', '2026-01-02', '2026-01-02')")
    conn.execute("INSERT INTO context_notes (context_id, note_md, created_at) VALUES (1, 'Important note', '2026-01-01')")
    conn.execute("INSERT INTO task_notes (task_id, note_md, created_at) VALUES (1, 'Task detail', '2026-01-01')")
    conn.execute("INSERT INTO context_state (context_id, active_task_id, updated_at) VALUES (1, 1, '2026-01-01')")
    conn.execute("INSERT INTO global_state (id, active_context_id, updated_at) VALUES (1, 1, '2026-01-01')")
    conn.execute("INSERT INTO user_state (user_id, active_context_id, updated_at) VALUES (1, 1, '2026-01-01')")
    conn.execute("INSERT INTO changelog (context_id, action, created_at) VALUES (1, 'created', '2026-01-01')")
    conn.execute("INSERT INTO changelog (context_id, action, created_at) VALUES (2, 'created', '2026-01-02')")

    conn.execute("INSERT INTO schema_version (id, version, updated_at) VALUES (1, ?, '2026-01-01')", (schema_version,))
    conn.close()


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

def test_sha256_file():
    """Test SHA-256 checksum of a file."""
    print("\n== sha256_file ==")
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    try:
        tmp.write_text("hello world")
        h = backup.sha256_file(tmp)
        report("returns hex string", len(h) == 64 and all(c in "0123456789abcdef" for c in h))
        # Same content = same hash.
        h2 = backup.sha256_file(tmp)
        report("deterministic", h == h2)
    finally:
        tmp.unlink(missing_ok=True)


def test_table_row_counts():
    """Test row count snapshot."""
    print("\n== table_row_counts ==")
    tmp = Path(tempfile.mktemp(suffix=".db"))
    try:
        make_test_db(tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        counts = backup.table_row_counts(conn)
        conn.close()

        report("users count", counts.get("users") == 1)
        report("project count", counts.get("project") == 1)
        report("contexts count", counts.get("contexts") == 3)
        report("tasks count", counts.get("tasks") == 3)
        report("context_notes count", counts.get("context_notes") == 1)
        report("task_notes count", counts.get("task_notes") == 1)
        report("changelog count", counts.get("changelog") == 2)
        report("user_state count", counts.get("user_state") == 1)
    finally:
        tmp.unlink(missing_ok=True)


def test_create_verified_backup():
    """Test that backup is created and checksum matches."""
    print("\n== create_verified_backup ==")
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = tmp_dir / "plan.db"
    try:
        make_test_db(db_path)
        backup_path = backup.create_verified_backup(db_path)
        report("backup file exists", backup_path.exists())
        report("backup in .backups dir", ".backups" in str(backup_path))

        # Verify checksums match.
        live_hash = backup.sha256_file(db_path)
        backup_hash = backup.sha256_file(backup_path)
        report("checksums match", live_hash == backup_hash)

        # Second backup gets different name.
        backup_path2 = backup.create_verified_backup(db_path)
        report("second backup different name", backup_path2 != backup_path)
        report("second backup exists", backup_path2.exists())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_validate_row_counts_catches_loss():
    """Test that validate_row_counts detects data loss."""
    print("\n== validate_row_counts (loss detection) ==")

    before = {"contexts": 3, "tasks": 3, "users": 1, "project": 1}
    after = {"contexts": 0, "tasks": 3, "users": 1, "project": 1}
    errors = backup.validate_row_counts(before, after)
    report("detects row loss", len(errors) == 1)
    report("names the table", "contexts" in errors[0])

    # Table disappeared entirely.
    after_missing = {"tasks": 3, "users": 1, "project": 1}
    errors = backup.validate_row_counts(before, after_missing)
    report("detects missing table", len(errors) == 1)
    report("reports MISSING", "MISSING" in errors[0])

    # No loss — should be clean.
    after_ok = {"contexts": 3, "tasks": 5, "users": 1, "project": 1}
    errors = backup.validate_row_counts(before, after_ok)
    report("no false positives", len(errors) == 0)


def test_safe_migrate_catches_destructive_patch():
    """CRITICAL TEST: Prove safe_migrate catches data destruction.

    Scenario 1: A purely destructive patch (DROP TABLE + empty replacement)
    simulates what patch-7.sql does when data doesn't carry over.

    Scenario 2: SQL error during trial migration (e.g., missing column)
    also aborts cleanly.
    """
    print("\n== safe_migrate catches destructive patch ==")

    tmp_dir = Path(tempfile.mkdtemp())
    db_path = tmp_dir / "plan.db"

    # Create a custom destructive patch that mirrors patch-7's behavior:
    # CREATE _new (empty) → DROP original → RENAME _new.
    destructive_patches_dir = tmp_dir / "patches"
    destructive_patches_dir.mkdir()
    (destructive_patches_dir / "patch-7.sql").write_text("""
        -- Destructive: recreate contexts without carrying data
        CREATE TABLE IF NOT EXISTS contexts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            description_md TEXT,
            user_id INTEGER,
            project_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        -- Intentionally skip INSERT to simulate data loss (stale _new table scenario)
        DROP TABLE IF EXISTS contexts;
        ALTER TABLE contexts_new RENAME TO contexts;
    """)

    try:
        make_test_db(db_path, schema_version=6)

        live_hash_before = backup.sha256_file(db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        counts_before = backup.table_row_counts(conn)
        conn.close()

        report("pre-migration: 3 contexts", counts_before.get("contexts") == 3)
        report("pre-migration: 3 tasks", counts_before.get("tasks") == 3)
        report("pre-migration: 1 user_state", counts_before.get("user_state") == 1)

        # Run safe_migrate — this MUST abort.
        aborted = False
        error_msg = ""
        try:
            backup.safe_migrate(db_path, 6, 7, destructive_patches_dir)
        except backup.MigrationAborted as exc:
            aborted = True
            error_msg = str(exc)

        report("migration ABORTED", aborted)
        report("error mentions data loss", "data loss" in error_msg.lower() or "lost rows" in error_msg.lower())
        report("error mentions backup", "backup" in error_msg.lower())

        # CRITICAL: Verify the live DB was NOT touched.
        live_hash_after = backup.sha256_file(db_path)
        report("live DB unchanged (hash match)", live_hash_before == live_hash_after)

        # Double-check: row counts in live DB are still intact.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        counts_after = backup.table_row_counts(conn)
        conn.close()

        report("live contexts still 3", counts_after.get("contexts") == 3)
        report("live tasks still 3", counts_after.get("tasks") == 3)
        report("live user_state still 1", counts_after.get("user_state") == 1)
        report("live changelog still 2", counts_after.get("changelog") == 2)

        # Verify backup was created.
        backups_dir = tmp_dir / ".backups"
        report("backup dir created", backups_dir.exists())
        backups = list(backups_dir.glob("plan.db.*"))
        report("backup file exists", len(backups) == 1)

        if backups:
            backup_hash = backup.sha256_file(backups[0])
            report("backup matches original", backup_hash == live_hash_before)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_safe_migrate_catches_sql_error():
    """Test that SQL errors during trial migration abort cleanly.

    Uses a custom patch with a deliberate SQL error to verify the
    safety pipeline catches it and leaves the live DB untouched.
    """
    print("\n== safe_migrate catches SQL error ==")

    tmp_dir = Path(tempfile.mkdtemp())
    db_path = tmp_dir / "plan.db"

    # Create a patches dir with a broken patch.
    bad_patches_dir = tmp_dir / "bad_patches"
    bad_patches_dir.mkdir()
    (bad_patches_dir / "patch-7.sql").write_text(
        "ALTER TABLE contexts ADD COLUMN nonexistent_ref REFERENCES no_such_table(id);\n"
        "SELECT * FROM completely_fake_table;\n"
    )

    try:
        make_test_db(db_path, schema_version=6)
        live_hash_before = backup.sha256_file(db_path)

        aborted = False
        error_msg = ""
        try:
            backup.safe_migrate(db_path, 6, 7, bad_patches_dir)
        except (backup.MigrationAborted, RuntimeError) as exc:
            aborted = True
            error_msg = str(exc)

        report("migration aborted on SQL error", aborted)

        # Live DB must be untouched.
        live_hash_after = backup.sha256_file(db_path)
        report("live DB unchanged after SQL error", live_hash_before == live_hash_after)

        # Backup should still exist.
        backups_dir = tmp_dir / ".backups"
        backups = list(backups_dir.glob("plan.db.*")) if backups_dir.exists() else []
        report("backup exists for recovery", len(backups) >= 1)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_safe_migrate_nondestructive():
    """Test that non-destructive migrations pass through cleanly."""
    print("\n== safe_migrate with non-destructive patches ==")

    tmp_dir = Path(tempfile.mkdtemp())
    db_path = tmp_dir / "plan.db"

    # Create a patches dir with only safe patches.
    safe_patches_dir = tmp_dir / "safe_patches"
    safe_patches_dir.mkdir()

    # Write a simple non-destructive patch.
    (safe_patches_dir / "patch-2.sql").write_text(
        "ALTER TABLE contexts ADD COLUMN extra_field TEXT;\n"
    )

    try:
        # Create a DB at version 1 with a minimal schema.
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.executescript("""
            CREATE TABLE contexts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO contexts (name, created_at) VALUES ('task-1', '2026-01-01');
            INSERT INTO contexts (name, created_at) VALUES ('task-2', '2026-01-02');
            INSERT INTO schema_version (id, version, updated_at) VALUES (1, 1, '2026-01-01');
        """)
        conn.close()

        # Run safe_migrate — should succeed.
        backup_path = backup.safe_migrate(db_path, 1, 2, safe_patches_dir)
        report("migration succeeded", True)
        report("backup created", backup_path.exists())

        # Verify the new column exists and data is intact.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(contexts)").fetchall()}
        count = conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0]
        version = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()["version"]
        conn.close()

        report("new column exists", "extra_field" in cols)
        report("data intact (2 rows)", count == 2)
        report("version updated to 2", version == 2)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_backup_missing_db():
    """Test that backup fails gracefully for missing DB."""
    print("\n== Edge: missing DB ==")
    try:
        backup.create_verified_backup(Path("/nonexistent/plan.db"))
        report("raises on missing DB", False, "should have raised")
    except RuntimeError as exc:
        report("raises on missing DB", "does not exist" in str(exc))


def test_ensure_schema_integration():
    """Test that db.py's ensure_schema uses the safety pipeline.

    Creates a pre-patch-7 DB and calls ensure_schema — with the fixed
    (non-destructive) patch-7, migration should SUCCEED and preserve
    all data.  A verified backup should be created.
    """
    print("\n== ensure_schema integration ==")

    # Import db module.
    db_spec = importlib.util.spec_from_file_location("db", MODULE_DIR / "db.py")
    db = importlib.util.module_from_spec(db_spec)

    # We need to handle relative imports in db.py.
    # Create a fake package so `from .backup import ...` works.
    import types
    pkg = types.ModuleType("mcpp_plan_test_pkg")
    pkg.__path__ = [str(MODULE_DIR)]
    import sys
    sys.modules["mcpp_plan_test_pkg"] = pkg
    sys.modules["mcpp_plan_test_pkg.backup"] = backup

    # Patch the relative import by modifying db.py's package reference.
    db.__package__ = "mcpp_plan_test_pkg"
    db_spec.loader.exec_module(db)

    tmp_dir = Path(tempfile.mkdtemp())
    db_path = tmp_dir / "plan.db"

    try:
        make_test_db(db_path, schema_version=6)

        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Record pre-state.
        counts_before = backup.table_row_counts(conn)
        conn.close()

        # Call ensure_schema — should succeed with fixed patches.
        conn = db.connect(db_path)
        error_msg = ""
        try:
            db.ensure_schema(conn)
        except RuntimeError as exc:
            error_msg = str(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        report("ensure_schema succeeded", error_msg == "", error_msg)

        # Verify all data is intact.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        counts_after = backup.table_row_counts(conn)
        conn.close()

        report("contexts preserved", counts_after.get("contexts", 0) >= counts_before.get("contexts", 0))
        report("tasks preserved", counts_after.get("tasks", 0) >= counts_before.get("tasks", 0))
        report("user_state preserved", counts_after.get("user_state", 0) >= counts_before.get("user_state", 0))

        # Verify backup was created.
        backups_dir = tmp_dir / ".backups"
        backups = list(backups_dir.glob("plan.db.*")) if backups_dir.exists() else []
        report("backup created during migration", len(backups) >= 1)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Clean up sys.modules.
        sys.modules.pop("mcpp_plan_test_pkg", None)
        sys.modules.pop("mcpp_plan_test_pkg.backup", None)


# ═══════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════

def main():
    print("backup.py safety pipeline tests")
    print(f"Module: {MODULE_DIR}")

    test_sha256_file()
    test_table_row_counts()
    test_create_verified_backup()
    test_validate_row_counts_catches_loss()
    test_safe_migrate_catches_destructive_patch()
    test_safe_migrate_catches_sql_error()
    test_safe_migrate_nondestructive()
    test_backup_missing_db()
    test_ensure_schema_integration()

    print(f"\n{'='*50}")
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")

    import sys
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
