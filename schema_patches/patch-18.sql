-- patch-18: unify task status vocabulary — 'complete' -> 'completed'
-- contexts.status has always used 'completed'; tasks used 'complete'.
-- Any cross-table query using one spelling for both silently returned zero rows.
UPDATE tasks SET status = 'completed' WHERE status = 'complete';
