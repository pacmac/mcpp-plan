# release-scope-insertion-order

## Gap

`get_release` returns scope areas ordered `ORDER BY ra.rc_id NULLS FIRST, a.name`.
The `a.name` secondary sort is alphabetical, erasing insertion order.
To a viewer this looks like a priority ranking. It is not — it is an accident.

## Fix

Change the ORDER BY to `ra.rc_id NULLS FIRST, ra.id` so areas appear in the order
they were added to the release (`ra.id` is an AUTOINCREMENT, so lower id = added first).

## Files changing

- `context.py` — `get_release` only, the `SELECT … FROM release_areas` query
