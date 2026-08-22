-- patch-16: completed_at on contexts for accurate last_closed in roadmap
ALTER TABLE contexts ADD COLUMN completed_at TEXT;
UPDATE contexts SET completed_at = updated_at WHERE status = 'completed';
