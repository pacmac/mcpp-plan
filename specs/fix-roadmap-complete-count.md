# Spec: fix-roadmap-complete-count

## Two bugs, one patch

### Bug 1 — status mismatch (complete count always 0)

`roadmap_all_data` counts `c.status='complete'` but `complete_context` sets
`status='completed'`. These never match. Complete count has always been 0.
Every area with completed contexts reads as "never examined" instead of "done".

Fix: change both `c.status='complete'` references in `roadmap_all_data` to
`c.status='completed'`.

### Bug 2 — last_closed uses updated_at (wrong timestamp)

`MAX(c.updated_at WHERE status='completed')` is bumped by rename, note-add,
area-assignment — any update, not just the completion event. A rename of a
completed context re-dates the "done" row.

Fix: add `completed_at TEXT` column to `contexts` (schema patch 16). Set it
in `complete_context` at the moment of transition. `roadmap_all_data` uses
`MAX(completed_at)`.

Backfill for existing completed contexts: `updated_at` is still the best
available proxy. Patch sets `completed_at = updated_at WHERE status='completed'`
for rows that predate the column.

## Files changing

- `schema_patches/patch-16.sql` — new
- `db.py` — bump LATEST_SCHEMA_VERSION to 16
- `context.py` — complete_context sets completed_at; roadmap_all_data fixes
  status string and uses completed_at

## Files NOT changing

- `mcpptool.py`, `tool.yaml`
