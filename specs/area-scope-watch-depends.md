# Spec: area-scope-watch-depends

## Why

Design rules G2 (watch), G3 (scope), D1/D2 (depends) all require structured columns.
Without them the check "every tracked file lands in exactly one area, 0 unowned, 0
double-owned" cannot run. Encoding them in description_md would be capability loss —
nothing can parse and validate them.

## Schema change — patch-19

```sql
ALTER TABLE areas ADD COLUMN scope TEXT;
ALTER TABLE areas ADD COLUMN watch TEXT;
ALTER TABLE areas ADD COLUMN depends TEXT;
```

All three are TEXT. Values are JSON arrays of strings:
- `scope`: file glob patterns that define what files belong to this area
  (e.g. `["src/radio/**", "tests/test_radio.py"]`)
- `watch`: file paths/patterns whose change invalidates the area's sign-off
  (e.g. `["rak/v3/src/main.cpp"]`)
- `depends`: area names this area depends on — gates ordering (D1)
  (e.g. `["radio-link", "power-and-sleep"]`)

NULL means not set. Empty JSON array `[]` is distinct from NULL (explicitly empty).

## Rules (from design rules doc)

- D1: a gated area (has open depends) is NOT STARTABLE however good its priority.
  plan_roadmap_next must put it after all ungated areas, with a note naming the
  open dependency.
- D2: depends cannot be derived — humans author these edges.
- G2: watch explains why an area re-opens. plan_roadmap_all should name watched
  files alongside each area.
- G3: scope enables the file-ownership check. A test can verify 0 unowned,
  0 double-owned across all scopes.

## Tools changing

### plan_area_new (single + batch)
- Add `scope` (array of strings), `watch` (array of strings), `depends` (array of
  strings) to inputSchema.
- Stored as JSON. Validate: depends names must be existing areas (at write time).

### plan_area_describe
- Add same three fields. Same validation.

### plan_area_list
- Show scope/watch/depends per area when set. Omit when NULL.

### plan_roadmap_next
- After class/priority ordering, move gated areas (depends has an area that is
  still active/has open tasks) to a "Gated" section:
  `(gated by <area> — N open tasks)`
- An area with all dependencies done (or no depends) is ungated.

### plan_roadmap_all
- Show depends/watch per area when set.

## context.py changes

- `create_area`: add scope, watch, depends params (JSON-encode before storing)
- `create_areas_batch`: read scope/watch/depends from item dict
- `update_area_description`: extend with scope/watch/depends update support
- `list_areas`: SELECT scope, watch, depends
- `roadmap_all_data`: SELECT scope, watch, depends; annotate areas with open_depends
  (list of depends names that still have open contexts)

## db.py
- Bump LATEST_SCHEMA_VERSION to 19

## Files changing
- `schema_patches/patch-19.sql` — new
- `db.py` — version 19
- `context.py` — create_area, create_areas_batch, update_area_description,
  list_areas, roadmap_all_data
- `mcpptool.py` — _cmd_area_new, _cmd_area_describe, _cmd_area_list,
  _cmd_roadmap_next, _cmd_roadmap_all
- `tool.yaml` — plan_area_new, plan_area_describe

## Files NOT changing
- `schema.sql` (patches only)
- `specs/area-class-and-priority.md` (predecessor, complete)
