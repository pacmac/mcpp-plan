# Spec: roadmap-description-and-steps

## Two display issues raised by bridge onboarding (17 areas)

### Issue 4 — plan_roadmap_all echoes full descriptions

Bridge's descriptions carry live defects with file:line. At 17 areas, the
output is ~10k tokens of prose with the actual roadmap (17 rows) invisible.

Fix: show only the first line of `description_md` in `plan_roadmap_all`.
No `verbose` flag for now — first line is the summary clause, which is
exactly what the roadmap shape view needs.

Implementation: `desc_line = (a.get("description_md") or "").split("\n")[0].strip()`
Use that instead of the full `a['description_md']` in the display line.
Empty description still shows no description.

### Issue 5 — unfiled section hides open step counts

`bridge-backlog`: 1 task, 60 steps, 46 open, spanning all 17 areas.
Roadmap reports "IN NO AREA (1 active task)". `command` reads 0 open
while three deployed units were blocked. The count is visibly incomplete.

Fix: `roadmap_all_data` adds `open_steps` to the unfiled query via LEFT
JOIN on `tasks`:

```sql
SELECT c.name, c.description_md,
       SUM(CASE WHEN t.status != 'complete' AND t.is_deleted = 0 THEN 1 ELSE 0 END) AS open_steps
FROM contexts c
LEFT JOIN tasks t ON t.context_id = c.id
WHERE c.project_id = ? AND c.area IS NULL AND c.status = 'active'
GROUP BY c.id
ORDER BY c.name
```

Display: if total open_steps across unfiled tasks > 0, append
"(N open steps total)" to the IN NO AREA line.

Per-task: if a task has open_steps > 0, show it in the list as
"`task-name` (N open steps)" so the reader sees which tasks are
step-heavy.

## Files changing

- `context.py` — roadmap_all_data unfiled query adds open_steps
- `mcpptool.py` — _cmd_roadmap_all: first-line description, step counts

## Files NOT changing

- `db.py`, schema_patches/, tool.yaml
