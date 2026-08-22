-- patch-14: functional areas table and area field on contexts
CREATE TABLE IF NOT EXISTS areas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES project(id),
    name            TEXT NOT NULL,
    description_md  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_areas_project ON areas(project_id);

ALTER TABLE contexts ADD COLUMN area TEXT;
