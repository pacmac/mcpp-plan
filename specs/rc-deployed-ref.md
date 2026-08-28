# rc-deployed-ref

## Gap

`plan_rc_release` transitions an RC to "released" with no record of:
- what commit it was cut from (`commit_sha`)
- what artifact was built (`artifact_ref`)
- whether it ever ran on hardware (`deployed_at`, `deployed_ref`)

"Released" and "shipped" are indistinguishable. This is the same class of bug as
rc-gate-green-on-unprovable-area: the tool is confident about something nobody checked.

## Fix

### Schema (patch-21)

Add four nullable columns to `release_candidates`:

```sql
ALTER TABLE release_candidates ADD COLUMN commit_sha TEXT;
ALTER TABLE release_candidates ADD COLUMN artifact_ref TEXT;
ALTER TABLE release_candidates ADD COLUMN deployed_at TEXT;
ALTER TABLE release_candidates ADD COLUMN deployed_ref TEXT;
```

### release_rc changes (context.py)

- Auto-capture `commit_sha` via `git rev-parse HEAD` at call time (subprocess,
  cwd = workspace root derived from db path). If git unavailable or fails, store
  NULL and add warning: "commit_sha could not be captured (git unavailable)".
- Accept optional `artifact_ref: str = None` param. Store as-is, never interpreted.
- After storing, if `artifact_ref IS NULL`, append warning:
  "RC released with no artifact reference recorded".

### New: deploy_rc (context.py)

```python
def deploy_rc(conn, release_name, rc_number, project_id, deployed_ref=None) -> dict:
```

- RC must exist and be in state "released" (not "planning" or "active").
- Sets `deployed_at = db.utc_now_iso()`, `deployed_ref = deployed_ref`.
- Returns updated RC dict.

### get_release / plan_release_show

RC rows in the response gain: `commit_sha`, `artifact_ref`, `deployed_at`,
`deployed_ref`. Display format in `_cmd_release_show`:

```
RC1 [released]  commit: 7332ebd  artifact: firmware.bin 1343936B ...
                deployed: never
```

or

```
RC1 [released]  commit: 7332ebd  artifact: <none>
                deployed: 2026-08-28T20:15Z  ref: OTA bench rotator
```

### New tool: plan_rc_deploy (mcpptool.py + tool.yaml)

```
plan_rc_deploy(release, rc_number, ref=None)
```

Sets deployed_at and deployed_ref on a released RC. `ref` is free-text; the
project gives it meaning. Never blocks on absence.

### New: backfill_rc_sha (context.py)

```python
def backfill_rc_sha(conn, release_name, rc_number, project_id, commit_sha) -> dict:
```

- Repair tool: sets `commit_sha` on a released RC where it is currently NULL.
- Raises `ValueError` if `commit_sha` is already set (prevents silent overwrite
  of the only factual field on the RC).
- No state restriction beyond "must exist" — backfill is for RCs released before
  patch-21 and cannot wait for a state change.

New tool: `plan_rc_backfill_sha(release, rc_number, commit_sha)` in mcpptool.py + tool.yaml.

## Files changing

- `schema_patches/patch-21.sql` (new, requires `git add -f`)
- `db.py` — `LATEST_SCHEMA_VERSION = 21`
- `context.py` — `release_rc`, `get_release`, new `deploy_rc`, new `backfill_rc_sha`
- `mcpptool.py` — `_cmd_rc_release` updated, new `_cmd_rc_deploy`, new `_cmd_rc_backfill_sha`
- `tool.yaml` — update `plan_rc_release` params, add `plan_rc_deploy`, add `plan_rc_backfill_sha`
