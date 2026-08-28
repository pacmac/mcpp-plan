ALTER TABLE release_candidates ADD COLUMN commit_sha TEXT;
ALTER TABLE release_candidates ADD COLUMN artifact_ref TEXT;
ALTER TABLE release_candidates ADD COLUMN deployed_at TEXT;
ALTER TABLE release_candidates ADD COLUMN deployed_ref TEXT;
