#!/usr/bin/env python3
"""Tests for file attachment functionality.

Proves that:
1. Files can be attached to projects, tasks (contexts), and steps.
2. Exactly one target (project/context/task) must be set.
3. Absolute paths and path traversal are rejected.
4. Broken links are detected on list.
5. File content is read with correct truncation.
6. Detach removes the attachment by ID.
7. LATEST_SCHEMA_VERSION covers the attachments table.

Usage:
    python test_attachments.py
"""

from __future__ import annotations

import sqlite3
import tempfile
import shutil
from pathlib import Path
import sys

MODULE_DIR = Path(__file__).resolve().parent
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
    """Create a temp DB with schema and minimal seed data. Returns (conn, tmp_dir, workspace)."""
    tmp = tempfile.mkdtemp()
    workspace = Path(tmp) / "workspace"
    workspace.mkdir()
    db_path = Path(tmp) / "test_plan.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((MODULE_DIR / "schema.sql").read_text())
    now = db_mod.utc_now_iso()
    conn.execute(
        "INSERT INTO project (project_name, absolute_path, description_md, created_at) VALUES (?, ?, ?, ?)",
        ("test-proj", str(workspace), "Test project", now),
    )
    conn.execute(
        "INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
        ("testuser", "Test", now),
    )
    conn.execute(
        "INSERT INTO contexts (name, description_md, user_id, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("test-task", "A test task", 1, 1, now, now),
    )
    conn.execute(
        "INSERT INTO user_state (user_id, project_id, active_context_id, updated_at) VALUES (?, ?, ?, ?)",
        (1, 1, 1, now),
    )
    conn.execute(
        "INSERT INTO context_state (context_id, active_task_id, updated_at) VALUES (?, ?, ?)",
        (1, None, now),
    )
    conn.execute(
        "INSERT INTO tasks (context_id, task_number, sub_index, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 1, 1, "Step 1", "started", now, now),
    )
    conn.execute("UPDATE context_state SET active_task_id = 1 WHERE context_id = 1")
    conn.commit()
    return conn, tmp, str(workspace)


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)


# ── Schema ──

def test_schema_version():
    print("\n== Schema version ==")
    report("LATEST_SCHEMA_VERSION is 13", db_mod.LATEST_SCHEMA_VERSION == 13,
           f"got {db_mod.LATEST_SCHEMA_VERSION}")


def test_attachments_table_exists():
    print("\n== Attachments table ==")
    conn, tmp, ws = make_test_db()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        report("attachments table exists", "attachments" in tables)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(attachments)").fetchall()}
        for col in ("id", "file_path", "label", "kind", "project_id", "context_id", "task_id", "created_at"):
            report(f"column {col} exists", col in cols)
    finally:
        conn.close()
        cleanup(tmp)


# ── Attach / list / detach ──

def test_attach_to_project():
    print("\n== Attach to project ==")
    conn, tmp, ws = make_test_db()
    try:
        spec = Path(ws) / "spec.md"
        spec.write_text("# Spec\nLine 2.")
        r = ctx_mod.attach_file(conn, "spec.md", ws, label="My spec", kind="ref", project_id=1)
        report("returns id", isinstance(r["id"], int) and r["id"] > 0, f"id={r['id']}")
        report("file_path stored", r["file_path"] == "spec.md")
        lst = ctx_mod.list_attachments(conn, ws, project_id=1)
        report("lists one attachment", len(lst) == 1)
        report("not broken", lst[0]["broken"] is False)
        report("label preserved", lst[0]["label"] == "My spec")
    finally:
        conn.close()
        cleanup(tmp)


def test_attach_to_context():
    print("\n== Attach to task (context) ==")
    conn, tmp, ws = make_test_db()
    try:
        (Path(ws) / "task.md").write_text("Task spec.")
        ctx_mod.attach_file(conn, "task.md", ws, context_id=1)
        lst = ctx_mod.list_attachments(conn, ws, context_id=1)
        report("lists one attachment", len(lst) == 1)
        report("not broken", not lst[0]["broken"])
    finally:
        conn.close()
        cleanup(tmp)


def test_attach_to_step():
    print("\n== Attach to step (task row) ==")
    conn, tmp, ws = make_test_db()
    try:
        (Path(ws) / "step.md").write_text("Step spec.")
        ctx_mod.attach_file(conn, "step.md", ws, task_id=1)
        lst = ctx_mod.list_attachments(conn, ws, task_id=1)
        report("lists one attachment", len(lst) == 1)
        report("not broken", not lst[0]["broken"])
    finally:
        conn.close()
        cleanup(tmp)


def test_detach():
    print("\n== Detach ==")
    conn, tmp, ws = make_test_db()
    try:
        (Path(ws) / "x.md").write_text("x")
        r = ctx_mod.attach_file(conn, "x.md", ws, project_id=1)
        ctx_mod.detach_file(conn, r["id"])
        lst = ctx_mod.list_attachments(conn, ws, project_id=1)
        report("attachment removed", len(lst) == 0)
        try:
            ctx_mod.detach_file(conn, r["id"])
            report("detach missing raises", False, "should have raised")
        except ValueError:
            report("detach missing raises", True)
    finally:
        conn.close()
        cleanup(tmp)


# ── Validation ──

def test_multi_target_rejected():
    print("\n== Multi-target rejected ==")
    conn, tmp, ws = make_test_db()
    try:
        (Path(ws) / "f.md").write_text("x")
        try:
            ctx_mod.attach_file(conn, "f.md", ws, project_id=1, context_id=1)
            report("multi-target rejected", False, "should have raised")
        except ValueError:
            report("multi-target rejected", True)
        try:
            ctx_mod.attach_file(conn, "f.md", ws)
            report("no-target rejected", False, "should have raised")
        except ValueError:
            report("no-target rejected", True)
    finally:
        conn.close()
        cleanup(tmp)


def test_absolute_path_rejected():
    print("\n== Absolute path rejected ==")
    conn, tmp, ws = make_test_db()
    try:
        try:
            ctx_mod.attach_file(conn, "/etc/passwd", ws, project_id=1)
            report("absolute path rejected", False, "should have raised")
        except ValueError:
            report("absolute path rejected", True)
    finally:
        conn.close()
        cleanup(tmp)


def test_path_traversal_rejected():
    print("\n== Path traversal rejected ==")
    conn, tmp, ws = make_test_db()
    try:
        try:
            ctx_mod.attach_file(conn, "../etc/passwd", ws, project_id=1)
            report("traversal rejected", False, "should have raised")
        except ValueError:
            report("traversal rejected", True)
    finally:
        conn.close()
        cleanup(tmp)


# ── Broken link detection ──

def test_broken_link():
    print("\n== Broken link detection ==")
    conn, tmp, ws = make_test_db()
    try:
        ctx_mod.attach_file(conn, "missing.md", ws, project_id=1)
        lst = ctx_mod.list_attachments(conn, ws, project_id=1)
        report("broken flag set", lst[0]["broken"] is True)
    finally:
        conn.close()
        cleanup(tmp)


# ── Content reading ──

def test_content_reading():
    print("\n== Content reading ==")
    conn, tmp, ws = make_test_db()
    try:
        f = Path(ws) / "long.md"
        f.write_text("\n".join(f"Line {i}" for i in range(1, 201)))

        c = ctx_mod.read_attachment_content("long.md", ws, max_lines=50)
        report("not broken", not c["broken"])
        report("truncated flag set", c["truncated"] is True)
        report("line_count correct", c["line_count"] == 200, f"got {c['line_count']}")
        report("content capped at 50 lines", c["content"].count("\n") == 49)

        c2 = ctx_mod.read_attachment_content("long.md", ws, max_lines=300)
        report("no truncation within limit", c2["truncated"] is False)

        c3 = ctx_mod.read_attachment_content("missing.md", ws)
        report("missing file returns broken", c3["broken"] is True)
        report("missing file content is None", c3["content"] is None)
    finally:
        conn.close()
        cleanup(tmp)


# ── Run all tests ──

if __name__ == "__main__":
    test_schema_version()
    test_attachments_table_exists()
    test_attach_to_project()
    test_attach_to_context()
    test_attach_to_step()
    test_detach()
    test_multi_target_rejected()
    test_absolute_path_rejected()
    test_path_traversal_rejected()
    test_broken_link()
    test_content_reading()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
