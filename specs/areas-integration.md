# Spec: areas-integration

## Problem

Tasks (contexts) have no functional area field. Area is recorded only by naming
convention which nothing enforces and nothing can filter on. There is no place to
define what areas a project has. Agents cannot see progress area by area and cannot
be directed to "work on area X this session."

## Solution

Add an `areas` table to plan.db (per-project, name + description). Add `area TEXT
NULL` to `contexts`. Validate at write time against the `areas` table — DB only, no
filesystem, no YAML. Add area management tools. Add area filter to `plan_task_list`.
Nag when a project has active tasks but no areas defined.

## Schema — `schema_patches/patch-14.sql`

```sql
CREATE TABLE IF NOT EXISTS areas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES project(id),
    name            TEXT NOT NULL,
    description_md  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_areas_project ON areas(project_id);

ALTER TABLE contexts ADD COLUMN area TEXT;
```

## `db.py:26` — version bump

`LATEST_SCHEMA_VERSION = 13` → `14`

## `context.py` changes

### `create_context()` (line 267)

Add `area: Optional[str] = None` parameter. Update INSERT:

```python
"INSERT INTO contexts (name, status, description_md, user_id, project_id, area, created_at, updated_at) "
"VALUES (?, 'active', ?, ?, ?, ?, ?, ?)",
(name, description_md, user_id, project_id, area, now, now),
```

### `list_contexts()` (line 1650)

Add `c.area` to SELECT and to returned dict entry (`entry["area"] = row["area"]`).

### `list_tasks()` (line 2087)

Add `area_filter=None` parameter:
```python
if area_filter:
    contexts = [c for c in contexts if c.get("area") == area_filter]
```

### `create_task()` wrapper (line 2095)

Add `area=None`, pass `area=area` to `create_context`.

### New area functions (insert after `rename_task`)

```python
def create_area(conn, name: str, description_md: str | None = None,
                project_id: int | None = None) -> dict:
    now = db.utc_now_iso()
    cur = conn.execute(
        "INSERT INTO areas (project_id, name, description_md, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, name, description_md, now, now),
    )
    conn.commit()
    return {"id": cur.lastrowid, "project_id": project_id, "name": name,
            "description_md": description_md}


def list_areas(conn, project_id: int | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT id, project_id, name, description_md, created_at FROM areas "
        "WHERE project_id = ? ORDER BY name",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def validate_area(conn, area_name: str, project_id: int | None = None) -> str | None:
    """Return error string if area_name is invalid for this project, else None."""
    areas = list_areas(conn, project_id=project_id)
    if not areas:
        return "this project has no areas defined — use plan_area_new to create one"
    valid = [a["name"] for a in areas]
    if area_name not in valid:
        return f"unknown area '{area_name}'; valid: {', '.join(valid)}"
    return None
```

## `mcpptool.py` changes

### 1. "task new" block in `_run_plan_cmd` (~line 345)

Add `--area` parsing after the steps loop. After `if not steps_list:` block, before
`create_task()`:

```python
area = None
# re-parse for --area (loop above may have advanced i past it)
for j in range(3, len(cmd_args) - 1):
    if cmd_args[j] == "--area":
        area = cmd_args[j + 1]
        break

if area:
    err = plan_ctx.validate_area(conn, area, project_id=_project_id)
    if err:
        conn.close()
        return {"success": False, "error": err}
```

Pass `area=area` to `plan_ctx.create_task(...)`.

### 2. "task list" block in `_run_plan_cmd` (~line 374)

Add `--area` to the parsing loop:
```python
elif cmd_args[i] == "--area" and i + 1 < len(cmd_args):
    area_filter = cmd_args[i + 1]
    i += 2
```
Initialize `area_filter = None` before the loop. Pass `area_filter=area_filter` to `list_tasks`.

### 3. `_cmd_task_new` (line 927)

Add area to cmd:
```python
if area := args.get("area"):
    cmd.extend(["--area", area])
```

### 4. `_cmd_task_list` (line 946)

Add area to cmd:
```python
if area := args.get("area"):
    cmd.extend(["--area", area])
```

### 5. New `_cmd_area_new()` and `_cmd_area_list()` handlers

```python
def _cmd_area_new(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}
    description_md = args.get("description")
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.create_area(conn, name, description_md=description_md,
                                      project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Area created: **{name}**"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_area_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        areas = plan_ctx.list_areas(conn, project_id=project_id)
        lines = [f"**Areas** ({len(areas)})"]
        for a in areas:
            desc = f" — {a['description_md']}" if a.get("description_md") else ""
            lines.append(f"  - {a['name']}{desc}")
        display = "\n".join(lines) if areas else "No areas defined. Use `plan_area_new` to create one."
        return {"success": True, "result": {"areas": areas}, "display": display}
    finally:
        conn.close()
```

### 6. New `_cmd_task_set_area()` handler

```python
def _cmd_task_set_area(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    area = args.get("area")  # None = clear
    if not name:
        return {"success": False, "error": "name is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        if area:
            err = plan_ctx.validate_area(conn, area, project_id=project_id)
            if err:
                return {"success": False, "error": err}
        context_id = plan_ctx.resolve_context_id(conn, name, project_id=project_id)
        now = plan_db_mod.utc_now_iso()
        conn.execute("UPDATE contexts SET area = ?, updated_at = ? WHERE id = ?",
                     (area, now, context_id))
        conn.commit()
        action = f"→ {area}" if area else "cleared"
        return {"success": True, "result": {"name": name, "area": area},
                "display": f"Area {action} on `{name}`"}
    finally:
        conn.close()
```

### 7. Dispatch map additions (after `plan_task_rename`)

```python
"plan_area_new":      _cmd_area_new,
"plan_area_list":     _cmd_area_list,
"plan_task_set_area": _cmd_task_set_area,
```

### 8. AREAS nag in execute() injection block (after stale nag, before `conn.close()`)

```python
# Nag: project has active tasks but no areas defined
if _proj_id:
    has_areas = conn.execute(
        "SELECT 1 FROM areas WHERE project_id = ? LIMIT 1", (_proj_id,)
    ).fetchone()
    if not has_areas:
        has_tasks = conn.execute(
            "SELECT 1 FROM contexts WHERE project_id = ? AND status = 'active' LIMIT 1",
            (_proj_id,)
        ).fetchone()
        if has_tasks:
            result["display"] = (result.get("display", "") +
                "\n\n---\n📋 No areas defined for this project. "
                "Use `plan_area_new` to define functional areas and enable area-based tracking.")
```

## `tool.yaml` additions

Add `area` property to `plan_task_new` and `plan_task_list`. Add three new tools:

```yaml
  - name: plan_area_new
    description: "Define a functional area for this project"
    inputSchema:
      type: object
      required: [name]
      properties:
        name:
          type: string
          description: "Area name (e.g. 'radio-transport')"
        description:
          type: string
          description: "What this area does"

  - name: plan_area_list
    description: "List functional areas defined for this project"
    inputSchema:
      type: object
      properties: {}

  - name: plan_task_set_area
    description: "Set or clear the functional area on a task"
    inputSchema:
      type: object
      required: [name]
      properties:
        name:
          type: string
          description: "Task slug to update"
        area:
          type: string
          description: "Area name to set (omit to clear)"
```

## `README.md` — document new tools

Add `plan_area_new`, `plan_area_list`, `plan_task_set_area` to the tools table. Add
`area` to plan_task_new and plan_task_list descriptions.

## Files changing
- `schema_patches/patch-14.sql` (new)
- `db.py`
- `context.py`
- `mcpptool.py`
- `tool.yaml`
- `README.md`

## Files NOT changing
- `schema.sql` — baseline only, not updated by patches
- `backup.py`, `config.py` — no changes needed

## source_hash
db.py:       ~
context.py:  ~
mcpptool.py: ~
tool.yaml:   ~
README.md:   ~
