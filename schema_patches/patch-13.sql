-- patch-13: File attachments for projects, tasks, and steps
CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    label       TEXT,
    kind        TEXT NOT NULL DEFAULT 'ref',
    project_id  INTEGER REFERENCES project(id),
    context_id  INTEGER REFERENCES contexts(id),
    task_id     INTEGER REFERENCES tasks(id),
    created_at  TEXT NOT NULL,
    CHECK (
        (project_id IS NOT NULL) + (context_id IS NOT NULL) + (task_id IS NOT NULL) = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_attachments_project  ON attachments(project_id);
CREATE INDEX IF NOT EXISTS idx_attachments_context  ON attachments(context_id);
CREATE INDEX IF NOT EXISTS idx_attachments_task     ON attachments(task_id);
