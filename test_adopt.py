#!/usr/bin/env python3
"""Tests for task adopt (deep-copy) functionality.

Proves that:
1. adopt_context copies context, steps, context notes, and step notes.
2. Parent_id remapping works for nested steps.
3. Name collision raises error.
4. reset=True resets step statuses; reset=False preserves them.
5. Changelog entry is created with source info.
6. Self-adopt (clone) works when new_name is provided.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import sys
MODULE_DIR = Path(__file__).resolve().parent

# Import as package to handle relative imports
pkg_dir = MODULE_DIR.parent
pkg_name = MODULE_DIR.name
if str(pkg_dir) not in sys.path:
    sys.path.insert(0, str(pkg_dir))

import importlib
pkg = importlib.import_module(pkg_name)
ctx_mod = importlib.import_module(f"{pkg_name}.context")
db_mod = importlib.import_module(f"{pkg_name}.db")

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


def make_test_db():
    """Create a temporary DB with schema and seed data.

    Seeds:
    - project_id=1, user_id=1 (testuser/Test), user_id=2 (otheruser/Other)
    - context_id=1: "source-task" owned by user 2 with 3 steps (one nested),
      context notes (goal + plan), and step notes.
    - user 1 has no active context yet.
    """
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_plan.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    schema_sql = (MODULE_DIR / "schema.sql").read_text()
    conn.executescript(schema_sql)

    now = db_mod.utc_now_iso()

    # Project
    conn.execute(
        "INSERT INTO project (project_name, absolute_path, description_md, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("test-proj", "/tmp/test", "Test project", now),
    )

    # Users
    conn.execute(
        "INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
        ("testuser", "Test", now),
    )
    conn.execute(
        "INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
        ("otheruser", "Other", now),
    )

    # Source context owned by user 2
    conn.execute(
        "INSERT INTO contexts (name, description_md, user_id, project_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("source-task", "A source task to adopt", 2, 1, now, now),
    )
    conn.execute(
        "INSERT INTO context_state (context_id, active_task_id, updated_at) "
        "VALUES (?, ?, ?)",
        (1, None, now),
    )

    # Steps: step 1 (top-level), step 2 (child of step 1), step 3 (top-level, completed)
    conn.execute(
        "INSERT INTO tasks (context_id, task_number, title, status, is_deleted, parent_id, "
        "sort_index, sub_index, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, NULL, 1, NULL, ?, ?)",
        (1, 1, "Step one", "started", now, now),
    )
    conn.execute(
        "INSERT INTO tasks (context_id, task_number, title, status, is_deleted, parent_id, "
        "sort_index, sub_index, created_at, updated_at, completed_at) "
        "VALUES (?, ?, ?, ?, 0, NULL, 2, NULL, ?, ?, ?)",
        (1, 2, "Step two (complete)", "complete", now, now, now),
    )
    # Step 3: child of step 1 (parent_id = 1)
    conn.execute(
        "INSERT INTO tasks (context_id, task_number, title, status, is_deleted, parent_id, "
        "sort_index, sub_index, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 1, NULL, 1, ?, ?)",
        (1, 3, "Sub-step of one", "planned", now, now),
    )

    # Set active step
    conn.execute("UPDATE context_state SET active_task_id = 1 WHERE context_id = 1")

    # Context notes (goal + plan + note)
    conn.execute(
        "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Build the widget", now, "Other", "goal"),
    )
    conn.execute(
        "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Use TDD approach", now, "Other", "plan"),
    )
    conn.execute(
        "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Remember to test edge cases", now, "Other", "note"),
    )

    # Step notes on step 1
    conn.execute(
        "INSERT INTO task_notes (task_id, note_md, created_at, kind) VALUES (?, ?, ?, ?)",
        (1, "Step 1 implementation note", now, "note"),
    )

    # Set user 2 as active for the source context
    conn.execute(
        "INSERT INTO user_state (user_id, project_id, active_context_id, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (2, 1, 1, now),
    )

    conn.commit()
    return conn, tmp


def cleanup(tmp):
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── Test: basic adopt copies everything ──

def test_adopt_basic():
    """Adopt copies context, steps, context notes, and step notes."""
    print("\n== Basic adopt ==")
    conn, tmp = make_test_db()
    try:
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="my-copy",
            reset=True,
            user_id=1,
            project_id=1,
        )
        report("returns new context id", new_id is not None and new_id > 0, f"id={new_id}")

        # New context exists
        row = conn.execute("SELECT * FROM contexts WHERE id = ?", (new_id,)).fetchone()
        report("new context created", row is not None)
        report("new context name", row["name"] == "my-copy", f"name={row['name']}")
        report("owned by adopting user", row["user_id"] == 1, f"user_id={row['user_id']}")
        report("same project", row["project_id"] == 1)
        report("description copied", row["description_md"] == "A source task to adopt")

        # Steps copied
        steps = conn.execute(
            "SELECT * FROM tasks WHERE context_id = ? ORDER BY task_number",
            (new_id,),
        ).fetchall()
        report("3 steps copied", len(steps) == 3, f"count={len(steps)}")

        # All reset to planned (except active which is started)
        statuses = [s["status"] for s in steps]
        report("first step is started (active)", statuses[0] == "started")
        report("second step reset to planned", statuses[1] == "planned")
        report("third step reset to planned", statuses[2] == "planned")

        # Context notes copied (goal + plan + note = 3)
        notes = conn.execute(
            "SELECT * FROM context_notes WHERE context_id = ? ORDER BY id",
            (new_id,),
        ).fetchall()
        report("3 context notes copied", len(notes) == 3, f"count={len(notes)}")
        kinds = [n["kind"] for n in notes]
        report("goal note present", "goal" in kinds)
        report("plan note present", "plan" in kinds)
        report("note present", "note" in kinds)

        # Step notes copied
        new_step1_id = steps[0]["id"]
        step_notes = conn.execute(
            "SELECT * FROM task_notes WHERE task_id = ?",
            (new_step1_id,),
        ).fetchall()
        report("step note copied", len(step_notes) == 1, f"count={len(step_notes)}")
        report("step note content", step_notes[0]["note_md"] == "Step 1 implementation note")

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: parent_id remapping ──

def test_adopt_parent_remapping():
    """Parent_id references are remapped to new step IDs."""
    print("\n== Parent_id remapping ==")
    conn, tmp = make_test_db()
    try:
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="remapped",
            user_id=1,
            project_id=1,
        )

        steps = conn.execute(
            "SELECT id, task_number, parent_id FROM tasks WHERE context_id = ? ORDER BY task_number",
            (new_id,),
        ).fetchall()
        step1 = steps[0]
        step3 = steps[2]  # child of step 1

        report("step 1 has no parent", step1["parent_id"] is None)
        report("step 3 parent remapped to new step 1", step3["parent_id"] == step1["id"],
               f"parent_id={step3['parent_id']}, expected={step1['id']}")

        # Verify it's NOT pointing to the original step 1 (id=1)
        report("parent is not original id", step3["parent_id"] != 1 or step1["id"] == 1)

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: name collision ──

def test_adopt_name_collision():
    """Adopting with an existing name raises ValueError."""
    print("\n== Name collision ==")
    conn, tmp = make_test_db()
    try:
        # source-task already exists in project 1
        error = None
        try:
            ctx_mod.adopt_context(
                conn,
                source_name="source-task",
                new_name=None,  # will try to use "source-task"
                user_id=1,
                project_id=1,
            )
        except ValueError as e:
            error = str(e)

        report("raises ValueError", error is not None, f"error={error}")
        report("mentions name conflict", "already exists" in (error or ""))

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: reset=False preserves statuses ──

def test_adopt_no_reset():
    """reset=False preserves original step statuses."""
    print("\n== reset=False ==")
    conn, tmp = make_test_db()
    try:
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="no-reset",
            reset=False,
            user_id=1,
            project_id=1,
        )

        steps = conn.execute(
            "SELECT task_number, status FROM tasks WHERE context_id = ? ORDER BY task_number",
            (new_id,),
        ).fetchall()
        # Step 1 was "started" in source, but adopt sets first non-deleted as active (started)
        # Step 2 was "complete" — should stay complete
        # Step 3 was "planned" — should stay planned
        report("step 2 preserves complete", steps[1]["status"] == "complete",
               f"status={steps[1]['status']}")
        report("step 3 preserves planned", steps[2]["status"] == "planned",
               f"status={steps[2]['status']}")

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: changelog entry ──

def test_adopt_changelog():
    """Adopt creates a changelog entry with source info."""
    print("\n== Changelog entry ==")
    conn, tmp = make_test_db()
    try:
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="logged",
            user_id=1,
            project_id=1,
        )

        logs = conn.execute(
            "SELECT * FROM changelog WHERE context_id = ? ORDER BY id",
            (new_id,),
        ).fetchall()
        report("has changelog entries", len(logs) > 0, f"count={len(logs)}")

        adopt_entry = [l for l in logs if l["action"] == "Task Adopted"]
        report("has adopt entry", len(adopt_entry) == 1)
        report("mentions source user", "Other" in adopt_entry[0]["details_md"],
               f"details={adopt_entry[0]['details_md']}")
        report("mentions source name", "source-task" in adopt_entry[0]["details_md"])

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: self-adopt (clone) ──

def test_adopt_self_clone():
    """Adopting own task with new_name works as a clone."""
    print("\n== Self-clone ==")
    conn, tmp = make_test_db()
    try:
        # User 2 adopts their own task with a new name
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="cloned-task",
            user_id=2,
            project_id=1,
        )
        report("clone succeeds", new_id is not None and new_id > 0)

        row = conn.execute("SELECT user_id, name FROM contexts WHERE id = ?", (new_id,)).fetchone()
        report("owned by same user", row["user_id"] == 2)
        report("has new name", row["name"] == "cloned-task")

    finally:
        conn.close()
        cleanup(tmp)


# ── Test: sets active after adopt ──

def test_adopt_sets_active():
    """Adopted task becomes the active task."""
    print("\n== Sets active ==")
    conn, tmp = make_test_db()
    try:
        new_id = ctx_mod.adopt_context(
            conn,
            source_name="source-task",
            new_name="active-test",
            set_active=True,
            user_id=1,
            project_id=1,
        )

        # Check user_state
        us = conn.execute(
            "SELECT active_context_id FROM user_state WHERE user_id = 1 AND project_id = 1"
        ).fetchone()
        report("user_state updated", us is not None and us["active_context_id"] == new_id,
               f"active={us['active_context_id'] if us else None}, expected={new_id}")

        # Check context_state has active step
        cs = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (new_id,),
        ).fetchone()
        report("has active step", cs is not None and cs["active_task_id"] is not None)

    finally:
        conn.close()
        cleanup(tmp)


# ── Run all tests ──

if __name__ == "__main__":
    print("=== Adopt Tests ===")
    test_adopt_basic()
    test_adopt_parent_remapping()
    test_adopt_name_collision()
    test_adopt_no_reset()
    test_adopt_changelog()
    test_adopt_self_clone()
    test_adopt_sets_active()
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)
