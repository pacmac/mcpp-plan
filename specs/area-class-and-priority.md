# Spec: area-class-and-priority

## Gap

Areas have no class (product|tooling) or priority. Roadmap lists alphabetically.
Three sessions (device, roadmap, bridge) confirmed it: tooling areas interleave
with product, which is the one thing the design says must never happen.

Design rule E3: "PRODUCT BEFORE TOOLING IN EVERY LISTING, and the classes NEVER
INTERLEAVE whatever the priorities say."

## Schema change — patch-17

```sql
ALTER TABLE areas ADD COLUMN class TEXT CHECK(class IN ('product','tooling'));
ALTER TABLE areas ADD COLUMN priority INTEGER;
```

No NOT NULL, no default — existing areas are unclassed. Roadmap shows them in
a distinct "Unclassed" section and does not pretend they have a class.

## Ordering

Everywhere areas are listed:
```sql
ORDER BY
  CASE WHEN class='product' THEN 0 WHEN class='tooling' THEN 1 ELSE 2 END,
  COALESCE(priority, 999999),
  name
```

Product (priority ASC, nulls last), then Tooling (same), then Unclassed (alpha).

## Display

### plan_roadmap_all

Section headers separate the groups:

```
**Roadmap** (project: foo)

**Product**
  - **act** — First line of description: 2 open, 1 complete
  - **aim** — 3 open

**Tooling**
  - **charts** — 0 open, 3 complete (done, last closed 2026-08-20)

**Unclassed** (use plan_area_describe to set class)
  - **queue** — 1 open
```

Omit a section if empty.

### plan_roadmap_next

work_now list shows class as a section label:

```
**Work now — Product:**
  - **act** — 3 open task(s)

**Work now — Tooling:**
  - **charts** — 1 open task(s)

**Work now — Unclassed:**
  - **queue** — 2 open task(s)
```

Done / Never examined sections are unchanged (already per-area, ordering covers it).

### plan_area_list

Include class and priority in each row. Show "(unclassed)" where class is NULL.

## Tools

### plan_area_new — add class and priority

```
class: string ('product' | 'tooling') — optional
priority: integer — optional
```

Both supported in single and batch mode. Validated against ('product','tooling').

### plan_area_describe — extend to set class and priority

Add `class` and `priority` params alongside `description`. Any combination can
be updated in one call. Validate class value.

## Files changing

- `schema_patches/patch-17.sql` — new
- `db.py` — bump to 17
- `context.py` — create_area, create_areas_batch, list_areas, update_area_description, roadmap_all_data
- `mcpptool.py` — _cmd_area_new, _cmd_area_describe, _cmd_roadmap_all, _cmd_roadmap_next
- `tool.yaml` — plan_area_new, plan_area_describe

## Files NOT changing

- `schema_patches/` (except new patch-17)
