# Spec: roadmap-payload-cleanup

## Two issues raised by device after first real use of never-examined

### Issue 1 — `parked: []` is a semantic trap

`plan_roadmap_next` currently returns `parked: []` for backwards compatibility.
Right now it means "parking feature not supported yet". After `depends` lands it
will mean "nothing is gated". A consumer that learned the first meaning reads
the second as good news — a silent breaking change.

Fix: drop `parked` from the payload now. No key = feature not present.
When `depends` lands, the key appears and its meaning is unambiguous.

### Issue 2 — done areas carry no date

"Done" (open=0, complete>0) is not terminal — areas re-open when new code or
tooling arrives. A date on the done row tells the reader how stale "done" is,
and prevents mistrust when a done area sprouts a task.

`contexts` has no `completed_at` — only `updated_at`. Best proxy:
`MAX(updated_at) WHERE status='complete'` per area.

Display:
- `plan_roadmap_next` done section: `- area2 — 3 complete (last closed 2026-08-20)`
- `plan_roadmap_all` done marker: `(done, last closed 2026-08-20)`

## Implementation

### context.py — roadmap_all_data

Add `MAX(CASE WHEN c.status='complete' THEN c.updated_at END) AS last_closed`
to the SELECT:

```sql
SELECT a.name, a.description_md,
       COUNT(CASE WHEN c.status='active' THEN 1 END) AS open,
       COUNT(CASE WHEN c.status='complete' THEN 1 END) AS complete,
       MAX(CASE WHEN c.status='complete' THEN c.updated_at END) AS last_closed
FROM areas a
LEFT JOIN contexts c ON c.project_id = a.project_id AND c.area = a.name
WHERE a.project_id = ?
GROUP BY a.id ORDER BY a.name
```

### mcpptool.py — _cmd_roadmap_next

- Remove `"parked": []` from result payload
- In done section display: append `(last closed YYYY-MM-DD)` using `a["last_closed"][:10]`
  if `last_closed` is not None

### mcpptool.py — _cmd_roadmap_all

- In done marker: `(done, last closed YYYY-MM-DD)` if date available, else `(done)`

## Files changing

- `context.py` — roadmap_all_data SQL query
- `mcpptool.py` — _cmd_roadmap_next, _cmd_roadmap_all

## Files NOT changing

- `db.py`, schema_patches/, tool.yaml (no schema change, no new tool)
