# Spec: area-delete-checks-all-tasks

## Bug

`delete_area()` in `context.py` only checks ACTIVE tasks before refusing deletion:

```python
refs = conn.execute(
    "SELECT name FROM contexts WHERE project_id = ? AND area = ? AND status = 'active'",
    (project_id, name),
).fetchall()
```

A completed task whose `area` column still references the deleted area is silently
orphaned. After deletion:
- `plan_area_list` shows no such area
- `plan_task_list --area <name>` returns "this project has no areas" error (not the task)
- The completed task record says `area = 'roadmap'` but nothing can find it that way

Reported by roadmap (xsession item `area-delete-orphans-completed-tasks`, #15) with
a full end-to-end reproduction and state restored.

## Fix

Remove the `AND status = 'active'` predicate. Any task — active or completed — that
references the area blocks deletion.

```python
refs = conn.execute(
    "SELECT name FROM contexts WHERE project_id = ? AND area = ?",
    (project_id, name),
).fetchall()
```

The error message already says "task(s) still assigned" — update to "task(s) reference"
to be accurate for completed tasks too.

## Files changing

- `context.py` — `delete_area()`: remove status filter, update error wording

## Files NOT changing

- `mcpptool.py` — no handler changes needed
- `tool.yaml` — no new tools
- schema_patches/ — no schema changes

## source_hash

context.py: post-2cc1439
