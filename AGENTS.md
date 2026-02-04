# 🛑 STOP! READ THIS FIRST
**You are in a DB-backed stateful project (V2).** You do NOT know the active context yet.
**ACTION REQUIRED:** Run `agent context` IMMEDIATELY to orient yourself.

# AGENTS.md - Operational Directives (V2)

### B. Interaction Triggers
If the user asks "context ?" or "agent context ?", run `agent context`.
If the user says "context <name>", run `agent context <name>`.

### C. Script Permissions
If you encounter permission issues when running `agent`, inform the user immediately. Do NOT attempt to bypass security or modify system permissions without explicit user approval.

## 1. THE CONTEXT RULE (Primary Directive)
**Work happens via the DB, not folders.**

### A. The State Protocol (Handover)
Agents DO NOT share memory. Use the `agent` CLI to manage state.

1. **Global Entry:** Run `agent context` to see the active context and task.
2. **Context Switching:** Run `agent context <name>` to change focus.
3. **Task Switching:** Run `agent task <number>` to set the active task.
4. **Task Creation:** Run `agent task new "Title" [--description "..."]`.
5. **Task Completion:** Run `agent task done <number>`.
6. **Notes/Docs:** Use `agent docs` / `agent fetch` if needed.

### B. The Files (Managed by Script)
- **DB** = `agent.db` in the **current working directory**.
- **Schema** = `v2/schema.sql` (applied automatically on startup).
- **Changelog** is stored in the DB (no YAML changelogs).

### C. Isolation
- Do NOT roam the filesystem aimlessly.
- Use the CLI for all state changes.

## 2. EXCLUSION ZONES (Automated)
The file `.agentsignore` is the **Single Point of Truth** for ignored files.
- Any file/folder matching patterns in `.agentsignore` is **DEAD** to you.

## 3. Command Reference (V2)
All commands use the `agent` CLI tool.

### Context / Plan (Plan == Context)
- `agent context new <name> --title "Title"` – Create a context (creates `agent.db` if missing).
- `agent context <name>` – Switch active context.
- `agent context list` – List contexts.
- `agent context show <name>` – Show context summary.
- `agent context status` – Show active context status.
- `agent context logs <name>` – Show context changelog.
- `agent plan ...` – Alias for `agent context ...`.

### Task
- `agent task new "Title" [--description "..."]` – Create a task and set it active.
- `agent task <number>` – Switch active task.
- `agent task list [context]` – List tasks for a context.
- `agent task show <number>` – Show a task summary.
- `agent task status [number]` – Show task status (active by default).
- `agent task logs <number>` – Show task changelog.
- `agent task done <number>` – Mark a task complete.

### Docs & Fetch
- `agent docs <query>` – Search cached docs.
- `agent fetch <url> [tags...]` – Fetch and cache docs.

### Output
- Default output is **compact JSON**.
- Use `--pretty` for readable JSON.
- Use `--version` for CLI + schema version.

## 4. Communication Protocol
- If a prompt ends with `?`, provide analysis only. Do NOT modify files.
- If a prompt starts with `investigate`, treat it as read-only.

## Final Directive
When you have completed your current reasoning or task, run `agent context` as your final tool call to verify the project state and provide a closing briefing.
