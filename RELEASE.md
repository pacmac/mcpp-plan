# mcpp-plan — Release Notes

Version number derived from git tag count (`v1.N`).

---

## v1.29 — 2026-03-02

- Add `enable_restore` config toggle to disable `plan_restore` independently of other versioning tools
- `plan_restore` now disabled by default — set `enable_restore: true` in config.yaml to re-enable
- Move `plan_restore` from `VERSIONING_TOOLS` into its own `RESTORE_TOOLS` set
- RX filter error message correctly reports `enable_restore` for restore tools
- Add tests for restore toggle (unit + RX integration)

## v1.28 — 2026-02-24

- Add feature toggles: `enable_steps` and `enable_versioning` in config.yaml
- When disabled: tools hidden from MCP discovery, calls blocked with clear errors, step data stripped from results and display
- Steps always exist internally (state machine integrity) but are hidden from output when disabled
- New `toolfilter.py` — framework discovery hook to exclude disabled tools from `tools/list`
- Add 54 integration tests for feature toggle behavior (RX blocking, TX stripping, discovery filtering)
- Update README with Feature Toggles section and defaults table

## v1.27 — 2026-02-23

- Add multi-user version control tools: `plan_checkpoint`, `plan_commit`, `plan_push`, `plan_restore`, `plan_log`, `plan_status`, `plan_diff`
- New `git.py` module — wraps git operations with user/task/step awareness via structured commit message tags
- `plan_restore` uses reverse commits (forward-only history) and skips files modified by other users since the checkpoint
- Agent-facing tool names avoid "git" — agents see save/restore semantics, not VCS internals
- Add `test_git.py` with 36 tests covering tag parsing, multi-user restore, push, and edge cases

## v1.26 — 2026-02-22

- Add `plan_step_reorder` tool — reassign step order with a single call
- Stable agent-facing step numbers via `sub_index` — internal IDs never exposed
- Fix bulk step creation (`plan_task_new` with steps) not assigning step numbers
- Add step reorder unit and integration tests
- Update README with `plan_step_reorder` in tool table
- Add RELEASE.md

## v1.25 — 2026-02-22

- Add RAPIDSTART.md quickstart guide

## v1.24 — 2026-02-21

- Add `plan_task_adopt` for cross-user task deep-copy (copies steps, notes, step notes)

## v1.23 — 2026-02-21

- Replace append-only notes with upsert and delete
- Goal/plan notes upsert by kind; regular notes support update by ID or create new

## v1.22 — 2026-02-20

- Add `plan_task_report` tool
- Enable reopening completed tasks (config-gated via `allow_reopen_completed`)

## v1.21 — 2026-02-20

- Add daily auto-backup with configurable retention pruning

## v1.20 — 2026-02-20

- Rewrite destructive patch-7 for safety, update tests and docs

## v1.19 — 2026-02-20

- Add migration safety pipeline: verified backup, trial-on-copy, row count validation

## v1.18 — 2026-02-19

- Add `plan_project_report` and `plan_task_report` markdown report generation tools

## v1.17 — 2026-02-19

- Add auto-backup of plan.db before schema migrations

## v1.16 — 2026-02-19

- Add `.backups/` to .gitignore

## v1.15 — 2026-02-19

- Fix config import paths
- Add MCP integration test suite

## v1.14 — 2026-02-18

- Rename "archived" status to "completed"
- Add config-gated task reopening

## v1.13 — 2026-02-18

- Add note kinds: `goal` (what), `plan` (how), `note` (freeform)
- Add global `config.yaml` with `plan_config_show` and `plan_config_set` tools
- Add workflow enforcement: require goal and plan notes before step progress

## v1.12 — 2026-02-17

- Add agent-portability note to README

## v1.11 — 2026-02-17

- Add dogfooding note to README

## v1.10 — 2026-02-17

- Add GitHub link to Inspired By section

## v1.9 — 2026-02-17

- Fix Inspired By: correct video description

## v1.8 — 2026-02-17

- Fix Inspired By: correct name to Andreas Spiess

## v1.7 — 2026-02-17

- Add Inspired By section crediting Andreas Spiess

## v1.6 — 2026-02-16

- Fix wrong DB path in README, remove DB location from get_info

## v1.5 — 2026-02-16

- Show task IDs in list display for easy reference

## v1.4 — 2026-02-16

- Fix DB path: use module directory, not user home

## v1.3 — 2026-02-16

- Fix case-sensitive user lookup creating duplicate users

## v1.2 — 2026-02-15

- Add Hints & Tips section to README

## v1.1 — 2026-02-15

- Initial release
- Task and step management with full lifecycle (planned → started → complete)
- Multi-user support with auto-detected OS user
- Multi-project support with project-scoped databases
- Task notes and project metadata
- Centralized SQLite database
- MCP tool interface with `plan_` prefix (20 tools)
- README, license (PolyForm Noncommercial 1.0.0)
