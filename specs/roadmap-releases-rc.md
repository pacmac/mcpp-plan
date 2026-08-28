# roadmap-releases-rc — Releases and Release Candidates

## Purpose

The roadmap currently models a work queue (areas + tasks + gating). It has no concept of
a *shippable deliverable*. This spec adds releases and release candidates so a project can:

- Define a named release (e.g. "v1.0") with a target date and scope
- Subdivide it into RC1, RC2, … with the rule that RC(n+1) cannot start until RC(n) is released
- Answer "what is blocking RC2?" using existing area/task/idiot data
- Record release notes when an RC ships

## Schema — three new tables (patch-20)

### `releases`

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER FK → project | |
| name | TEXT NOT NULL | e.g. "v1.0", "mesh-gateway-1.0" |
| description_md | TEXT | |
| state | TEXT | planning \| active \| released \| abandoned |
| target_date | TEXT | ISO date (YYYY-MM-DD) |
| start_date | TEXT | ISO date |
| released_at | TEXT | ISO timestamp set when state→released |
| notes_md | TEXT | release notes |
| created_at | TEXT | |
| updated_at | TEXT | |
| UNIQUE(project_id, name) | | |

### `release_candidates`

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| release_id | INTEGER FK → releases | |
| rc_number | INTEGER NOT NULL | 1, 2, 3 … 0 = GA/final |
| state | TEXT | planning \| active \| released \| abandoned |
| start_date | TEXT | ISO date |
| target_date | TEXT | ISO date |
| released_at | TEXT | ISO timestamp |
| notes_md | TEXT | |
| created_at | TEXT | |
| updated_at | TEXT | |
| UNIQUE(release_id, rc_number) | | |

**Gate**: `plan_rc_start` checks that all earlier RCs for this release have
`state = 'released'` before allowing `active`. Enforced in Python, not a trigger.

### `release_areas`

| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| release_id | INTEGER FK → releases | |
| rc_id | INTEGER FK → release_candidates | NULL = applies to whole release |
| area_id | INTEGER FK → areas | |
| created_at | TEXT | |
| UNIQUE(release_id, rc_id, area_id) | | |

Scope is additive: areas on the release apply to every RC unless an RC overrides with its
own explicit set.

## Exit criteria for `plan_rc_release`

Two hard checks, one warning:

1. **Open tasks = 0** — all `contexts` scoped to an in-scope area must be `status = 'completed'`.
   Bug tracking is expected to use tasks (filed in areas), not a separate ledger. No special
   `idiot.yaml` check — not all projects use it, and a file-watch gate would read zero while
   known defects stand in task form.

2. **Open depends = 0** — area's `depends` list must contain no area with open tasks (same
   check as `roadmap_next` gating, scoped to the RC's areas).

3. **Warning (non-blocking)** — if the project has open tasks in *no area*, `plan_rc_release`
   reports: "N open task(s) unfiled — not counted by this gate." The caller decides whether to
   block on that or proceed. Tasks intentionally out of scope need not be filed to pass, but
   invisible work must at least be visible.

If any hard criterion fails, `plan_rc_release` returns a blocking list, not an error.

## Tools

| tool | purpose |
|---|---|
| `plan_release_new` | create a release (name, description, target_date, start_date) |
| `plan_release_list` | list releases for the project |
| `plan_release_show` | show one release with its RCs, scope, and blocking summary |
| `plan_release_notes` | set/append release notes_md |
| `plan_release_state` | set state: planning → active → released \| abandoned |
| `plan_rc_new` | add RC to a release (rc_number auto-increments if omitted) |
| `plan_rc_start` | set RC active; gate checks previous RC released |
| `plan_rc_release` | attempt to release RC; returns blockers or succeeds |
| `plan_rc_notes` | set/append RC notes_md |
| `plan_release_scope` | add or remove an area from a release or specific RC |

Existing tools updated:
- `roadmap_next` — adds optional `--release`/`--rc` filter; gated areas now also show
  which RC they are scoped to
- `roadmap_all` — shows release/RC column per area when a filter is active

## Files changing

- `schema_patches/patch-20.sql` — new tables
- `db.py` — `LATEST_SCHEMA_VERSION = 20`
- `context.py` — release/RC CRUD and exit-criteria check
- `mcpptool.py` — new `_cmd_release_*` and `_cmd_rc_*` handlers
- `tool.yaml` — new tool definitions

## Out of scope

- UI / web view (node-dash integration — separate task)
- Automatic idiot-entry scanning (needs idiot library import; phase 2)
- Flow `areas.yaml` reconciliation — tracked in `[who-owns-the-area-registry]`
