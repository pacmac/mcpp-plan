# Spec: area-type-field

## Gap

Areas carry `class` (product|tooling), which answers WHO GETS IT. Nothing answers
HOW THE AREA CAN BE PROVEN, and that is the question that decides what work an
area needs.

`class` cannot stand in for it. Across every project in `plan.db`, measured
2026-09-13, the distribution is **63 product, 12 tooling, 14 unset** — 84% of
classed rows share one value, so the field cannot discriminate. (It read 61/9/19
earlier the same day; device is classing its areas as this is written, which is why
the figure moves and why it is dated rather than quoted flat.) An area of firmware
and an area of build
gates are both `product`/`tooling` rows, with nothing recording that one needs a
board on a cable and the other needs a check that has been seen to go RED.

Raised by `device` on the `device--mcpp-plan` board as
`areas-need-a-type-field-because-class-only-answers-who-gets-it`, at Peter's ask:
"I need to modify areas so that we can record in this and other repos."

## The ruling this implements

Posted to device as `device--mcpp-plan` #26.

**Seven values, closed set.** Each has a different answer to "what counts as proof",
which is the test for whether a value earns its place:

| value | is | proved by |
|---|---|---|
| `firmware` | runs on a device | hardware, or a build gate; never a host test |
| `service` | a long-running host process | it is running, and answering |
| `library` | code with no lifetime | host tests |
| `contract` | a shared wire format or schema | peers agree, and a hash gate holds it |
| `tool` | a human or a build runs it | it runs from where you would reach for it |
| `gate` | a check that fails a build | it has been shown to go RED, not merely green |
| `doc` | prose that governs work | it matches the code it cites |

**Single value, not a list.** The field says what proving the area COSTS; a list of
two proofs makes neither of them required. Tiebreak: the type is the one whose
proof, if skipped, would let a defect through. An area needing two independent
proofs is two areas.

**`class` is untouched.** product|tooling stays exactly as it is. The two are
independent axes.

**Nullable, no default, no backfill.** 70 area rows exist with no type. A guessed
backfill asserts a proof nobody chose.

**Ordering does not change.** Design rule E3 — product before tooling, never
interleaved — stays keyed on `class` alone. A second sort key would move every
roadmap in every repo on the day the field lands, for no gain.

## Schema — `schema_patches/patch-22.sql` (new)

```sql
ALTER TABLE areas ADD COLUMN type TEXT CHECK(type IN
  ('firmware','service','library','contract','tool','gate','doc'));
```

`db.py:26` — `LATEST_SCHEMA_VERSION = 21` → `22`.

`type` is not a reserved word in SQLite. It IS a Python builtin, so every Python
parameter and local is named `area_type`, matching the existing `area_class`.

## `context.py`

### New, beside `_validate_area_class` (line 1189)

```python
AREA_TYPES = ("firmware", "service", "library", "contract", "tool", "gate", "doc")


def _validate_area_type(area_type):
    if area_type is not None and area_type not in AREA_TYPES:
        raise ValueError(
            f"type must be one of {', '.join(AREA_TYPES)}; got '{area_type}'")
```

One Python copy of the vocabulary, named, reused by the error message. The SQL
CHECK constraint is a second copy and the two `tool.yaml` enums are a third and
fourth; those are unavoidable, being different languages. `class` is NOT
retro-fitted to this pattern — out of scope.

### `create_area` (line 1218)

`area_type=None` parameter; `_validate_area_type(area_type)` beside the class
call; `type` added to the INSERT column list and values; `"type": area_type` in
the returned dict.

### `create_areas_batch` (line 1249)

The same, against this function's own separate INSERT: `area_type = item.get("type")`,
validate, insert, and carry into the result dict.

### `list_areas` (line 1315)

Add `type` to the explicit SELECT column list.

### `update_area_description` (line 1390)

`area_type=None` and `_update_type=False` parameters; `_validate_area_type` at the
top beside the class call; a `if _update_type:` branch appending `"type = ?"` to
`sets` and the value to `params`, matching the existing branches exactly. Passing
`None` with the flag set clears the field, as `class` already does.

### `roadmap_all_data` (line 1451) and `area_stats` (line 1497)

Add `a.type` to each SELECT list. Neither `GROUP BY` nor `ORDER BY` changes.

## `mcpptool.py`

- `_cmd_area_new` (1314) — read `args.get("type")`, pass as `area_type` in single
  mode. Batch mode passes `items` through untouched and needs no change.
- `_cmd_area_describe` (1395) — read `type`, set `_update_type = "type" in args`,
  add it to the "supply at least one of" guard and its error string, pass it
  through, and report `type=<v|cleared>` in the `parts` summary.
- `_cmd_area_list` (1331) — append the type to the existing parenthesis when set:
  `- name (product, gate, priority 3)`. When unset, the parenthesis is unchanged.
  There is no "untyped" filler: `class` prints "unclassed" always, and doing the
  same for a field 70 rows do not have would be noise on every listing.
- `_cmd_roadmap_all` (1959) — in `_area_row`, append ` [gate]` after the area name
  when type is set. Sections and ordering are untouched.

## `tool.yaml`

Add a `type` property with the seven-value enum in three places:

- `plan_area_new` single-area properties (beside `class`, line 200)
- `plan_area_new` `items` properties (line 235)
- `plan_area_describe` properties (line 302)

Each description states the proof, not just the noun — the proof is the reason the
value exists. Extend both tool `description:` strings to name `type` alongside
`class`.

## Test — `test_area_type.py` (new)

Follows `test_attachments.py`'s idiom (temp dir, `report()`, PASS/FAIL, exit code).

**It cannot build its DB from `schema.sql` alone.** `schema.sql` has no `areas`
table; it sits at schema version 9, and the areas table arrives in patch-14. The
test therefore does `executescript(schema.sql)` then
`db.apply_schema_patches(conn, 9)`, which is the real migration path and reaches
version 22. Determined empirically: starting from 8 fails on `duplicate column
name: kind`, from 9 upward succeeds.

Proves:

1. `LATEST_SCHEMA_VERSION` is 22 and `areas` has a `type` column.
2. `create_area(..., area_type="gate")` round-trips through `list_areas`.
3. `create_area(..., area_type="nonsense")` raises ValueError.
4. `create_areas_batch` sets type per item, and one bad type rolls the whole batch back.
5. `update_area_description` sets a type on an existing area, and clears it.
6. An area created with no type reads back `None` — no default, no backfill.
7. `area_stats` and `roadmap_all_data` both return the type.
8. Setting `type` does not alter `class`, and ordering is unchanged by type.

Red today at test 1: the column does not exist. Green after the change.

## Files changing

- `schema_patches/patch-22.sql` — new
- `db.py` — version constant only
- `context.py`
- `mcpptool.py`
- `tool.yaml`
- `test_area_type.py` — new

## Files explicitly NOT changing, and why

- **`server.py`** — it renders `a.class` as a badge at line 219 and in the
  not-started panel at 237, and `area_stats` will now carry `type`, so the data
  reaches it. The badge is deliberately not added: CLAUDE.md requires a real
  browser check in both themes for any UI change, and the Playwright MCP server is
  disconnected this session. Shipping an unverifiable UI change to hit a deadline
  is the thing that rule exists to stop. Registered separately as
  `the-area-stats-view-shows-class-but-not-type`.
- **`schema.sql`** — the baseline, by the design stated in
  `specs/areas-integration.md` line 298. It has no `areas` table to alter. That
  a fresh DB therefore never gets one is a real defect, registered as
  `a-fresh-db-is-stamped-at-latest-and-skips-every-patch-from-8`, and is not
  fixed here.
- **`class`, and everything that reads it** — the ruling keeps it as it is.
- **The RC gate** — once `type` exists it could ask "has this area been proven the
  way its type requires", which today it cannot ask at all. Separate item, not
  opened.
