# Spec: fix-project-isolation

## Problem

`_open_db()` applies the `user_prefs` project override unconditionally — for both
web requests and local agent sessions. Once `plan_project_select` has been called
(even once, e.g. during testing or web-server use), the override persists in
`user_prefs` and silently wins over `workspace_dir` for every subsequent call,
regardless of cwd.

Symptom: a new agent session started in directory A resolves to project B because
a prior session left an override row in `user_prefs`.

## Root cause

`mcpptool.py` — `_open_db()`:

```python
# BEFORE (lines 276-281)
override_id = plan_ctx.get_active_project_override(conn, user_id)
if override_id is not None:
    project = plan_ctx.get_project(conn, project_id=override_id)
    if project:
        return conn, project, False, user_id, project["id"]  # ignores workspace_dir
```

The override is unconditional. For local agents (`workspace_dir` is a real
directory), `workspace_dir` should always win.

## Fix

Gate the override on `not Path(workspace_dir).is_dir()`. Web requests arrive with
a non-directory `workspace_dir` (e.g. a server process path or `.`); local agents
always have a real workspace directory.

```python
# AFTER
if not Path(workspace_dir).is_dir():
    override_id = plan_ctx.get_active_project_override(conn, user_id)
    if override_id is not None:
        project = plan_ctx.get_project(conn, project_id=override_id)
        if project:
            return conn, project, False, user_id, project["id"]
```

This is the same gate already used in `_cmd_project_set()` (`757e1cb`).

## Files changing

### mcpptool.py — `_open_db()` (lines 276–281)

Before:
```python
    # Check for project override
    override_id = plan_ctx.get_active_project_override(conn, user_id)
    if override_id is not None:
        project = plan_ctx.get_project(conn, project_id=override_id)
        if project:
            return conn, project, False, user_id, project["id"]
```

After:
```python
    # Check for project override — web requests only (workspace_dir is not a real dir)
    if not Path(workspace_dir).is_dir():
        override_id = plan_ctx.get_active_project_override(conn, user_id)
        if override_id is not None:
            project = plan_ctx.get_project(conn, project_id=override_id)
            if project:
                return conn, project, False, user_id, project["id"]
```

## Files NOT changing

- `context.py` — `get_active_project_override()` is correct as-is
- `db.py` — no schema changes
- `tool.yaml` — no new tools
- `README.md` — no user-facing behavioural change to document

## Verification

1. Start a local session in mcpp-plan with a node-dash override still in user_prefs.
   Call `plan_project_show` — must return mcpp-plan, not node-dash.
2. Call `plan_project_select` (web key, project_id=node-dash id) to set an override.
   Call `plan_project_show` — local session must still return mcpp-plan (override ignored).
3. Confirm web path still works: a call with a non-directory `workspace_dir` (simulate
   by passing `.` when cwd is not a project) must use the override.

## source_hash

mcpptool.py: 1849255665a8f3266cd3ad87a3fbab5c63027127939d0de68d35867150ebb1d9
