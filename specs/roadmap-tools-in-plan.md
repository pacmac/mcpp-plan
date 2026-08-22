# Spec: roadmap-tools-in-plan

## Goal

Port `roadmap_focus`, `roadmap_next`, and `roadmap_all` from the retired
`mcpp-roadmap` tool into `mcpp-plan` as DB-backed MCP tools. No file scanning,
no AREAS.yaml, no claude/areas dependency. Areas are plan.db rows; tasks are
plan.db contexts.

`roadmap_areas_check`, `roadmap_areas_init`, and `roadmap_areas_set` are NOT
ported — their functionality (file-to-area mapping, init from directory structure,
YAML editing) is being dropped entirely.

## Behavioral contracts inherited from the old tests

These are the rules that survive the transport change:

1. **CANNOT ≠ zero ≠ OK** — three distinct states. A query failure returns CANNOT,
   not an empty list. An empty list of open tasks returns OK (not CANNOT). Silence
   reads as health and is the worst answer.

2. **Unfiled tasks are shown, not dropped** — tasks with `area=NULL` appear in
   `plan_roadmap_all` under "IN NO AREA". Dropping them is how "nothing asked for
   is lost" fails.

3. **Every ranked line carries the constraint that put it there** — `plan_roadmap_next`
   shows WHY each area is where it is: N open tasks, or "nothing open".

4. **Focus get/set**: set stores, read back returns stored value; setting twice
   does not leave two pointers (upsert); unknown area → CANNOT with list of valid ones;
   no focus set → helpful message naming `plan_roadmap_next` and `plan_roadmap_focus`.

5. **The payload and the display say the same thing** — both are derived from the
   same query result; they cannot disagree.

6. **The project it resolved is in every response** — always include project_name or
   project_id so a caller can tell if the tool ran against the wrong tree.

## Schema change — patch 15

Add `focus_area TEXT` to `user_state`:

```sql
ALTER TABLE user_state ADD COLUMN focus_area TEXT;
```

`user_state` is per-user-per-project (composite PK user_id + project_id), so this
is the right home — same scope as `active_context_id`.

## New functions in `context.py`

### `get_focus_area(conn, user_id, project_id) -> str | None`

```python
def get_focus_area(conn, user_id, project_id):
    row = conn.execute(
        "SELECT focus_area FROM user_state WHERE user_id = ? AND project_id = ?",
        (user_id, project_id),
    ).fetchone()
    return row["focus_area"] if row else None
```

### `set_focus_area(conn, user_id, project_id, area_name) -> None`

Upsert into user_state (reuses existing upsert pattern):

```python
def set_focus_area(conn, user_id, project_id, area_name):
    now = db.utc_now_iso()
    conn.execute(
        "INSERT INTO user_state (user_id, project_id, focus_area, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, project_id) DO UPDATE SET focus_area=excluded.focus_area, "
        "updated_at=excluded.updated_at",
        (user_id, project_id, area_name, now),
    )
```

### `roadmap_all_data(conn, project_id) -> dict`

Returns structured data used by both `plan_roadmap_all` and `plan_roadmap_next`:

```python
{
  "areas": [
    {"name": str, "description_md": str|None,
     "open": int, "complete": int}
  ],
  "unfiled": [
    {"name": str, "title": str}   # tasks with area=NULL and status='active'
  ],
  "project_id": int,
}
```

SQL for areas:
```sql
SELECT
    a.name,
    a.description_md,
    COUNT(CASE WHEN c.status='active' THEN 1 END) AS open,
    COUNT(CASE WHEN c.status='complete' THEN 1 END) AS complete
FROM areas a
LEFT JOIN contexts c ON c.project_id = a.project_id AND c.area = a.name
WHERE a.project_id = ?
GROUP BY a.id
ORDER BY a.name
```

SQL for unfiled:
```sql
SELECT name, description_md
FROM contexts
WHERE project_id = ? AND area IS NULL AND status = 'active'
ORDER BY name
```

## New commands in `mcpptool.py`

### `_cmd_roadmap_focus(workspace_dir, args)`

- `area` absent → read mode: return current focus or helpful FINDING
- `area` present → validate against `list_areas`, then `set_focus_area`; reject unknown with list
- Always CANNOT if no areas defined
- Payload always includes `focus`, `areas` (list of valid names), `project_name`

### `_cmd_roadmap_next(workspace_dir, args)`

- Call `roadmap_all_data`
- CANNOT if no areas defined
- For each area: `open > 0` → ranked with `why = "N open task(s)"`; `open == 0` → parked with `why = "nothing open"`
- Ranked sorted by open count descending
- Always include `unfiled` count in display if > 0
- Focus area (if set) highlighted at top of display
- Payload: `{"ranked": [...], "parked": [...], "unfiled": [...], "focus": str|None}`

### `_cmd_roadmap_all(workspace_dir, args)`

- CANNOT if no areas defined
- Show all areas with open + complete counts
- Unfiled tasks listed under "IN NO AREA" — never dropped
- Payload: `{"areas": [...], "unfiled": [...], "project_name": str}`

## tool.yaml additions

Three new tools after `plan_area_delete`:

```yaml
- name: plan_roadmap_focus
  description: "Get or set the focus area for this session. Omit `area` to read the current focus."
  inputSchema:
    type: object
    properties:
      area:
        type: string
        description: "Area name to focus on. Omit to read current focus."

- name: plan_roadmap_next
  description: "Show what to work on next, ranked by open task count per area."
  inputSchema:
    type: object
    properties: {}

- name: plan_roadmap_all
  description: "Show the full roadmap: all areas with open/complete task counts, plus unfiled tasks."
  inputSchema:
    type: object
    properties: {}
```

## Status / CANNOT convention

Reuse the three-value pattern from roadmap.py:
- `OK` (0) — no findings, no errors
- `FINDING` (1) — something worth attention (open tasks, no focus set)
- `CANNOT` (2) — could not determine state (no areas, DB error)

In mcpptool: `success: True` with `status` field in result, or `success: False` for CANNOT.

## Files changing

- `schema_patches/patch-15.sql` — new
- `context.py` — `get_focus_area()`, `set_focus_area()`, `roadmap_all_data()`
- `mcpptool.py` — `_cmd_roadmap_focus()`, `_cmd_roadmap_next()`, `_cmd_roadmap_all()`, dispatch table
- `tool.yaml` — three new tool definitions
- `db.py` — bump `LATEST_SCHEMA_VERSION` to 15

## Files NOT changing

- `schema.sql` (patches only), `mcpp-roadmap/` (read-only reference)

## source_hash

context.py: post-960cdd5
mcpptool.py: post-960cdd5
db.py: post-960cdd5
