# Spec: remove-areas-yaml-nag-gate

## Problem

The areas nag in `execute()` is gated on `not _areas_yaml.exists()`:

```python
_areas_yaml = Path(workspace_dir) / "docs" / "specs" / "AREAS.yaml"
if _proj_id and not _areas_yaml.exists():
    has_areas = conn.execute(...)
```

`AREAS.yaml` lives in `claude/areas`, which is being deleted once its functionality
migrates to plan.db. Once gone, `not _areas_yaml.exists()` is always True and the
gate does nothing — but it leaves dead code referencing a file that no longer exists
and a module that has been removed.

The gate was a stop-gap added when mcpp-roadmap still had `AREAS.yaml` and the nag
would have fired there as a false alarm. With the migration complete, the correct
behaviour is: any project with active tasks and no plan.db areas gets nagged.

## Fix

Remove the `_areas_yaml` Path construction and collapse the condition:

```python
# BEFORE
_areas_yaml = Path(workspace_dir) / "docs" / "specs" / "AREAS.yaml"
if _proj_id and not _areas_yaml.exists():
    has_areas = conn.execute(
        "SELECT 1 FROM areas WHERE project_id = ? LIMIT 1", (_proj_id,)
    ).fetchone()
    if not has_areas:
        has_tasks = conn.execute(
            "SELECT 1 FROM contexts WHERE project_id = ? AND status = 'active' LIMIT 1",
            (_proj_id,),
        ).fetchone()
        if has_tasks:
            result["display"] = (result.get("display", "") +
                "\n\n---\n📋 No areas defined for this project. "
                "Use `plan_area_new` to define functional areas and enable area-based tracking.")

# AFTER
if _proj_id:
    has_areas = conn.execute(
        "SELECT 1 FROM areas WHERE project_id = ? LIMIT 1", (_proj_id,)
    ).fetchone()
    if not has_areas:
        has_tasks = conn.execute(
            "SELECT 1 FROM contexts WHERE project_id = ? AND status = 'active' LIMIT 1",
            (_proj_id,),
        ).fetchone()
        if has_tasks:
            result["display"] = (result.get("display", "") +
                "\n\n---\n📋 No areas defined for this project. "
                "Use `plan_area_new` to define functional areas and enable area-based tracking.")
```

## Files changing

- `mcpptool.py` — execute() injection block: remove _areas_yaml, update condition

## Files NOT changing

- `context.py`, `db.py`, `tool.yaml`, `README.md` — no changes

## source_hash

mcpptool.py: post-317a0f1
