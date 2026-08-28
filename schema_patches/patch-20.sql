-- patch-20: releases, release_candidates, release_areas
-- Adds first-class release/RC objects so a project can define shippable deliverables,
-- scope areas to each RC, and gate RC(n+1) on RC(n) being released.

CREATE TABLE IF NOT EXISTS releases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER REFERENCES project(id),
    name        TEXT NOT NULL,
    description_md TEXT,
    state       TEXT NOT NULL DEFAULT 'planning',  -- planning|active|released|abandoned
    start_date  TEXT,   -- ISO date YYYY-MM-DD
    target_date TEXT,   -- ISO date YYYY-MM-DD
    released_at TEXT,   -- ISO timestamp, set when state->released
    notes_md    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(project_id, name)
);

CREATE TABLE IF NOT EXISTS release_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id  INTEGER NOT NULL REFERENCES releases(id),
    rc_number   INTEGER NOT NULL,  -- 1,2,3... sequential; 0=GA/final
    state       TEXT NOT NULL DEFAULT 'planning',  -- planning|active|released|abandoned
    start_date  TEXT,
    target_date TEXT,
    released_at TEXT,
    notes_md    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(release_id, rc_number)
);

CREATE TABLE IF NOT EXISTS release_areas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id  INTEGER NOT NULL REFERENCES releases(id),
    rc_id       INTEGER REFERENCES release_candidates(id),  -- NULL = applies to whole release
    area_id     INTEGER NOT NULL REFERENCES areas(id),
    created_at  TEXT NOT NULL
);

-- Partial unique indexes handle nullable rc_id correctly (SQLite NULL != NULL in UNIQUE).
CREATE UNIQUE INDEX IF NOT EXISTS idx_release_areas_release
    ON release_areas(release_id, area_id) WHERE rc_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_release_areas_rc
    ON release_areas(release_id, rc_id, area_id) WHERE rc_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_releases_project ON releases(project_id);
CREATE INDEX IF NOT EXISTS idx_release_candidates_release ON release_candidates(release_id);
CREATE INDEX IF NOT EXISTS idx_release_areas_rc_id ON release_areas(rc_id);
CREATE INDEX IF NOT EXISTS idx_release_areas_area ON release_areas(area_id);
