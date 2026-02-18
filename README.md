# mcpp-plan

A persistent task and step tracker for AI coding agents. Gives Claude Code (or any MCP-compatible agent) the ability to break work into tasks, track steps within each task, and remember exactly where it left off across sessions.

> **Dogfooded daily.** This module is developed, maintained, and continuously improved using itself. Every feature gets real-world testing the moment it's built.
>
> **Agent-portable.** Start a task in one agent, pick it up in another — no context lost. The state lives in the database, not the conversation.

## Why

AI agents lose context between sessions. When you resume a conversation, the agent doesn't know what it was doing, which steps are done, or what's next. mcpp-plan solves this by giving agents a structured, persistent task manager backed by SQLite.

The agent talks to it through MCP tools. You talk to the agent in plain English. The agent manages the rest.

## How it works

```
project
  └── user (auto-detected from $USER)
        └── task (a focus area, like "build login page")
              └── step (individual action, like "create user table")
```

- **Tasks** are top-level work items (features, bugs, refactors)
- **Steps** are ordered actions within a task
- **One task and one step are active at a time** -- the agent always knows what to do next
- **State persists** in `plan.db` within the module directory
- **Multi-user** -- each OS user gets independent task cursors within a shared database

## Installation

mcpp-plan is an [mcpp](https://github.com/pacmac/mcpp) tool module. Install it by adding the tool path to your mcpp configuration.

### Prerequisites

- Python 3.10+
- SQLite 3 (bundled with Python)
- An MCP-compatible agent (Claude Code, etc.)

### Setup

1. Clone or copy this directory into your mcpp tools path:

```bash
git clone <repo-url> /path/to/mcpp-plan
```

2. Register it with mcpp by adding the tool path to your configuration. The `tool.yaml` in this directory declares all available MCP tools.

3. The database is created automatically as `plan.db` in the module directory on first use. No setup required.

## Tools

All tools are exposed via MCP with the `plan_` prefix.

### Task tools

| Tool | Description |
|------|-------------|
| `plan_task_new` | Create a task with initial steps |
| `plan_task_list` | List tasks (yours by default, `show_all` for everyone) |
| `plan_task_show` | Show a task and its steps |
| `plan_task_status` | Show active task and progress |
| `plan_task_switch` | Switch to a different task |
| `plan_task_complete` | Mark a task as completed |
| `plan_task_notes_set` | Set a note on a task (upsert: goal/plan replace by kind, note updates by ID or creates new) |
| `plan_task_notes_get` | View notes on a task (returns notes with IDs) |
| `plan_task_notes_delete` | Delete a note from a task by ID |

### Step tools

| Tool | Description |
|------|-------------|
| `plan_step_list` | List steps in a task |
| `plan_step_show` | Show step details |
| `plan_step_switch` | Switch to a specific step |
| `plan_step_done` | Mark a step as complete |
| `plan_step_new` | Add a step to a task |
| `plan_step_delete` | Soft-delete a step |
| `plan_step_notes_set` | Set a note on a step (upsert: updates by ID or creates new) |
| `plan_step_notes_get` | View notes on a step (returns notes with IDs) |
| `plan_step_notes_delete` | Delete a note from a step by ID |

### User tools

| Tool | Description |
|------|-------------|
| `plan_user_show` | Show current user info |
| `plan_user_set` | Set your display name |

### Project tools

| Tool | Description |
|------|-------------|
| `plan_project_show` | Show project metadata |
| `plan_project_set` | Set project name and description |

### Report tools

| Tool | Description |
|------|-------------|
| `plan_project_report` | Generate a project report (.md) with all tasks, goals, plans, and steps |
| `plan_task_report` | Generate a task report (.md) with goal, plan, steps, and notes |

Reports are written to the workspace directory with date-stamped filenames (e.g. `project_report_260215.md`, `task_report_build-auth_260215.md`). Same-day files are overwritten.

### Config tools

| Tool | Description |
|------|-------------|
| `plan_config_show` | Show current configuration (merged defaults + overrides) |
| `plan_config_set` | Set a configuration value (`section`, `key`, `value`) |

### Utility

| Tool | Description |
|------|-------------|
| `plan_readme` | Display the user-facing README |

## Usage

You interact with plan through your agent in natural language. Examples:

```
"Create a task called build-auth with steps: design schema, implement JWT, add middleware, write tests"

"What am I working on?"

"Mark step 1 as done"

"Switch to step 2"

"Add a note: decided to use refresh tokens"

"Show me all my tasks"

"Switch to the fix-search task"
```

The agent translates these into MCP tool calls automatically.

## Step lifecycle

```
planned  →  started  →  complete
```

Only one step can be `started` at a time within a task. When you switch steps, the new one becomes `started`. Completing a step marks it `complete`.

## Note kinds

Notes have a `kind` field that classifies their purpose:

| Kind | Purpose | When to use |
|------|---------|-------------|
| `goal` | **What** needs to be achieved | Before starting work -- defines the objective |
| `plan` | **How** it will be done | Before starting work -- defines the approach |
| `note` | Observations and updates | During execution -- freeform (default) |

### Setting notes

Use `_set` tools to create or update notes. For goal/plan kinds, the note is upserted by kind (only one goal and one plan per task). For regular notes, pass an `id` to update or omit to create new:

```
plan_task_notes_set  text="Implement user authentication"  kind="goal"
plan_task_notes_set  text="Use JWT with refresh tokens"    kind="plan"
plan_task_notes_set  text="Decided to skip OAuth for now"
```

Setting goal or plan again replaces the existing one — no duplicates.

### Reading notes

Use `_get` tools to view notes. Notes are returned with IDs so you can update or delete them:

```
plan_task_notes_get                  # all notes
plan_task_notes_get  kind="goal"     # only goal notes
```

### Updating and deleting notes

Pass the note `id` (returned by `_get`, `_set`, `show`, and `switch`) to update or delete:

```
plan_task_notes_set     text="Revised note"  id=42    # update note 42
plan_task_notes_delete  id=42                          # delete note 42
```

### Workflow enforcement

By default, tasks require at least one `goal` and one `plan` note before steps can be switched or completed. This ensures every task has a clear objective and approach before implementation begins. Disable this in `config.yaml`:

```yaml
workflow:
  require_goal_and_plan: false
```

### Display

`plan_task_show` and `plan_task_switch` display goal and plan notes inline and return all notes with IDs, so the purpose and approach are always visible and notes can be updated in a single follow-up call. `plan_step_show` and `plan_step_switch` similarly include step notes with IDs.

### Migrated tasks

Tasks that existed before note kinds were introduced have migration placeholder notes (`"(migrated — no goal defined)"`). These are not displayed in `plan_task_show` and do not satisfy workflow enforcement. Replace them by adding real goal and plan notes to those tasks.

## Database

All state lives in a single SQLite database at `plan.db` in the module directory, shared across all projects. Each project is identified by its absolute filesystem path.

### Schema

Core tables:

- **`project`** -- workspace metadata (name, path, description)
- **`users`** -- OS users with optional display names
- **`contexts`** -- tasks (name, status, owner, project)
- **`tasks`** -- steps within a task (title, status, ordering)
- **`context_state`** -- active step cursor per task
- **`user_state`** -- active task cursor per user per project
- **`context_notes`** / **`task_notes`** -- typed notes (`goal`, `plan`, `note`)
- **`changelog`** -- audit log of all state changes

Schema migrations are applied automatically via numbered patches in `schema_patches/`.

## Configuration

Global settings live in `config.yaml` in the module directory (alongside `plan.db`). The file is optional — all keys have sensible defaults. Settings are organized by section.

```yaml
workflow:
  require_goal_and_plan: true      # require goal and plan notes before step progress
  allow_reopen_completed: false    # allow switching to completed tasks (reopens them)
  daily_backup: true               # create one backup per day on first use
  backup_retain_days: 7            # delete backups older than this many days
```

### Defaults

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `workflow` | `require_goal_and_plan` | `true` | Require goal and plan notes before step progress |
| `workflow` | `allow_reopen_completed` | `false` | Allow switching to completed tasks (sets them back to active) |
| `workflow` | `daily_backup` | `true` | Create one backup per day on first use |
| `workflow` | `backup_retain_days` | `7` | Delete backups older than this many days |

### Behavior

- Missing file = all defaults
- Missing keys = defaults for those keys
- Unknown keys are preserved in the file but ignored by the system
- Invalid YAML falls back to all defaults

### Tools

- `plan_config_show` -- show current settings (merged defaults + overrides)
- `plan_config_set` -- set a value: requires `section`, `key`, and `value` parameters

## Migration safety

Schema migrations are protected by a multi-layer safety pipeline (`backup.py`):

1. **Verified backup** -- `plan.db` is copied to `.backups/plan.db.YYMMDDx` and the SHA-256 checksum is verified to match the live DB before proceeding.
2. **Trial migration on a copy** -- all patches are applied to a temporary copy of the database first. If the trial fails (SQL error or data loss), the live DB is never touched.
3. **Row count validation** -- after the trial, every table's row count is compared to pre-migration counts. Any decrease aborts the migration.
4. **Live migration + re-validation** -- only after the trial passes are patches applied to the live DB, followed by a second row count validation.

If anything fails at any step, the migration aborts with a clear error message and the path to the backup file. The live database is left untouched.

Backups use letter suffixes (`a`-`z`) for multiple backups on the same day. Migration backups are created when patches are applied. Additionally, a daily auto-backup runs on first use each day (configurable via `daily_backup`), with automatic pruning of backups older than `backup_retain_days`.

## Hints & Tips

**Orient the agent on a new project.** When starting work on a fresh codebase, have the agent explore it first:

```
> Discover what this project is about, including its structure,
> and add what you learn to the project notes.
```

This lets the agent build its own understanding of the codebase -- what's where, how things connect, what conventions are used -- and persist that context for future sessions.

**Capture ideas without losing focus.** If you spot an unrelated issue or think of something while working on a task, tell the agent to note it and carry on:

```
> Add a task: "refactor the cache expiry logic" -- then continue
> what you were doing.
```

This keeps your current flow intact while making sure the thought doesn't get lost.

**Checkpoint before big changes.** Before a refactor or risky edit, ask for a commit so you have a rollback point:

```
> Commit what we have before refactoring.
```

**Review before you push.** After multi-file edits, ask the agent to summarise what changed:

```
> Show me what you changed and why.
```

**Let the agent plan first.** For complex tasks, have it think before writing code:

```
> Plan how you'd approach this before writing code.
```

**Use help for discovery.** Agents can call the built-in `help` tool to see what's available — no need to remember tool names:

```
> What mcpp tools do you have?
```

## Architecture

```
tool.yaml          MCP tool definitions (schema for all plan_* tools)
mcpptool.py        MCP entry point -- routes tool calls to Python API
context.py         Business logic (create/switch/complete tasks and steps)
config.py          Global configuration (config.yaml loading + defaults)
db.py              SQLite connection, schema management, user/project helpers
backup.py          Migration safety pipeline (verified backup, trial-on-copy, row validation)
schema.sql         Base schema
schema_patches/    Incremental migrations (patch-4.sql through patch-10.sql)
```

### Entry points

- **`execute(tool_name, arguments, context)`** -- called by the MCP host for every tool invocation
- **`get_info(context)`** -- returns tool metadata and existing task names for autocomplete

### How a tool call flows

1. MCP host calls `execute("plan_step_done", {"number": 3}, {"workspace_dir": "/my/project"})`
2. `mcpptool.py` routes to `_cmd_step_done`
3. Handler builds a command list and calls `_run_plan_cmd`
4. `_run_plan_cmd` dynamically imports `db.py` and `context.py`, opens the central DB, and dispatches
5. `context.py` runs the operation in a transaction
6. Result dict is returned with structured data and a `display` string for the user

## Inspired By

This project was inspired by [Andreas Spiess](https://www.youtube.com/@AndreasSpiess) ([GitHub](https://github.com/SensorsIot)) and his [video on AI-assisted coding](https://www.youtube.com/watch?v=5DG0-_lseR4).

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)

Free for personal use, research, education, non-profits, and government. Not permitted for commercial use. See [LICENSE](LICENSE) for the full text.
