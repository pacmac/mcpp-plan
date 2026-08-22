-- patch-16: completed_at on contexts for accurate last_closed in roadmap
-- No backfill: pre-patch completed rows get NULL, rendered as "last closed unknown".
-- A missing date is honest; updated_at is bumped by renames and is not the completion date.
ALTER TABLE contexts ADD COLUMN completed_at TEXT;
