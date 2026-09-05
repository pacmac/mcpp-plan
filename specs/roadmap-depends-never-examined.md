# roadmap-depends-never-examined

## Bug

`plan_roadmap_all` renders an area with 0 tasks as `(never examined)` in its own
row — correctly. But in every *dependent* area's `depends:` list, that same area
appears as `(done)`. Zero-open is indistinguishable from zero-open-zero-complete,
so a never-started area satisfies the dependency gate.

On a board used to decide what is startable, this is actively misleading: it can
show `web` as unblocked when `api` has no code and no tasks at all.

## Fix

Wherever the depends-line label is computed, add the total-tasks check before
calling an area done:

```
if total == 0:    "(never examined)"
elif open == 0:   "(done)"
else:             f"({open} open)"
```

## Files changing

- `context.py` — `roadmap_all_data` or wherever the depends label is emitted
  (confirm with grep before editing)
