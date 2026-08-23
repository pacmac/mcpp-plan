-- patch-19: scope, watch, depends columns on areas
-- G2 (watch), G3 (scope), D1/D2 (depends) require structured columns.
-- Without them the file-ownership check and dependency gating cannot run.
ALTER TABLE areas ADD COLUMN scope TEXT;
ALTER TABLE areas ADD COLUMN watch TEXT;
ALTER TABLE areas ADD COLUMN depends TEXT;
