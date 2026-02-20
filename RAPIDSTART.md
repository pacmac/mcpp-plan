# Rapid Start

Get up and running with Claude Code in under 10 minutes.

## Prerequisites

- Python 3.10+ with `pyyaml` (`pip install pyyaml`)
- Claude Code CLI installed

## 1. Clone (2 min)

Clone both repos as siblings into your chosen folder:

```bash
cd ~/projects
git clone git@github.com:pacmac/mcpp.git
git clone git@github.com:pacmac/mcpp-plan.git
```

mcpp's default `tools.yaml` already includes `../mcpp-plan`, so no configuration needed if they're side by side.

## 2. Register with Claude Code (1 min)

```bash
claude mcp add mympc --scope user \
  --env MYMPC_LOG_LEVEL=error \
  --env MYMPC_TIMEOUT_SECONDS=30 \
  -- python3 ~/projects/mcpp/wrapper.py
```

Replace `~/projects` with your install folder.

## 3. Verify (1 min)

Open Claude Code in any project and ask:

```
What mcpp tools do you have?
```

You should see the `plan_*` tools listed.

## 4. Start using it

### Set up your project

```
Discover what this project is about and add what you learn to the project notes.
```

The agent reads your docs and code, then stores a summary that persists across sessions.

### Create a task

```
Create a task called "my-first-task" with steps: review codebase, identify issues, fix top priority bug
```

### Work through it

```
What am I working on?
Mark step 1 as done
Switch to step 2
Add a note: found three issues in the auth module
Show me all my tasks
```

## Quick reference

| You say | What happens |
|---------|--------------|
| "Create a task called X with steps: A, B, C" | New task with steps |
| "What am I working on?" | Shows active task and step |
| "Mark this step as done" | Completes current step |
| "Switch to step 3" | Jumps to step 3 |
| "Add a note: ..." | Adds a freeform note |
| "Show me all my tasks" | Lists all tasks |
| "Switch to the X task" | Changes active task |

## Troubleshooting

**"No tools found"** — Restart Claude Code. MCP servers load at startup.

**"Module not found"** — Check that `mcpp` and `mcpp-plan` are sibling directories.

**"pyyaml not installed"** — `pip install pyyaml`
