CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    absolute_path TEXT NOT NULL UNIQUE,
    description_md TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description_md TEXT,
    user_id INTEGER REFERENCES users(id),
    project_id INTEGER REFERENCES project(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id INTEGER NOT NULL,
    note_md TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor TEXT,
    kind TEXT NOT NULL DEFAULT 'note',
    FOREIGN KEY (context_id) REFERENCES contexts(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id INTEGER NOT NULL,
    task_number INTEGER,
    title TEXT NOT NULL,
    description_md TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    is_deleted INTEGER NOT NULL DEFAULT 0,
    parent_id INTEGER,
    sort_index INTEGER,
    sub_index INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (context_id) REFERENCES contexts(id),
    FOREIGN KEY (parent_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS task_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    note_md TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS context_state (
    context_id INTEGER PRIMARY KEY,
    active_task_id INTEGER,
    last_task_id INTEGER,
    next_step TEXT,
    status_label TEXT,
    last_event TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (context_id) REFERENCES contexts(id),
    FOREIGN KEY (active_task_id) REFERENCES tasks(id),
    FOREIGN KEY (last_task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS global_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_context_id INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (active_context_id) REFERENCES contexts(id)
);

CREATE TABLE IF NOT EXISTS user_state (
    user_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    active_context_id INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES project(id),
    FOREIGN KEY (active_context_id) REFERENCES contexts(id)
);

CREATE TABLE IF NOT EXISTS changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id INTEGER,
    task_id INTEGER,
    action TEXT NOT NULL,
    details_md TEXT,
    created_at TEXT NOT NULL,
    actor TEXT,
    FOREIGN KEY (context_id) REFERENCES contexts(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_context_status ON tasks(context_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_task_notes_task ON task_notes(task_id);
CREATE INDEX IF NOT EXISTS idx_context_notes_context ON context_notes(context_id);
CREATE INDEX IF NOT EXISTS idx_changelog_context_created ON changelog(context_id, created_at);
CREATE INDEX IF NOT EXISTS idx_changelog_task_created ON changelog(task_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_context_number ON tasks(context_id, task_number);
CREATE INDEX IF NOT EXISTS idx_contexts_user ON contexts(user_id);
-- NOTE: idx_contexts_project and idx_contexts_project_name are created
-- by patch-7.sql for existing DBs, and by ensure_schema() post-patch for new DBs.
