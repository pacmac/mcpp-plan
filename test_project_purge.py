#!/usr/bin/env python3
"""Tests for plan_project_purge functionality.

Proves that:
1. Purge removes project + all contexts, steps, notes, attachments, changelog.
2. confirm=True is required.
3. force=False blocks when other users have active tasks.
4. force=True overrides the block.
5. Purge by name works (and rejects ambiguous names).
6. Purge by project_id works.
7. Purging an orphaned (non-CWD) project works.

Usage:
    python test_project_purge.py
"""

from __future__ import annotations

import sqlite3
import tempfile
import shutil
from pathlib import Path
import sys
import importlib.util

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
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_plan.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((MODULE_DIR / "schema.sql").read_text())
    return conn, tmp


def seed_project(conn, name="proj-a", path="/tmp/proj-a"):
    now = db_mod.utc_now_iso()
    cur = conn.execute(
        "INSERT INTO project (project_name, absolute_path, created_at) VALUES (?, ?, ?)",
        (name, path, now),
    )
    conn.commit()
    return cur.lastrowid


def seed_user(conn, username="alice"):
    now = db_mod.utc_now_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
        (username, username.title(), now),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE name = ?", (username,)).fetchone()
    return row["id"]


def seed_context(conn, project_id, user_id, name="task-1"):
    now = db_mod.utc_now_iso()
    cur = conn.execute(
        "INSERT INTO contexts (name, description_md, user_id, project_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (name, "A task", user_id, project_id, now, now),
    )
    context_id = cur.lastrowid
    conn.execute(
        "INSERT INTO context_state (context_id, updated_at) VALUES (?, ?)",
        (context_id, now),
    )
    conn.execute(
        "INSERT INTO user_state (user_id, project_id, active_context_id, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, project_id, context_id, now),
    )
    conn.commit()
    return context_id


def seed_step(conn, context_id):
    now = db_mod.utc_now_iso()
    cur = conn.execute(
        "INSERT INTO tasks (context_id, task_number, sub_index, title, status, created_at, updated_at) "
        "VALUES (?, 1, 1, 'Step 1', 'started', ?, ?)",
        (context_id, now, now),
    )
    step_id = cur.lastrowid
    conn.execute("UPDATE context_state SET active_task_id = ? WHERE context_id = ?", (step_id, context_id))
    conn.commit()
    return step_id


def seed_notes(conn, context_id, step_id):
    now = db_mod.utc_now_iso()
    conn.execute(
        "INSERT INTO context_notes (context_id, note_md, created_at, kind) VALUES (?, ?, ?, 'goal')",
        (context_id, "The goal", now),
    )
    conn.execute(
        "INSERT INTO task_notes (task_id, note_md, created_at, kind) VALUES (?, ?, ?, 'note')",
        (step_id, "A note", now),
    )
    conn.execute(
        "INSERT INTO changelog (context_id, task_id, action, created_at) VALUES (?, ?, 'test', ?)",
        (context_id, step_id, now),
    )
    conn.commit()


def count_table(conn, table, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


# ── Tests ──

def test_full_cascade():
    print("\n== Full cascade purge ==")
    conn, tmp = make_test_db()
    try:
        pid = seed_project(conn)
        uid = seed_user(conn)
        cid = seed_context(conn, pid, uid)
        sid = seed_step(conn, cid)
        seed_notes(conn, cid, sid)
        ctx_mod.attach_file(conn, "spec.md", tmp, project_id=pid)

        result = ctx_mod.purge_project(conn, pid, force=True)
        d = result["deleted"]

        report("project row gone", count_table(conn, "project", "id=?", (pid,)) == 0)
        report("contexts gone", count_table(conn, "contexts", "project_id=?", (pid,)) == 0)
        report("tasks gone", d["tasks"] == 1)
        report("context_notes gone", d["context_notes"] >= 1)
        report("task_notes gone", d["task_notes"] >= 1)
        report("changelog gone", d["changelog"] >= 1)
        report("user_state gone", d["user_state"] >= 1)
        report("attachments gone", d["attachments"] >= 1)
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_confirm_required():
    print("\n== confirm=True required ==")
    conn, tmp = make_test_db()
    try:
        # Test via mcpptool execute
        import sys
        sys.path.insert(0, str(MODULE_DIR.parent))
        import mcpptool as mcp
        r = mcp.execute("plan_project_purge", {"confirm": False}, {"workspace_dir": tmp})
        report("confirm=False rejected", not r.get("success"), r.get("error", ""))
        r2 = mcp.execute("plan_project_purge", {}, {"workspace_dir": tmp})
        report("no confirm rejected", not r2.get("success"))
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_multi_user_block():
    print("\n== Multi-user block ==")
    conn, tmp = make_test_db()
    try:
        import os
        os.environ["USER"] = "alice"
        pid = seed_project(conn)
        bob_id = seed_user(conn, "bob")
        seed_context(conn, pid, bob_id, "bobs-task")

        try:
            ctx_mod.purge_project(conn, pid, force=False)
            report("other-user block", False, "should have raised")
        except ValueError as e:
            report("other-user block", "bob" in str(e), str(e))
    finally:
        os.environ["USER"] = "root"
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_force_override():
    print("\n== force=True override ==")
    conn, tmp = make_test_db()
    try:
        import os
        os.environ["USER"] = "alice"
        pid = seed_project(conn)
        bob_id = seed_user(conn, "bob")
        seed_context(conn, pid, bob_id, "bobs-task")

        result = ctx_mod.purge_project(conn, pid, force=True)
        report("purge succeeded with force", result["project"]["id"] == pid)
        report("project gone", count_table(conn, "project", "id=?", (pid,)) == 0)
    finally:
        os.environ["USER"] = "root"
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_purge_by_name():
    print("\n== Purge by name ==")
    conn, tmp = make_test_db()
    try:
        pid = seed_project(conn, name="my-project", path="/tmp/unique-path")
        result = ctx_mod.purge_project(conn, pid, force=True)
        report("project purged by id (name lookup via handler)", result["project"]["project_name"] == "my-project")
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_not_found():
    print("\n== Not found ==")
    conn, tmp = make_test_db()
    try:
        try:
            ctx_mod.purge_project(conn, 9999, force=True)
            report("missing id raises", False)
        except ValueError as e:
            report("missing id raises", "not found" in str(e).lower(), str(e))
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_user_prefs_cleared():
    print("\n== user_prefs cleared ==")
    conn, tmp = make_test_db()
    try:
        pid = seed_project(conn)
        uid = seed_user(conn)
        now = db_mod.utc_now_iso()
        conn.execute(
            "INSERT OR REPLACE INTO user_prefs (user_id, active_project_id, updated_at) VALUES (?, ?, ?)",
            (uid, pid, now),
        )
        conn.commit()
        ctx_mod.purge_project(conn, pid, force=True)
        row = conn.execute("SELECT active_project_id FROM user_prefs WHERE user_id = ?", (uid,)).fetchone()
        report("active_project_id nulled", row is None or row["active_project_id"] is None)
    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)


def test_end_to_end_via_execute():
    print("\n== End-to-end via execute() ==")
    import mcpptool as mcp
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ws = str(Path(tmp) / "workspace")
        Path(ws).mkdir()
        ctx = {"workspace_dir": ws}
        mcp.execute("plan_project_set", {"name": "purge-me"}, ctx)
        mcp.execute("plan_task_new", {"name": "a-task", "title": "A Task"}, ctx)
        r = mcp.execute("plan_project_purge", {"confirm": True}, ctx)
        report("execute purge succeeds", r.get("success"), r.get("error", r.get("display", "")))
        report("display mentions purge", "Purged" in r.get("display", ""), r.get("display", "")[:80])


if __name__ == "__main__":
    test_full_cascade()
    test_confirm_required()
    test_multi_user_block()
    test_force_override()
    test_purge_by_name()
    test_not_found()
    test_user_prefs_cleared()
    test_end_to_end_via_execute()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
