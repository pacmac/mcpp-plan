-- Centralize DB: multi-project support
-- Idempotent: handles partial previous runs.

-- 1. Recreate project table without singleton constraint (if needed)
CREATE TABLE IF NOT EXISTS project_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    absolute_path TEXT NOT NULL UNIQUE,
    description_md TEXT,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO project_new (id, project_name, absolute_path, description_md, created_at)
    SELECT id, project_name, absolute_path, description_md, created_at FROM project;

DROP TABLE IF EXISTS project;
ALTER TABLE project_new RENAME TO project;

-- 2. Add project_id to contexts if not present
-- (Recreating is safest to drop the UNIQUE constraint on name)
CREATE TABLE IF NOT EXISTS contexts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description_md TEXT,
    user_id INTEGER REFERENCES users(id),
    project_id INTEGER REFERENCES project(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO contexts_new (id, name, status, description_md, user_id, project_id, created_at, updated_at)
    SELECT id, name, status, description_md, user_id, COALESCE(project_id, 1), created_at, updated_at FROM contexts;

-- FK checks disabled by apply_schema_patches() in Python.
DROP TABLE IF EXISTS contexts;
ALTER TABLE contexts_new RENAME TO contexts;

CREATE INDEX IF NOT EXISTS idx_contexts_user ON contexts(user_id);

-- 3. Recreate user_state as per-user-per-project
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

INSERT OR IGNORE INTO user_state_new (user_id, project_id, active_context_id, updated_at)
    SELECT user_id, 1, active_context_id, updated_at FROM user_state;

DROP TABLE IF EXISTS user_state;
ALTER TABLE user_state_new RENAME TO user_state;
