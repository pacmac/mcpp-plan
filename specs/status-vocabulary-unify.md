# Spec: status-vocabulary-unify

## Bug

`tasks.status` uses `'complete'`; `contexts.status` uses `'completed'`. Any
cross-table query that uses one spelling for both silently returns zero rows for
the other. This already caused fix-roadmap-complete-count — roadmap_all_data was
counting `c.status='complete'` (wrong) against contexts, which always hold
`'completed'`. The root cause is the split vocabulary, not the query.

The fix chosen: migrate tasks to `'completed'` — it is the correct English past
tense, it is what contexts already use, and converging on it means every status
field in the DB says the same word for the same state.

## Schema change — patch-18

```sql
UPDATE tasks SET status = 'completed' WHERE status = 'complete';
-- The CHECK constraint on tasks.status must be widened or the column lacks one.
-- Check schema.sql first.
```

After the UPDATE, all code that checks `task.status == 'complete'` must be updated
to `'completed'`.

## Files changing

- `schema_patches/patch-18.sql` — UPDATE + CHECK widening if needed
- `context.py` — every literal `'complete'` in task status comparisons/sets
- `mcpptool.py` — every literal `'complete'` in task status comparisons/sets
- `schema.sql` — if CHECK constraint exists on tasks.status, update it

## Files NOT changing

- `db.py` — version bump only (18)
- `tool.yaml` — no schema exposed to callers
- `contexts.status` values — already correct, untouched

## Verification

After migration:
1. `SELECT DISTINCT status FROM tasks` → must contain only 'planned', 'started',
   'blocked', 'completed' — no 'complete'
2. Call plan_task_done on a step, then plan_task_complete on the task, then
   plan_roadmap_all — complete count must increment
