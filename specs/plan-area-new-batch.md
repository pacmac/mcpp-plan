# Spec: plan-area-new-batch

## Problem

Every repo that has an AREAS.yaml but no plan.db areas gets a nag on every MCP
call. The only clearance path is N sequential `plan_area_new` calls — one per area.
A repo with 10 areas requires 10 round trips. A nag with no cheap clearance path
gets ignored; an ignored nag is worse than no nag.

## Fix

Extend `plan_area_new` to accept an `items` list alongside the existing `name` /
`description_md` scalars. When `items` is present, create all rows in one call.

The single-item path (`name` + optional `description_md`) is unchanged — no
existing caller breaks.

## Interface

```python
# single (unchanged)
plan_area_new(name="roadmap")
plan_area_new(name="roadmap", description_md="…")

# batch (new)
plan_area_new(items=[
    {"name": "radio-transport", "description_md": "…"},
    {"name": "power-and-sleep"},
    …
])
```

`items` and `name` are mutually exclusive. If both are supplied, error.

Each item goes through the same `_validate_area_name()` + case-insensitive
duplicate check as the single path. The call is all-or-nothing: if any item fails
validation or collides, no rows are inserted and the error names the failing item.

Return value for batch: `{"created": N, "areas": [list of created area dicts]}`.

## Changes

### `context.py` — `create_area()`

No change. The function already handles one area; the batch caller loops over it
inside a single transaction.

### `context.py` — new `create_areas_batch()`

```python
def create_areas_batch(conn, items: list, project_id=None) -> list:
    """Create multiple areas atomically. Raises ValueError on first collision."""
    results = []
    for item in items:
        name = _validate_area_name(item["name"])
        desc = item.get("description_md")
        clash = conn.execute(
            "SELECT name FROM areas WHERE project_id = ? AND LOWER(name) = LOWER(?)",
            (project_id, name),
        ).fetchone()
        if clash:
            raise ValueError(
                f"area '{clash['name']}' already exists (while adding '{name}')"
            )
        now = db.utc_now_iso()
        cur = conn.execute(
            "INSERT INTO areas (project_id, name, description_md, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, name, desc, now, now),
        )
        results.append({"id": cur.lastrowid, "project_id": project_id,
                        "name": name, "description_md": desc})
    conn.commit()
    return results
```

### `mcpptool.py` — `_cmd_area_new()`

```python
def _cmd_area_new(conn, project, args):
    items = args.get("items")
    name  = args.get("name")
    if items and name:
        raise ValueError("supply either 'name' or 'items', not both")
    if items:
        created = context.create_areas_batch(conn, items,
                                             project_id=project["id"])
        return {"created": len(created), "areas": created}
    # existing single-item path unchanged
    area = context.create_area(conn, name=name,
                               description_md=args.get("description_md"),
                               project_id=project["id"])
    return area
```

### `tool.yaml` — `plan_area_new`

Add `items` parameter (array of objects):

```yaml
- name: items
  description: >
    Batch mode: list of {name, description_md?} objects. Mutually exclusive with `name`.
  schema:
    type: array
    items:
      type: object
      required: [name]
      properties:
        name: {type: string}
        description_md: {type: string}
```

## Files changing

- `context.py` — `create_areas_batch()` (new)
- `mcpptool.py` — `_cmd_area_new()`
- `tool.yaml` — `plan_area_new` parameter addition

## Files NOT changing

- `db.py`, schema_patches/, `plan_area_list`, `plan_area_rename`, `plan_area_delete`

## source_hash

context.py: post-3fd2657
mcpptool.py: post-fc865ff
