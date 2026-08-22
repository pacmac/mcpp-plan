# Spec: fix-roadmap-cannot-display

## Bug

`_cmd_roadmap_focus`, `_cmd_roadmap_next`, `_cmd_roadmap_all` return `success: False`
with an `error` string but NO `display` field on the CANNOT path (no areas defined).

The MCP framework surfaces the raw error string rather than formatted text.
The success path already has a `display` field; the CANNOT path must too.

## Fix

Add `display` to every `return {"success": False, ...}` in all three roadmap commands
in `mcpptool.py`. The display should be the same readable text an agent or user sees
on the success path — not an error trace.

### plan_roadmap_focus — no areas

```
display: "No areas defined for **{project_name}**.\nUse `plan_area_new` to define areas first."
```

### plan_roadmap_next — no areas

```
display: "**Roadmap next** (project: {project_name})\n\nNo areas defined. Use `plan_area_new` to create areas."
```

### plan_roadmap_all — no areas

```
display: "**Roadmap** (project: {project_name})\n\nNo areas defined. Use `plan_area_new` to create areas."
```

## Files changing

- `mcpptool.py` — `_cmd_roadmap_focus`, `_cmd_roadmap_next`, `_cmd_roadmap_all`

## Files NOT changing

- `context.py`, `tool.yaml`, `db.py`, schema_patches/
