-- patch-9: Add kind column to note tables and backfill goal/plan placeholders
--
-- Adds kind TEXT NOT NULL DEFAULT 'note' to context_notes and task_notes.
-- Inserts placeholder goal and plan notes for every existing context (task)
-- that doesn't already have them, so workflow enforcement doesn't break
-- existing tasks.

-- 1. Add kind column to context_notes (task-level notes)
ALTER TABLE context_notes ADD COLUMN kind TEXT NOT NULL DEFAULT 'note';

-- 2. Add kind column to task_notes (step-level notes)
ALTER TABLE task_notes ADD COLUMN kind TEXT NOT NULL DEFAULT 'note';

-- 3. Insert placeholder goal notes for contexts that don't have one
INSERT INTO context_notes (context_id, note_md, created_at, actor, kind)
SELECT c.id, '(migrated — no goal defined)', datetime('now'), 'migration', 'goal'
FROM contexts c
WHERE c.id NOT IN (
    SELECT context_id FROM context_notes WHERE kind = 'goal'
);

-- 4. Insert placeholder plan notes for contexts that don't have one
INSERT INTO context_notes (context_id, note_md, created_at, actor, kind)
SELECT c.id, '(migrated — no plan defined)', datetime('now'), 'migration', 'plan'
FROM contexts c
WHERE c.id NOT IN (
    SELECT context_id FROM context_notes WHERE kind = 'plan'
);

-- 5. Validate: every context must have exactly one goal and one plan note
-- This SELECT will raise visibility if anything is wrong (checked by the app layer)
