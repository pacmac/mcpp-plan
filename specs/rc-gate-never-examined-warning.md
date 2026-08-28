# rc-gate-never-examined-warning

## Gap

An RC area with zero tasks ever (open=0, complete=0) passes the gate silently.
"Nobody has ever filed a task here" and "the work is done" are indistinguishable.
The unfiled-task warning does not catch this — it counts tasks that exist but are unfiled;
these areas have nothing written down at all.

## Fix

In `check_rc_exit_criteria` (context.py), after the open-task loop: for each scoped
area, count total tasks (any status). If 0, append to `warnings`:

  "area {name!r} is scoped but never examined (0 tasks ever)"

Non-blocking: warning only, not a hard blocker. Warning at release time, not at scope
time — scoping before tasks are filed is legitimate planning.

## Files changing

- `context.py` — `check_rc_exit_criteria` only
