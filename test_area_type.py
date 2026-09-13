#!/usr/bin/env python3
"""Tests for the areas `type` field.

`type` records HOW an area can be PROVEN, which `class` (product|tooling) cannot
say. Seven values, closed set, nullable, independent of class. See
specs/area-type-field.md.

Proves that:
1. LATEST_SCHEMA_VERSION is 22 and areas has a `type` column.
2. create_area round-trips a type through list_areas.
3. create_area rejects a value outside the closed set.
4. create_areas_batch sets type per item, and one bad type rolls the batch back.
5. update_area_description sets a type, and clears it.
6. An area created with no type reads back None — no default, no backfill.
7. area_stats and roadmap_all_data both carry the type.
8. Setting type leaves class alone, and does not change ordering.

The DB is NOT built from schema.sql alone: schema.sql has no areas table and sits
at schema version 9, so the patches must be applied on top of it. That is the real
migration path. Starting from 8 fails on `duplicate column name: kind`.

Usage:
    python3 test_area_type.py
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

SCHEMA_SQL_VERSION = 9   # what schema.sql itself represents; patches run from here

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


def check(name, fn):
    """Run one check. An exception is a FAIL naming the exception, never a crash."""
    try:
        ok, detail = fn()
        report(name, ok, detail)
    except Exception as e:
        report(name, False, f"{type(e).__name__}: {e}")


def make_test_db():
    """Temp DB at the latest schema, via schema.sql + the real patch sequence."""
    tmp = tempfile.mkdtemp()
    conn = sqlite3.connect(str(Path(tmp) / "test_plan.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript((MODULE_DIR / "schema.sql").read_text())
    db_mod.apply_schema_patches(conn, SCHEMA_SQL_VERSION)
    now = db_mod.utc_now_iso()
    conn.execute(
        "INSERT INTO project (project_name, absolute_path, description_md, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("test-proj", str(Path(tmp) / "workspace"), "Test project", now),
    )
    conn.commit()
    return conn, tmp


def main():
    print("Testing areas `type` field\n")
    conn, tmp = make_test_db()
    PID = 1
    try:
        # 1 — the column exists at the declared version
        def c1():
            cols = {r["name"] for r in conn.execute("PRAGMA table_xinfo(areas)")}
            v = db_mod.LATEST_SCHEMA_VERSION
            return ("type" in cols and v == 22,
                    f"LATEST_SCHEMA_VERSION={v}, areas columns={sorted(cols)}")
        check("schema: areas.type exists at version 22", c1)

        # 2 — round trip
        def c2():
            ctx_mod.create_area(conn, "gates", project_id=PID,
                                area_class="tooling", area_type="gate")
            got = [a for a in ctx_mod.list_areas(conn, project_id=PID)
                   if a["name"] == "gates"]
            if not got:
                return False, "area 'gates' not returned by list_areas"
            return got[0].get("type") == "gate", f"list_areas type={got[0].get('type')!r}"
        check("create_area: type round-trips through list_areas", c2)

        # 3 — closed set enforced
        def c3():
            try:
                ctx_mod.create_area(conn, "bogus", project_id=PID, area_type="nonsense")
            except ValueError as e:
                return True, f"rejected: {e}"
            return False, "'nonsense' was accepted as a type"
        check("create_area: a value outside the closed set is rejected", c3)

        # 4 — batch, and batch rollback
        def c4():
            ctx_mod.create_areas_batch(conn, [
                {"name": "codec", "type": "contract"},
                {"name": "sleep", "type": "firmware"},
            ], project_id=PID)
            by_name = {a["name"]: a for a in ctx_mod.list_areas(conn, project_id=PID)}
            got = (by_name.get("codec", {}).get("type"),
                   by_name.get("sleep", {}).get("type"))
            return got == ("contract", "firmware"), f"codec/sleep types={got}"
        check("create_areas_batch: type set per item", c4)

        def c4b():
            before = {a["name"] for a in ctx_mod.list_areas(conn, project_id=PID)}
            try:
                ctx_mod.create_areas_batch(conn, [
                    {"name": "good-one", "type": "library"},
                    {"name": "bad-one", "type": "not-a-type"},
                ], project_id=PID)
            except ValueError:
                pass
            after = {a["name"] for a in ctx_mod.list_areas(conn, project_id=PID)}
            return after == before, f"added despite the bad row: {sorted(after - before)}"
        check("create_areas_batch: one bad type rolls the whole batch back", c4b)

        # 5 — set and clear on an existing area
        def c5():
            err = ctx_mod.update_area_description(
                conn, "gates", project_id=PID, area_type="tool", _update_type=True)
            if err:
                return False, f"update returned {err!r}"
            got = {a["name"]: a for a in ctx_mod.list_areas(conn, project_id=PID)}
            return got["gates"].get("type") == "tool", f"type={got['gates'].get('type')!r}"
        check("update_area_description: sets a type on an existing area", c5)

        def c5b():
            err = ctx_mod.update_area_description(
                conn, "gates", project_id=PID, area_type=None, _update_type=True)
            if err:
                return False, f"update returned {err!r}"
            got = {a["name"]: a for a in ctx_mod.list_areas(conn, project_id=PID)}
            return got["gates"].get("type") is None, f"type={got['gates'].get('type')!r}"
        check("update_area_description: clears a type", c5b)

        # 6 — no default, no backfill
        def c6():
            ctx_mod.create_area(conn, "untyped-area", project_id=PID, area_class="product")
            got = {a["name"]: a for a in ctx_mod.list_areas(conn, project_id=PID)}
            return got["untyped-area"].get("type") is None, \
                f"type={got['untyped-area'].get('type')!r}"
        check("create_area: no type means NULL, not a default", c6)

        # 7 — the two aggregate readers carry it
        def c7():
            stats = ctx_mod.area_stats(conn, PID)
            by_name = {a["name"]: a for a in stats["areas"]}
            return by_name.get("codec", {}).get("type") == "contract", \
                f"area_stats codec type={by_name.get('codec', {}).get('type')!r}"
        check("area_stats: carries the type", c7)

        def c7b():
            data = ctx_mod.roadmap_all_data(conn, PID)
            by_name = {a["name"]: a for a in data["areas"]}
            return by_name.get("sleep", {}).get("type") == "firmware", \
                f"roadmap_all_data sleep type={by_name.get('sleep', {}).get('type')!r}"
        check("roadmap_all_data: carries the type", c7b)

        # 8 — independent of class, and ordering unmoved
        def c8():
            got = {a["name"]: a for a in ctx_mod.list_areas(conn, project_id=PID)}
            return got["gates"].get("class") == "tooling", \
                f"class={got['gates'].get('class')!r} after two type writes"
        check("type writes leave class alone", c8)

        def c8b():
            # codec/sleep/untyped-area are unclassed or product; gates is tooling.
            # E3: product first, then tooling, then unclassed — type must not disturb it.
            order = [a["name"] for a in ctx_mod.list_areas(conn, project_id=PID)]
            cls = {a["name"]: a.get("class")
                   for a in ctx_mod.list_areas(conn, project_id=PID)}
            rank = {"product": 0, "tooling": 1, None: 2}
            ranks = [rank[cls[n]] for n in order]
            return ranks == sorted(ranks), f"order={order}, ranks={ranks}"
        check("ordering is still product, tooling, unclassed", c8b)

    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    total = passed + failed
    print(f"\n{total} checks, {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
