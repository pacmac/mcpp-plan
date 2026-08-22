# Spec: never-examined-distinction

## Gap

`plan_roadmap_next` and `plan_roadmap_all` collapse two opposite states into
"nothing open":

- `open=0, complete>0` — DONE: all filed tasks are closed
- `open=0, complete=0` — NEVER EXAMINED: no tasks ever filed against this area

These are not the same. Discovered in first real use (17 areas, RAK4631 firmware):
five areas in the "nothing open" bucket were all the second kind — unexamined,
not done. lifecycle had 1,895 lines of code and zero tasks. Not credible as done.

## Fix — no schema change needed

`roadmap_all_data` already returns `open` and `complete` per area. Split on those:

```python
work_now        = [a for a in areas if a["open"] > 0]
done            = [a for a in areas if a["open"] == 0 and a["complete"] > 0]
never_examined  = [a for a in areas if a["open"] == 0 and a["complete"] == 0]
```

### plan_roadmap_next display

```
**Work now:**
  - **area1** — 5 open task(s)

**Done:**
  - area2 — 3 complete

**Never examined:**
  - area3
  - area4
```

### plan_roadmap_all display

Each area row already shows open/complete counts. Add a marker:
- `(done)` when open=0, complete>0
- `(never examined)` when open=0, complete=0

### result payload changes

`plan_roadmap_next` payload currently has `parked`. Replace with three arrays:
- `ranked` — open > 0 (unchanged)
- `done` — open=0, complete>0 (was collapsed into parked)
- `never_examined` — open=0, complete=0 (was collapsed into parked)

Keep `parked` as an empty array for backwards compatibility — it is where gated
areas (depends, when that lands) will go.

## Files changing

- `mcpptool.py` — `_cmd_roadmap_next`, `_cmd_roadmap_all`

## Files NOT changing

- `context.py`, `tool.yaml`, `db.py`, schema_patches/
