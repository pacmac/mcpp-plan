-- patch-10: Rename 'archived' status to 'completed' on contexts table
UPDATE contexts SET status = 'completed' WHERE status = 'archived';
