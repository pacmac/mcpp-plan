# Spec: fix-areas-nag-false-alarm

## Problem

The areas nag added in `areas-integration` fires in any repo with active tasks
but no `areas` rows in plan.db. This is correct for repos that NEVER had any area
definition (e.g. bridge, mesh-gw). It is a FALSE ALARM for repos that define areas
in `docs/specs/AREAS.yaml` — those repos have a valid area definition, just not
yet in plan.db.

Roadmap measured this immediately after `areas-integration` landed: their repo had
one area in AREAS.yaml and zero in plan.db, and the nag fired every call.

## Root cause

`mcpptool.py` execute() injection block (after stale-nag):

```python
if _proj_id and not has_areas and has_tasks:
    result["display"] += "\n\n---\n📋 No areas defined..."
```

Only checks plan.db. Does not know whether the repo has AREAS.yaml.

## Fix

Gate the nag additionally on whether `docs/specs/AREAS.yaml` is absent from the
workspace directory. If that file exists, the repo has area definitions and the
nag is a false alarm.

```python
_areas_yaml = Path(workspace_dir) / "docs" / "specs" / "AREAS.yaml"
if _proj_id and not _areas_yaml.exists():
    # ... existing check for has_areas / has_tasks
```

This check is purely a file existence test — no import of claude/areas, no reading
the file. It suppresses the false alarm without importing or depending on AREAS.yaml
content.

## Design note

This fix is intentionally conservative. It does NOT decide whether plan.db areas
should mirror AREAS.yaml, replace it, or act as a fallback for repos without one.
That is a Peter-level design decision (tracked separately, pending his return from
AFK). This fix only stops the regression (nag where it should not nag).

When Peter rules:
- If (a) plan.db replaces AREAS.yaml entirely: remove this gate, AREAS.yaml is gone
- If (b) plan.db mirrors: the nag becomes "areas not synced from AREAS.yaml"
- If (c) plan.db is for repos without AREAS.yaml: this gate stays permanently

## Files changing

- `mcpptool.py` — execute() injection block (areas nag section)

## Files NOT changing

- `context.py`, `db.py`, `tool.yaml`, `README.md`

## Verification

1. Call any plan tool from `/usr/share/pac/dev/py/mcpp-roadmap` (has AREAS.yaml) —
   nag must NOT appear.
2. Call any plan tool from `/usr/share/pac/dev/py/mcpp-plan` (no AREAS.yaml, no
   plan.db areas) — nag MUST appear.

## source_hash

mcpptool.py: ~
