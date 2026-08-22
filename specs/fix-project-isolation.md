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

## Additional hardening (steps 2-4)

### Step 2 — Hard error for non-absolute workspace_dir

After the override check in `_open_db()`, before calling `ensure_project()`:

```python
if not Path(workspace_dir).is_absolute():
    conn.close()
    raise ValueError(
        f"workspace_dir '{workspace_dir}' is not an absolute path — "
        "cannot resolve project. Ensure the MCP server is configured with an absolute workspace."
    )
```

`workspace_dir` defaults to `"."` in `execute()` when the context provides none. Calling
`ensure_project(conn, ".")` creates a junk project at path `"."` that all undirected calls
share. A hard error is better than silent mis-filing.

### Step 3 — Clear stale active-context cursor in execute() injection

In execute()'s injection block, after resolving `_user_id` and `_proj_id`, add:

```python
# Cross-check: active_context_id for this user+project must belong to this project.
# If it points to a context in a different project (e.g. after task move), clear it.
stale = conn.execute(
    "SELECT us.active_context_id FROM user_state us "
    "JOIN contexts c ON c.id = us.active_context_id "
    "WHERE us.user_id = ? AND us.project_id = ? AND c.project_id != ?",
    (_user_id, _proj_id, _proj_id),
).fetchone()
if stale:
    plan_db_mod.upsert_user_state(conn, _user_id, _proj_id, None)
    conn.commit()
```

This closes the write-through window that move_task's DELETE leaves open if a session
already has the context cached as active. Located in the `try/except Exception: pass`
injection block — failures are silent and non-blocking.

### Step 4 — Exempt plan_project_select from web-key when project matches cwd

In `_cmd_project_select()`, look up the project before the key check and skip the gate
when the project's `absolute_path` matches `workspace_dir`:

```python
# Resolve project first to check for cwd self-select exemption
project = plan_ctx.get_project(conn, project_id=project_id)
if not project:
    return {"success": False, "error": f"Project {project_id} not found."}

project_path = project.get("absolute_path", "")
is_self_select = (
    Path(workspace_dir).is_dir()
    and project_path
    and Path(workspace_dir).resolve() == Path(project_path)
)
if not is_self_select and not cfg_mod.check_web_key(key):
    return {"success": False, "error": "Invalid or missing web API key."}
```

Rationale: an agent in `/foo/bar` selecting project id=X where X's path is also `/foo/bar`
is self-correcting, not crossing a trust boundary.

## Files changing

- `mcpptool.py` — `_open_db()` (step 1, done), `_open_db()` (step 2), execute() injection (step 3), `_cmd_project_select()` (step 4)

## Files NOT changing

- `context.py` — no changes
- `db.py` — no schema changes
- `tool.yaml` — no new tools
- `README.md` — no user-facing behavioural change to document

## Verification

1. Start a local session in mcpp-plan with a node-dash override still in user_prefs.
   Call `plan_project_show` — must return mcpp-plan, not node-dash. (step 1)
2. Call `plan_project_select` without a web key, with project_id matching the current
   workspace — must succeed. (step 4)
3. Simulate stale cursor: directly update user_state to point to a context from another
   project; call any plan tool — cursor must be cleared and not cause a write-through. (step 3)

## source_hash

mcpptool.py: 2cc1439 (post-areas-tools-bugs commit)
