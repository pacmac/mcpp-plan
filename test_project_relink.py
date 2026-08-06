#!/usr/bin/env python3
"""Tests for relinking projects after a workspace move/rename."""

from __future__ import annotations

import importlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
pkg_dir = MODULE_DIR.parent
pkg_name = MODULE_DIR.name
if str(pkg_dir) not in sys.path:
    sys.path.insert(0, str(pkg_dir))

importlib.import_module(pkg_name)
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((MODULE_DIR / "schema.sql").read_text())
    return conn, tmp


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)


def add_project(conn, name, path, description=None):
    conn.execute(
        "INSERT INTO project (project_name, absolute_path, description_md, created_at) "
        "VALUES (?, ?, ?, ?)",
        (name, path, description, db_mod.utc_now_iso()),
    )
    return conn.execute(
        "SELECT id FROM project WHERE absolute_path = ?",
        (path,),
    ).fetchone()["id"]


def add_user(conn):
    conn.execute(
        "INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
        ("testuser", "Test", db_mod.utc_now_iso()),
    )
    return conn.execute("SELECT id FROM users WHERE name = 'testuser'").fetchone()["id"]


def add_task(conn, project_id, user_id, name="task"):
    now = db_mod.utc_now_iso()
    conn.execute(
        "INSERT INTO contexts (name, description_md, user_id, project_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, "Task", user_id, project_id, now, now),
    )
    context_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO user_state (user_id, project_id, active_context_id, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, project_id, context_id, now),
    )
    return context_id


def test_relink_by_old_path():
    print("\n== Relink by old path ==")
    conn, tmp = make_test_db()
    try:
        project_id = add_project(conn, "moved", "/old/path", "Description")
        result = ctx_mod.relink_project(conn, old_path="/old/path", new_path="/new/path")
        report("same project id", result["id"] == project_id, f"id={result['id']}")
        report("path updated", result["absolute_path"] == "/new/path", result["absolute_path"])
        report("description preserved", result["description_md"] == "Description")
        report("old path gone", ctx_mod.get_project(conn, absolute_path="/old/path") is None)
    finally:
        conn.close()
        cleanup(tmp)


def test_relink_removes_empty_placeholder():
    print("\n== Relink removes empty placeholder ==")
    conn, tmp = make_test_db()
    try:
        source_id = add_project(conn, "real", "/old/path")
        placeholder_id = add_project(conn, "placeholder", "/new/path")
        result = ctx_mod.relink_project(conn, project_id=source_id, new_path="/new/path")
        report("source owns new path", result["id"] == source_id)
        missing = ctx_mod.get_project(conn, project_id=placeholder_id) is None
        report("placeholder deleted", missing)
    finally:
        conn.close()
        cleanup(tmp)


def test_relink_rejects_occupied_target():
    print("\n== Relink rejects occupied target ==")
    conn, tmp = make_test_db()
    try:
        user_id = add_user(conn)
        source_id = add_project(conn, "real", "/old/path")
        target_id = add_project(conn, "occupied", "/new/path")
        add_task(conn, target_id, user_id, "occupied-task")
        try:
            ctx_mod.relink_project(conn, project_id=source_id, new_path="/new/path")
            report("raises on occupied target", False, "no exception")
        except ValueError as exc:
            report("raises on occupied target", "already uses that path" in str(exc), str(exc))
        report("target still exists", ctx_mod.get_project(conn, project_id=target_id) is not None)
    finally:
        conn.close()
        cleanup(tmp)


def test_relink_rejects_ambiguous_name():
    print("\n== Relink rejects ambiguous name ==")
    conn, tmp = make_test_db()
    try:
        add_project(conn, "same", "/one")
        add_project(conn, "same", "/two")
        try:
            ctx_mod.relink_project(conn, name="same", new_path="/three")
            report("raises on ambiguous name", False, "no exception")
        except ValueError as exc:
            report("raises on ambiguous name", "ambiguous" in str(exc), str(exc))
    finally:
        conn.close()
        cleanup(tmp)


def test_relink_requires_one_selector():
    print("\n== Relink selector validation ==")
    conn, tmp = make_test_db()
    try:
        try:
            ctx_mod.relink_project(conn, new_path="/new")
            report("raises on no selector", False, "no exception")
        except ValueError as exc:
            report("raises on no selector", "exactly one" in str(exc), str(exc))
        try:
            ctx_mod.relink_project(conn, project_id=1, old_path="/old", new_path="/new")
            report("raises on multiple selectors", False, "no exception")
        except ValueError as exc:
            report("raises on multiple selectors", "exactly one" in str(exc), str(exc))
    finally:
        conn.close()
        cleanup(tmp)


if __name__ == "__main__":
    print("Running project relink tests...")
    test_relink_by_old_path()
    test_relink_removes_empty_placeholder()
    test_relink_rejects_occupied_target()
    test_relink_rejects_ambiguous_name()
    test_relink_requires_one_selector()
    print(f"\nResult: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
