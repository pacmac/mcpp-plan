# Spec: fix-batch-area-atomicity

## Bug (reported by roadmap, [batch-area-new-is-not-atomic])

`create_areas_batch()` commits each INSERT immediately because the DB connection
uses `isolation_level=None` (autocommit mode). In autocommit mode `conn.commit()`
is a no-op — each statement runs in its own implicit transaction. A batch that
fails on item N leaves items 0..N-1 permanently inserted and the caller is told
the batch failed with no indication that part succeeded.

The retry scenario makes this worse: retrying the fixed batch collides on the
rows created by the first attempt, giving "already exists" errors for areas
nobody knowingly created.

## Root cause

`db.connect()` sets `isolation_level=None`:
```python
conn = sqlite3.connect(db_path, isolation_level=None)
```

In this mode explicit transactions require `BEGIN` / `COMMIT` / `ROLLBACK`
statements — `conn.commit()` and `conn.rollback()` are no-ops.

## Fix

Wrap the `create_areas_batch` body in an explicit savepoint (safe even when
called inside an already-open transaction, which `BEGIN` is not):

```python
conn.execute("SAVEPOINT batch_area_new")
try:
    # all validation + inserts
    conn.execute("RELEASE batch_area_new")
    return results
except Exception:
    conn.execute("ROLLBACK TO SAVEPOINT batch_area_new")
    conn.execute("RELEASE batch_area_new")
    raise
```

Using a savepoint rather than `BEGIN` is safe because `_open_db` may itself
have an open transaction (stale-cursor clear + commit). `BEGIN` inside an open
transaction is a no-op in SQLite and the rollback would land on the outer
transaction.

## Secondary fix — empty items list error message

`items=[]` currently falls through to the `not items and not name` gate and
returns "name is required" — the single-mode message. Correct message:
"items list is empty".

## Changes

### `context.py` — `create_areas_batch()`

Replace `conn.commit()` at the end with savepoint/release/rollback pattern.

### `mcpptool.py` — `_cmd_area_new()`

After the mutual-exclusion check, add:
```python
if items is not None and len(items) == 0:
    return {"success": False, "error": "items list is empty"}
```

## Files changing

- `context.py` — `create_areas_batch()`
- `mcpptool.py` — `_cmd_area_new()`

## Files NOT changing

- `tool.yaml`, `db.py`, schema_patches/, `create_area()`

## source_hash

context.py: post-b5b9e85
mcpptool.py: post-b5b9e85
