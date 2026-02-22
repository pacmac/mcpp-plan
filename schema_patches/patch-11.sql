-- patch-11: Backfill sub_index from task_number and add unique constraint
UPDATE tasks SET sub_index = task_number WHERE sub_index IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_context_subindex ON tasks(context_id, sub_index);
