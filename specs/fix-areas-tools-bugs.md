# Spec: fix-areas-tools-bugs

## Problems (all found by roadmap dogfooding areas-integration)

### Bug 1 — plan_task_list --area <unknown> returns "No tasks"

`list_tasks()` with `area_filter` silently returns empty when the area doesn't
exist. Indistinguishable from a real empty area. A typo in an area name makes a
project with open tasks look finished. Fix: validate area_filter before filtering.

### Bug 2 — plan_area_new with duplicate name leaks SQLite error

`create_area()` raises the raw `UNIQUE constraint failed: areas.project_id, areas.name`
message. Fix: catch `sqlite3.IntegrityError` in `create_area()` and raise a
`ValueError` with a user-readable message.

### Gap 1 — plan_area_rename missing, cascades needed

No rename tool exists. A wrong area name is permanent because the name is the join
key (contexts.area). Fix: add `rename_area(conn, name, new_name, project_id)` that
renames the row AND cascades `UPDATE contexts SET area = new_name WHERE area = name
AND project_id = ?`.

### Gap 2 — plan_area_delete missing, must refuse while tasks attached

No delete tool exists. Fix: add `delete_area(conn, name, project_id)` that:
- Refuses with a named list if any contexts still reference the area
- Deletes the row if safe

A delete that silently clears contexts.area loses information nobody can see.
Deletion is a last resort; rename is the common case.

## Fixes

### `context.py` — in `create_area()`

```python
import sqlite3
try:
    cur = conn.execute(...)
    conn.commit()
except sqlite3.IntegrityError:
    raise ValueError(f"area '{name}' already exists in this project")
```

### `context.py` — new `rename_area()` function

```python
def rename_area(conn, name: str, new_name: str, project_id=None) -> dict:
    now = db.utc_now_iso()
    row = conn.execute(
        "SELECT id FROM areas WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()
    if not row:
        raise ValueError(f"area '{name}' not found in this project")
    clash = conn.execute(
        "SELECT 1 FROM areas WHERE project_id = ? AND name = ?",
        (project_id, new_name),
    ).fetchone()
    if clash:
        raise ValueError(f"area '{new_name}' already exists in this project")
    conn.execute(
        "UPDATE areas SET name = ?, updated_at = ? WHERE id = ?",
        (new_name, now, row["id"]),
    )
    conn.execute(
        "UPDATE contexts SET area = ?, updated_at = ? WHERE project_id = ? AND area = ?",
        (new_name, now, project_id, name),
    )
    conn.commit()
    return {"old_name": name, "new_name": new_name, "project_id": project_id}
```

### `context.py` — new `delete_area()` function

```python
def delete_area(conn, name: str, project_id=None) -> dict:
    row = conn.execute(
        "SELECT id FROM areas WHERE project_id = ? AND name = ?",
        (project_id, name),
    ).fetchone()
    if not row:
        raise ValueError(f"area '{name}' not found in this project")
    refs = conn.execute(
        "SELECT name FROM contexts WHERE project_id = ? AND area = ? AND status = 'active'",
        (project_id, name),
    ).fetchall()
    if refs:
        names = ", ".join(f"`{r['name']}`" for r in refs)
        raise ValueError(
            f"cannot delete area '{name}': {len(refs)} task(s) still assigned: {names}"
        )
    conn.execute("DELETE FROM areas WHERE id = ?", (row["id"],))
    conn.commit()
    return {"deleted": name, "project_id": project_id}
```

### `mcpptool.py` — `_run_plan_cmd` "task list" block

After parsing `area_filter`, before calling `list_tasks`:

```python
if area_filter:
    err = plan_ctx.validate_area(conn, area_filter, project_id=_project_id)
    if err:
        conn.close()
        return {"success": False, "error": err}
```

### `mcpptool.py` — new `_cmd_area_rename()` and `_cmd_area_delete()` handlers

Standard pattern (open_db, call context fn, return display).

### `mcpptool.py` — dispatch map additions

```python
"plan_area_rename": _cmd_area_rename,
"plan_area_delete": _cmd_area_delete,
```

### `tool.yaml` — two new tools

```yaml
  - name: plan_area_rename
    description: "Rename a functional area; cascades to all tasks in that area"
    inputSchema:
      type: object
      required: [name, new_name]
      properties:
        name: {type: string, description: "Current area name"}
        new_name: {type: string, description: "New area name"}

  - name: plan_area_delete
    description: "Delete an area. Refuses if any tasks are still assigned to it."
    inputSchema:
      type: object
      required: [name]
      properties:
        name: {type: string, description: "Area name to delete"}
```

## Files changing

- `context.py` — create_area (bug fix), rename_area (new), delete_area (new)
- `mcpptool.py` — task list area validation; _cmd_area_rename; _cmd_area_delete; dispatch map
- `tool.yaml` — plan_area_rename, plan_area_delete
- `README.md` — add plan_area_rename and plan_area_delete to area tools table

## Files NOT changing

- `db.py`, schema_patches/ — no schema changes (areas table is unchanged)

## source_hash

context.py:  ~
mcpptool.py: ~
tool.yaml:   ~
README.md:   ~
