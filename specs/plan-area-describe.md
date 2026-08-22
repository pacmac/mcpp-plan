# Spec: plan-area-describe

## Gap

`plan_area_rename` only touches the `name` column. There is no tool to set or
update `description_md` on an existing area. Five areas in device's project have
no "DONE when…" clause and no way to add one.

## Fix

New tool `plan_area_describe` — sets `description_md` on an existing area.

### Signature

```
plan_area_describe(name: str, description: str)
```

- `name` — must match an existing area (same validation as other area tools)
- `description` — new description_md value (replaces existing; empty string clears it)

### Implementation

**context.py** — new function `update_area_description`:

```python
def update_area_description(conn, name, description_md, project_id):
    row = conn.execute(
        "SELECT id FROM areas WHERE name = ? AND project_id = ?",
        (name, project_id),
    ).fetchone()
    if not row:
        return f"Area '{name}' not found"
    now = db.utc_now_iso()
    conn.execute(
        "UPDATE areas SET description_md = ?, updated_at = ? WHERE id = ?",
        (description_md or None, now, row["id"]),
    )
    return None  # no error
```

Empty string → stored as NULL (consistent with how plan_area_new treats missing description).

**mcpptool.py** — new `_cmd_area_describe`, dispatched as `plan_area_describe`.

**tool.yaml** — new entry after `plan_area_rename`.

## Files changing

- `context.py` — `update_area_description`
- `mcpptool.py` — `_cmd_area_describe`
- `tool.yaml` — new tool entry

## Files NOT changing

- `db.py`, schema_patches/ (no schema change — description_md column already exists)
