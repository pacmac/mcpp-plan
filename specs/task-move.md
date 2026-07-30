# Spec: task-move

## Problem
Tasks created in the wrong project cannot be reassigned. The only workaround is
manual recreation. This blocks multi-project workflows where sub-project tasks
end up in the parent project (or vice versa).

## Solution
Add `plan_task_move` MCP tool that reassigns a context (task) to a different project
via a single UPDATE, and reports attached file paths with full source→target paths so
the caller knows what to move on disk.

## Nag condition satisfied
- `user_state` rows in source project pointing to the moved context are cleared
- `global_state.active_context_id` is nulled if it points to the moved context
- Name clash in target project is checked before any write

## New function: context.py — `move_task()`

```python
def move_task(conn, context_id: int, target_project_id: int) -> dict:
```

Returns:
```python
{
    "context_id": int,
    "name": str,
    "from_project": {"id": int, "project_name": str, "absolute_path": str},
    "to_project":   {"id": int, "project_name": str, "absolute_path": str},
    "attachments":  [{"file_path": str, "from": str, "to": str}],
}
```

Steps:
1. Load source context row — error if not found
2. Load source project row
3. Load target project row — error if not found
4. Check UNIQUE constraint: `SELECT id FROM contexts WHERE project_id=? AND name=?`
   — error if clash
5. Fetch context-level attachments (context_id = context_id) for path reporting
6. BEGIN:
   - UPDATE contexts SET project_id=?, updated_at=? WHERE id=?
   - DELETE FROM user_state WHERE active_context_id=? (stale source cursor)
   - UPDATE global_state SET active_context_id=NULL WHERE active_context_id=?
   - COMMIT
7. Build attachment path list: for each attachment,
   from = source_abs_path / file_path
   to   = target_abs_path / file_path

## New handler: mcpptool.py — `_cmd_task_move()`

Args: `name` (required), `project` (required — target project name or id)

- Resolves source task by name in current workspace project
- Resolves target project by name (try exact match) or by id if arg is integer
- Calls `move_task(conn, context_id, target_project_id)`
- Formats display with from/to paths and attachment move list

## tool.yaml — new entry

```yaml
- name: plan_task_move
  description: "Move a task to a different project. Reports attached file paths to move manually."
  inputSchema:
    type: object
    required: [name, project]
    properties:
      name:
        type: string
        description: "Task name to move"
      project:
        type: string
        description: "Target project name or numeric ID"
```

## README.md

Add one row to the Task tools table:
`plan_task_move` | Move a task to a different project (reports attached files to move manually)

## Files changing
- context.py: add move_task() after relink_project()
- mcpptool.py: add _cmd_task_move(), add to dispatch map
- tool.yaml: add plan_task_move tool entry
- README.md: add table row

## Files NOT changing
- schema.sql / schema_patches: no schema changes needed
- db.py: no changes needed
- backup.py: no changes needed

## source_hash
context.py:  5248f6c1299fae11b53db6cb67ff166fd5df92fbe176f67320914f9de430ffe5
mcpptool.py: 15d60483c9356d7c93eb596aa53e9308c4852fc06d4d6f79e72304262b5f59fc
tool.yaml:   2415e590b3bcb66b1a337aca6d199f89720df02c5d45ebe3a53e82f335df8c57
README.md:   da3793757f7e6252d71281821a2660556386588ff045d85cfe7b8037ba24b3bc
