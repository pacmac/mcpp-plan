-- Add user layer: project > user > task > step

-- Users table (auto-populated from OS login)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

-- Per-user active-task state (replaces global_state singleton)
CREATE TABLE IF NOT EXISTS user_state (
    user_id INTEGER PRIMARY KEY,
    active_context_id INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (active_context_id) REFERENCES contexts(id)
);

-- Link tasks to users
ALTER TABLE contexts ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_contexts_user ON contexts(user_id);
