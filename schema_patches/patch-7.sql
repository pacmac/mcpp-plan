-- Centralize DB: multi-project support
-- Safe migration: uses ALTER TABLE for contexts (no recreation needed),
-- and verified table recreation only where SQLite requires it
-- (constraint changes on project and user_state).
-- Data integrity is enforced by the backup.py safety pipeline
-- (trial-on-copy + row count validation) BEFORE this runs on the live DB.

-- 1. Add project_id to contexts (no table recreation needed).
ALTER TABLE contexts ADD COLUMN project_id INTEGER REFERENCES project(id);
UPDATE contexts SET project_id = 1 WHERE project_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_contexts_user ON contexts(user_id);

-- 2. Recreate project table without singleton CHECK constraint.
--    SQLite cannot alter constraints, so recreation is required.
CREATE TABLE IF NOT EXISTS project_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    absolute_path TEXT NOT NULL UNIQUE,
    description_md TEXT,
    created_at TEXT NOT NULL
);

INSERT INTO project_new (id, project_name, absolute_path, description_md, created_at)
    SELECT id, project_name, absolute_path, description_md, created_at FROM project
    WHERE TRUE
    ON CONFLICT(id) DO NOTHING;

DROP TABLE project;
ALTER TABLE project_new RENAME TO project;

-- 3. Recreate user_state as per-user-per-project composite PK.
CREATE TABLE IF NOT EXISTS user_state_new (
    user_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    active_context_id INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES project(id),
    FOREIGN KEY (active_context_id) REFERENCES contexts(id)
);

INSERT INTO user_state_new (user_id, project_id, active_context_id, updated_at)
    SELECT user_id, 1, active_context_id, updated_at FROM user_state
    WHERE TRUE
    ON CONFLICT(user_id, project_id) DO NOTHING;

DROP TABLE user_state;
ALTER TABLE user_state_new RENAME TO user_state;
