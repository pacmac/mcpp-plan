# Spec: stale-task-nag

## Problem

Active tasks that have had no recent activity (no step completions, no note additions)
can be silently forgotten. There is no signal to prompt housekeeping. Hardcoding a TTL
is inflexible — different projects have different cadences.

## Solution

Append a nag to every MCP tool response listing active tasks with no activity for
more than `workflow.stale_task_days` days. Default is 0 (disabled). Set a positive
integer to opt in (e.g. `stale_task_days: 14`).

## Staleness definition

`MAX(contexts.updated_at, MAX(tasks.updated_at))` across all non-deleted steps.
Using only `contexts.updated_at` is insufficient — it only updates on status/rename
changes, not on step completions or note additions.

## Changes

### config.py — add default

In `DEFAULTS["workflow"]`, add:
```python
"stale_task_days": 0,
```

Before (line 14–20):
```python
DEFAULTS: dict[str, Any] = {
    "workflow": {
        "require_goal_and_plan": True,
        "allow_reopen_completed": False,
        "daily_backup": True,
        "backup_retain_days": 7,
        "enable_steps": True,
    },
```

After:
```python
DEFAULTS: dict[str, Any] = {
    "workflow": {
        "require_goal_and_plan": True,
        "allow_reopen_completed": False,
        "daily_backup": True,
        "backup_retain_days": 7,
        "enable_steps": True,
        "stale_task_days": 0,
    },
```

### mcpptool.py — stale-nag block in execute()

Insert after the done-nag block (after line 869, before `conn.close()`):

```python
            # Nag: active tasks with no activity for stale_task_days days
            _stale_days = cfg_nag.get("workflow", {}).get("stale_task_days", 0)
            if _stale_days and _proj_id:
                stale_rows = conn.execute(
                    "SELECT c.name FROM contexts c "
                    "WHERE c.project_id = ? AND c.status = 'active' "
                    "AND MAX("
                    "    c.updated_at,"
                    "    COALESCE("
                    "        (SELECT MAX(t.updated_at) FROM tasks t"
                    "         WHERE t.context_id = c.id AND t.is_deleted = 0),"
                    "        c.updated_at"
                    "    )"
                    ") < datetime('now', ?)",
                    (_proj_id, f"-{_stale_days} days"),
                ).fetchall()
                if stale_rows:
                    snames = ", ".join(f"`{r[0]}`" for r in stale_rows)
                    stale_nag = (
                        f"\n\n---\n⚠ {len(stale_rows)} task(s) have had no activity"
                        f" for {_stale_days}+ days: {snames}. Review or close."
                    )
                    result["display"] = (result.get("display", "") + stale_nag)
```

The existing done-nag block loads `cfg_nag` via `_load_config_mod().get_config()` —
reuse that same variable. Confirm the variable name by reading the block at
implementation time.

### README.md — document the config knob

In the Configuration section, add `stale_task_days` alongside `backup_retain_days`
with its default and purpose.

## Files changing
- `config.py`
- `mcpptool.py`
- `README.md`

## Files NOT changing
- `context.py` — no new functions needed
- `db.py` — no schema changes
- `schema.sql` — no schema changes
- `tool.yaml` — no new tools

## source_hash
config.py:   6d6fb565264f1988c3168988bcb168efda51b92e00ba1831d4c5ac0fb83a86fa
mcpptool.py: 1f3760c688c56d5620aaf9010d2ed8ec55303b02cb5c26a203dfe93cff9bfda7
README.md:   071575bfe0648d32bb9498a8f814a51255e287f39e87f9bd3d13eade0aae60a8
