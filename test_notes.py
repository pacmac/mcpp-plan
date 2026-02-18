#!/usr/bin/env python3
"""Tests for notes upsert and delete functionality.

Proves that:
1. Context notes upsert by kind (goal/plan replace existing, note appends).
2. Task notes upsert by optional ID (update when ID given, insert when not).
3. Delete works at both context and task note levels.
4. Note IDs are returned in list output.
5. Step notes inherit upsert/delete from task notes.
6. Show/switch responses include notes with IDs.

Usage:
    python test_notes.py
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
    """Create a temporary DB with schema and seed data."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_plan.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Read and apply the full schema
    schema_sql = (MODULE_DIR / "schema.sql").read_text()
    conn.executescript(schema_sql)

    # Seed: project, user, context
    conn.execute("INSERT INTO project (project_name, absolute_path, description_md, created_at) VALUES (?, ?, ?, ?)",
                 ("test-proj", "/tmp/test", "Test project", db_mod.utc_now_iso()))
    conn.execute("INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
                 ("testuser", "Test", db_mod.utc_now_iso()))
    now = db_mod.utc_now_iso()
    conn.execute("INSERT INTO contexts (name, description_md, user_id, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                 ("test-task", "A test task", 1, 1, now, now))
    conn.execute("INSERT INTO user_state (user_id, project_id, active_context_id, updated_at) VALUES (?, ?, ?, ?)",
                 (1, 1, 1, now))
    conn.execute("INSERT INTO context_state (context_id, active_task_id, updated_at) VALUES (?, ?, ?)",
                 (1, None, now))

    # Add a task (step) for task note testing
    conn.execute("INSERT INTO tasks (context_id, task_number, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (1, 1, "Step 1", "started", db_mod.utc_now_iso(), db_mod.utc_now_iso()))
    conn.execute("UPDATE context_state SET active_task_id = 1 WHERE context_id = 1")

    conn.commit()
    return conn, tmp


def cleanup(tmp):
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ── Context note tests ──

def test_context_note_insert():
    """Adding a goal note creates it."""
    print("\n== Context note insert ==")
    conn, tmp = make_test_db()
    try:
        note_id = ctx_mod.add_context_note(conn, "First goal", user_id=1, project_id=1, kind="goal")
        report("returns note id", note_id is not None and note_id > 0, f"id={note_id}")

        notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1)
        report("one note exists", len(notes) == 1, f"count={len(notes)}")
        report("note has id field", "id" in notes[0], str(notes[0].keys()))
        report("correct text", notes[0]["note"] == "First goal")
        report("correct kind", notes[0]["kind"] == "goal")
    finally:
        conn.close()
        cleanup(tmp)


def test_context_note_upsert_by_kind():
    """Setting goal twice replaces the first one."""
    print("\n== Context note upsert by kind ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_context_note(conn, "First goal", user_id=1, project_id=1, kind="goal")
        id2 = ctx_mod.add_context_note(conn, "Updated goal", user_id=1, project_id=1, kind="goal")
        report("same id returned", id1 == id2, f"id1={id1}, id2={id2}")

        notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1, kind="goal")
        report("still one goal", len(notes) == 1, f"count={len(notes)}")
        report("text updated", notes[0]["note"] == "Updated goal")

        # Plan should also upsert
        ctx_mod.add_context_note(conn, "First plan", user_id=1, project_id=1, kind="plan")
        ctx_mod.add_context_note(conn, "Updated plan", user_id=1, project_id=1, kind="plan")
        plan_notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1, kind="plan")
        report("still one plan", len(plan_notes) == 1, f"count={len(plan_notes)}")
        report("plan text updated", plan_notes[0]["note"] == "Updated plan")
    finally:
        conn.close()
        cleanup(tmp)


def test_context_note_kind_note_appends():
    """Regular 'note' kind still appends (no upsert by kind)."""
    print("\n== Context note kind=note appends ==")
    conn, tmp = make_test_db()
    try:
        ctx_mod.add_context_note(conn, "Note one", user_id=1, project_id=1, kind="note")
        ctx_mod.add_context_note(conn, "Note two", user_id=1, project_id=1, kind="note")
        notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1, kind="note")
        report("two notes exist", len(notes) == 2, f"count={len(notes)}")
    finally:
        conn.close()
        cleanup(tmp)


def test_context_note_upsert_by_id():
    """Updating a note kind='note' by ID works."""
    print("\n== Context note upsert by ID ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_context_note(conn, "Original", user_id=1, project_id=1, kind="note")
        id2 = ctx_mod.add_context_note(conn, "Edited", user_id=1, project_id=1, kind="note", note_id=id1)
        report("same id returned", id1 == id2, f"id1={id1}, id2={id2}")

        notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1, kind="note")
        report("still one note", len(notes) == 1, f"count={len(notes)}")
        report("text updated", notes[0]["note"] == "Edited")
    finally:
        conn.close()
        cleanup(tmp)


def test_context_note_delete():
    """Deleting a context note removes it."""
    print("\n== Context note delete ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_context_note(conn, "To delete", user_id=1, project_id=1, kind="note")
        ctx_mod.delete_context_note(conn, id1)
        notes = ctx_mod.list_context_notes(conn, user_id=1, project_id=1, kind="note")
        report("note deleted", len(notes) == 0, f"count={len(notes)}")

        # Deleting non-existent note raises
        try:
            ctx_mod.delete_context_note(conn, 99999)
            report("raises on missing", False, "no exception raised")
        except ValueError:
            report("raises on missing", True)
    finally:
        conn.close()
        cleanup(tmp)


# ── Task note tests ──

def test_task_note_insert():
    """Adding a task note creates it with ID."""
    print("\n== Task note insert ==")
    conn, tmp = make_test_db()
    try:
        note_id = ctx_mod.add_task_note(conn, "A task note", user_id=1, project_id=1)
        report("returns note id", note_id is not None and note_id > 0, f"id={note_id}")

        notes = ctx_mod.list_task_notes(conn, user_id=1, project_id=1)
        report("one note exists", len(notes) == 1, f"count={len(notes)}")
        report("note has id field", "id" in notes[0], str(notes[0].keys()))
        report("correct text", notes[0]["note"] == "A task note")
    finally:
        conn.close()
        cleanup(tmp)


def test_task_note_upsert_by_id():
    """Updating a task note by ID replaces it."""
    print("\n== Task note upsert by ID ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_task_note(conn, "Original", user_id=1, project_id=1)
        id2 = ctx_mod.add_task_note(conn, "Updated", user_id=1, project_id=1, note_id=id1)
        report("same id returned", id1 == id2, f"id1={id1}, id2={id2}")

        notes = ctx_mod.list_task_notes(conn, user_id=1, project_id=1)
        report("still one note", len(notes) == 1, f"count={len(notes)}")
        report("text updated", notes[0]["note"] == "Updated")
    finally:
        conn.close()
        cleanup(tmp)


def test_task_note_append_without_id():
    """Without ID, task notes append."""
    print("\n== Task note append without ID ==")
    conn, tmp = make_test_db()
    try:
        ctx_mod.add_task_note(conn, "Note one", user_id=1, project_id=1)
        ctx_mod.add_task_note(conn, "Note two", user_id=1, project_id=1)
        notes = ctx_mod.list_task_notes(conn, user_id=1, project_id=1)
        report("two notes exist", len(notes) == 2, f"count={len(notes)}")
    finally:
        conn.close()
        cleanup(tmp)


def test_task_note_delete():
    """Deleting a task note removes it."""
    print("\n== Task note delete ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_task_note(conn, "To delete", user_id=1, project_id=1)
        ctx_mod.delete_task_note(conn, id1)
        notes = ctx_mod.list_task_notes(conn, user_id=1, project_id=1)
        report("note deleted", len(notes) == 0, f"count={len(notes)}")

        try:
            ctx_mod.delete_task_note(conn, 99999)
            report("raises on missing", False, "no exception raised")
        except ValueError:
            report("raises on missing", True)
    finally:
        conn.close()
        cleanup(tmp)


# ── Step note tests (adapter layer) ──

def test_step_note_upsert():
    """Step notes use task note upsert via adapter."""
    print("\n== Step note upsert via adapter ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_step_note(conn, "Original step note", step_number=1, user_id=1, project_id=1)
        id2 = ctx_mod.add_step_note(conn, "Updated step note", step_number=1, user_id=1, project_id=1, note_id=id1)
        report("same id returned", id1 == id2, f"id1={id1}, id2={id2}")

        notes = ctx_mod.list_step_notes(conn, step_number=1, user_id=1, project_id=1)
        report("still one note", len(notes) == 1, f"count={len(notes)}")
        report("text updated", notes[0]["note"] == "Updated step note")
    finally:
        conn.close()
        cleanup(tmp)


def test_step_note_delete():
    """Step note delete works via adapter."""
    print("\n== Step note delete via adapter ==")
    conn, tmp = make_test_db()
    try:
        id1 = ctx_mod.add_step_note(conn, "To delete", step_number=1, user_id=1, project_id=1)
        ctx_mod.delete_step_note(conn, id1)
        notes = ctx_mod.list_step_notes(conn, step_number=1, user_id=1, project_id=1)
        report("note deleted", len(notes) == 0, f"count={len(notes)}")
    finally:
        conn.close()
        cleanup(tmp)


# ── Show/switch include notes ──

def test_step_summary_includes_notes():
    """get_step_summary (used by show/switch) includes notes with IDs."""
    print("\n== Step summary includes notes ==")
    conn, tmp = make_test_db()
    try:
        ctx_mod.add_task_note(conn, "A note on step 1", user_id=1, project_id=1)
        result = ctx_mod.get_task_summary(conn, task_number=1, user_id=1, project_id=1)
        report("has notes key", "notes" in result, str(result.keys()))
        report("notes not empty", len(result["notes"]) > 0, f"count={len(result.get('notes', []))}")
        report("note has id", "id" in result["notes"][0])
        report("correct text", result["notes"][0]["note"] == "A note on step 1")
    finally:
        conn.close()
        cleanup(tmp)


def test_plan_show_includes_notes():
    """get_plan_show (used by task show) includes notes with IDs."""
    print("\n== Plan show includes notes ==")
    conn, tmp = make_test_db()
    try:
        ctx_mod.add_context_note(conn, "The goal", user_id=1, project_id=1, kind="goal")
        result = ctx_mod.get_plan_show(conn, user_id=1, project_id=1)
        report("has notes key", "notes" in result, str(result.keys()))
        report("notes not empty", len(result["notes"]) > 0, f"count={len(result.get('notes', []))}")
        report("note has id", "id" in result["notes"][0])
    finally:
        conn.close()
        cleanup(tmp)


# ── Changelog tracking ──

def test_changelog_tracks_updates():
    """Upsert and delete create appropriate changelog entries."""
    print("\n== Changelog tracking ==")
    conn, tmp = make_test_db()
    try:
        ctx_mod.add_context_note(conn, "First goal", user_id=1, project_id=1, kind="goal")
        ctx_mod.add_context_note(conn, "Updated goal", user_id=1, project_id=1, kind="goal")

        logs = conn.execute("SELECT action FROM changelog ORDER BY id").fetchall()
        actions = [r["action"] for r in logs]
        report("added logged", "Context Note Added" in actions)
        report("updated logged", "Context Note Updated" in actions)

        note_id = ctx_mod.add_context_note(conn, "To delete", user_id=1, project_id=1, kind="note")
        ctx_mod.delete_context_note(conn, note_id)
        logs = conn.execute("SELECT action FROM changelog ORDER BY id").fetchall()
        actions = [r["action"] for r in logs]
        report("deleted logged", "Context Note Deleted" in actions)
    finally:
        conn.close()
        cleanup(tmp)


if __name__ == "__main__":
    test_context_note_insert()
    test_context_note_upsert_by_kind()
    test_context_note_kind_note_appends()
    test_context_note_upsert_by_id()
    test_context_note_delete()
    test_task_note_insert()
    test_task_note_upsert_by_id()
    test_task_note_append_without_id()
    test_task_note_delete()
    test_step_note_upsert()
    test_step_note_delete()
    test_step_summary_includes_notes()
    test_plan_show_includes_notes()
    test_changelog_tracks_updates()

    print(f"\n{'=' * 50}")
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        exit(1)
