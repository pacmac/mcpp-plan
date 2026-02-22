-- patch-11: Populate sub_index as sequential step number per context
-- 1. NULL sub_index on soft-deleted rows (they have no position)
UPDATE tasks SET sub_index = NULL WHERE is_deleted = 1;

-- 2. Renumber non-deleted rows per context sequentially from 1
UPDATE tasks SET sub_index = (
    SELECT rn FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY context_id ORDER BY task_number) AS rn
        FROM tasks WHERE is_deleted = 0
    ) numbered WHERE numbered.id = tasks.id
) WHERE is_deleted = 0;

-- 3. Unique index (NULLs are distinct in SQLite, so deleted rows don't conflict)
DROP INDEX IF EXISTS idx_tasks_context_subindex;
CREATE UNIQUE INDEX idx_tasks_context_subindex ON tasks(context_id, sub_index);
