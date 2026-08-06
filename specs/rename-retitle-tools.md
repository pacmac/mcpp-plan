# Spec: rename-retitle-tools

## Problem

1. No way to retitle an existing task or step without deleting and recreating it.
   Delete-and-recreate destroys `completed_at`, step order, and the historical
   record — unacceptable for completed steps.

2. `plan_step_new(task=<name>)` writes correctly but returns a false error in the
   display: "Step N not found in context X". `get_step_summary` resolves step N in
   the **active** context, not the target task's context.

3. `plan_task_show` on a large task (e.g. `bugs` with hundreds of steps + attached
   spec) exceeds the tool output limit. No way to get a compact titles-only view.

## Schema note

`contexts.description_md` is the task title (human-readable). `contexts.name` is
the slug. `plan_task_rename` must update `description_md`, not a `title` column
(there is none). Steps use `tasks.title`.

## Changes

### context.py — two new functions

#### `rename_task(conn, context_name, new_title, project_id=None)`

```python
def rename_task(conn, context_name: str, new_title: str, project_id: int | None = None) -> dict:
    context_id = resolve_context_id(conn, context_name, project_id=project_id)
    now = db.utc_now_iso()
    conn.execute(
        "UPDATE contexts SET description_md = ?, updated_at = ? WHERE id = ?",
        (new_title, now, context_id),
    )
    conn.commit()
    return {"context_id": context_id, "name": context_name, "title": new_title}
```

Insert after `list_projects()` (currently ~line 1095).

#### `retitle_step(conn, step_number, new_title, user_id=None, project_id=None)`

```python
def retitle_step(conn, step_number: int, new_title: str,
                 user_id: int | None = None, project_id: int | None = None) -> dict:
    task_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    row = conn.execute(
        "SELECT id FROM tasks WHERE context_id = ? AND task_number = ?",
        (context_id, task_number),
    ).fetchone()
    if not row:
        raise ValueError(f"Step {step_number} not found")
    task_id = row["id"]
    now = db.utc_now_iso()
    conn.execute(
        "UPDATE tasks SET title = ?, updated_at = ? WHERE id = ?",
        (new_title, now, task_id),
    )
    conn.commit()
    return {"task_id": task_id, "step_number": step_number, "title": new_title}
```

Insert after `rename_task()`.

---

### mcpptool.py — five changes

#### 1. Add `_fmt_task_titles_only(data)` (insert near line 98, after `_fmt_task_show`)

```python
def _fmt_task_titles_only(data: dict) -> str:
    name = data.get("context_name", "?")
    title = data.get("context_title", name)
    active_num = data.get("active_task_number")
    lines = [f"**{name}**: {title}"]
    for t in data.get("tasks", []):
        if t.get("is_deleted"):
            continue
        num = t["task_number"]
        status = t["status"]
        marker = {"planned": " ", "started": ">", "complete": "x"}.get(status, " ")
        pointer = " <--" if num == active_num else ""
        lines.append(f"  [{marker}] {num}. {t['title']}{pointer}")
    return "\n".join(lines)
```

#### 2. Fix step new display bug (lines 509–512 in `_run_plan_cmd`)

Before:
```python
step_id, step_number = plan_ctx.create_step(
    conn, task_ref, title, description_md=description_md, user_id=_user_id, project_id=_project_id
)
result = plan_ctx.get_step_summary(conn, step_number=step_number, user_id=_user_id, project_id=_project_id)
return {"success": True, "result": result}
```

After:
```python
step_id, step_number = plan_ctx.create_step(
    conn, task_ref, title, description_md=description_md, user_id=_user_id, project_id=_project_id
)
if task_ref:
    # get_step_summary resolves via active context — wrong when task_ref differs.
    # Query by step_id directly.
    row = conn.execute(
        "SELECT id, context_id, task_number, title, description_md, status, "
        "parent_id, sort_index, sub_index, created_at, updated_at, completed_at "
        "FROM tasks WHERE id = ?",
        (step_id,),
    ).fetchone()
    result = dict(row) if row else {}
    result["notes"] = []
else:
    result = plan_ctx.get_step_summary(conn, step_number=step_number, user_id=_user_id, project_id=_project_id)
return {"success": True, "result": result}
```

#### 3. Add `titles_only` to `_cmd_task_show` (line 925)

Before:
```python
def _cmd_task_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    cmd = ["task", "show"]
    if name := args.get("name"):
        cmd.append(name)
    cmd.append("--json")
    r = _run_plan_cmd(workspace_dir, cmd)
    display = _fmt_task_show(r.get("result", {}))
    display += _fmt_inline_attachments(workspace_dir, context_id=r.get("result", {}).get("context_id"))
    return _with_display(r, display)
```

After:
```python
def _cmd_task_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    cmd = ["task", "show"]
    if name := args.get("name"):
        cmd.append(name)
    cmd.append("--json")
    r = _run_plan_cmd(workspace_dir, cmd)
    if args.get("titles_only"):
        display = _fmt_task_titles_only(r.get("result", {}))
    else:
        display = _fmt_task_show(r.get("result", {}))
        display += _fmt_inline_attachments(workspace_dir, context_id=r.get("result", {}).get("context_id"))
    return _with_display(r, display)
```

#### 4. Add `_cmd_task_rename` and `_cmd_step_retitle` handlers (insert after `_cmd_task_move`)

```python
def _cmd_task_rename(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Rename a task's display title (preserves slug/name)."""
    name = args.get("name")
    title = args.get("title")
    if not name:
        return {"success": False, "error": "name is required"}
    if not title:
        return {"success": False, "error": "title is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.rename_task(conn, name, title, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Renamed `{name}` → {title}"}
    finally:
        conn.close()


def _cmd_step_retitle(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Retitle a step (preserves status, completed_at, order)."""
    number = args.get("number")
    title = args.get("title")
    if number is None:
        return {"success": False, "error": "number is required"}
    if not title:
        return {"success": False, "error": "title is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.retitle_step(conn, number, title, user_id=user_id, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Step {number} retitled → {title}"}
    finally:
        conn.close()
```

#### 5. Add to dispatch map (after `plan_task_move`)

```python
"plan_task_rename": _cmd_task_rename,
"plan_step_retitle": _cmd_step_retitle,
```

---

### tool.yaml — add two tools, update plan_task_show

Add after `plan_task_move`:
```yaml
- name: plan_task_rename
  description: "Rename a task's display title without changing its slug. Preserves all history."
  inputSchema:
    type: object
    required: [name, title]
    properties:
      name:
        type: string
        description: "Task slug (name) to rename"
      title:
        type: string
        description: "New display title"

- name: plan_step_retitle
  description: "Retitle a step without affecting its status, completed_at, or order."
  inputSchema:
    type: object
    required: [number, title]
    properties:
      number:
        type: integer
        description: "Step number to retitle"
      title:
        type: string
        description: "New step title"
```

Add `titles_only` property to `plan_task_show`:
```yaml
      titles_only:
        type: boolean
        description: "Return only step numbers and titles (omits notes, goal, plan, attachments — use for large tasks)"
```

---

### README.md

Add two rows to the Task tools table:
```
plan_task_rename | Rename a task's display title (slug unchanged, history preserved)
plan_step_retitle | Retitle a step (status/completed_at/order unchanged)
```

---

## Files changing
- `context.py`
- `mcpptool.py`
- `tool.yaml`
- `README.md`

## Files NOT changing
- `db.py` — no schema changes
- `schema.sql` — no schema changes
- `config.py` — no config changes
- `backup.py` — no changes

## source_hash
context.py:  b1a6aece6ce97b5da94f5cea416eb87cbc39812233dd9e392b630703b71b2df9
mcpptool.py: a40d293dfc74c1c3d9a7b4197a1d2d515dd5135999543e1592c6a73404f9b7ac
tool.yaml:   87f1f3ed35a2abed728a3dfa58dcab2122a1044b94fe6fc5f935eedbe00ea332
README.md:   0968f86966539f915f13dbb915ca23a0bd5c9c1ade890d40bff9f9c201529003
