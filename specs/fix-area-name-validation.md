# Spec: fix-area-name-validation

## Bugs (reported by roadmap, item #16)

### Bug A — whitespace-only name accepted

`create_area(conn, name="   ")` inserts a row with `name = '   '`. The area appears
in `plan_area_list` as a blank entry and cannot be referenced by the filter tools.

### Bug B — case-variant duplicate accepted

`create_area(conn, name='Roadmap')` followed by `create_area(conn, name='roadmap')`
creates two distinct rows. The UNIQUE constraint is on `(project_id, name)` with
SQLite's default case-sensitive collation, so the two names pass the constraint.
Referencing either by its exact case works; the other is unreachable by that name.

## Fix

In `create_area()` and `rename_area()`, before any DB call:

1. Strip leading/trailing whitespace from `name`.
2. Reject if empty after strip.
3. Check for a case-insensitive duplicate with `LOWER(name) = LOWER(?)`.

Store the name as-provided (post-strip). The case-fold is for duplicate detection only;
display uses the original capitalisation.

For `rename_area()`, also check that `new_name` (after strip/validate) does not
case-insensitively collide with an existing area other than the one being renamed.

## Changes

### `context.py` — helper `_validate_area_name()`

```python
def _validate_area_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("area name cannot be empty or whitespace-only")
    return name
```

### `context.py` — `create_area()`

```python
def create_area(conn, name: str, ...):
    name = _validate_area_name(name)
    clash = conn.execute(
        "SELECT name FROM areas WHERE project_id = ? AND LOWER(name) = LOWER(?)",
        (project_id, name),
    ).fetchone()
    if clash:
        raise ValueError(f"area '{clash['name']}' already exists in this project")
    ...
```

The IntegrityError catch for exact dupes is kept but becomes unreachable in practice;
removing it would be premature.

### `context.py` — `rename_area()`

```python
def rename_area(conn, name: str, new_name: str, ...):
    new_name = _validate_area_name(new_name)
    ...
    # Case-insensitive clash check (exclude the row being renamed)
    clash = conn.execute(
        "SELECT name FROM areas WHERE project_id = ? AND LOWER(name) = LOWER(?) AND id != ?",
        (project_id, new_name, row["id"]),
    ).fetchone()
    if clash:
        raise ValueError(f"area '{clash['name']}' already exists in this project")
    ...
```

## Files changing

- `context.py` — `_validate_area_name()` (new), `create_area()`, `rename_area()`

## Files NOT changing

- `mcpptool.py`, `tool.yaml`, `README.md`, schema_patches/

## source_hash

context.py: post-b3d8776
