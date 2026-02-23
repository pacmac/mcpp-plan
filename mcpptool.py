"""
Plan: Task & Step Manager (MCP Tool Wrapper)

Exposes plan task and step operations as MCP tools.
Operates on workspace-local plan.db for autonomous task tracking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_project_nudge_sent = False


# ── Display formatters ──
# These produce human-readable text for the "display" key (audience: user).

def _with_display(result: dict[str, Any], display_text: str | None) -> dict[str, Any]:
    """Attach display text to a successful tool result."""
    if result.get("success") and display_text:
        result["display"] = display_text
    return result


def _fmt_notes(notes: list[dict], label: str = "Notes") -> str:
    if not notes:
        return f"No {label.lower()}."
    lines = [f"**{label}** ({len(notes)})"]
    for n in notes:
        actor = f" — {n['actor']}" if n.get("actor") else ""
        kind = n.get("kind", "note")
        kind_tag = f"[{kind}] " if kind != "note" else ""
        note_id = f" (id:{n['id']})" if "id" in n else ""
        lines.append(f"- {kind_tag}{n['note']}{actor}{note_id}")
    return "\n".join(lines)


def _fmt_task_show(data: dict) -> str:
    name = data.get("context_name", "?")
    title = data.get("context_title", name)
    active_num = data.get("active_task_number")
    lines = [f"**{name}**: {title}"]
    if goal := data.get("goal"):
        lines.append(f"  **Goal**: {goal}")
    if plan := data.get("plan"):
        lines.append(f"  **Plan**: {plan}")
    if notes := data.get("notes"):
        lines.append(_fmt_notes(notes, "Task notes"))
    for t in data.get("tasks", []):
        num = t["task_number"]
        deleted = t.get("is_deleted")
        if deleted:
            continue
        status = t["status"]
        marker = {"planned": " ", "started": ">", "complete": "x"}.get(status, " ")
        pointer = " <--" if num == active_num else ""
        lines.append(f"  [{marker}] {num}. {t['title']}{pointer}")
    return "\n".join(lines)


def _fmt_task_status(data: dict) -> str:
    name = data.get("context_name", "?")
    title = data.get("context_title", name)
    active = data.get("active_task_number", "—")
    done = data.get("completed_count", 0) or 0
    total = (data.get("planned_count", 0) or 0) + (data.get("started_count", 0) or 0) + done
    return f"**{name}**: {title}\nStep {active} active, {done}/{total} complete"


def _fmt_task_list(tasks: list[dict], grouped: bool = False) -> str:
    if not tasks:
        return "No tasks."
    if not grouped:
        lines = ["**Tasks**"]
        for t in tasks:
            tid = t.get("id", "?")
            active = " (active)" if t.get("is_active") else ""
            status = t.get("status", "active")
            if status == "completed":
                active = " [completed]"
            lines.append(f"- [{tid}] {t['name']}: {t.get('title', t['name'])}{active}")
        return "\n".join(lines)

    # Grouped by user
    from collections import defaultdict
    by_user: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        user = t.get("user", "unknown")
        by_user[user].append(t)
    lines = ["**Tasks** (all users)"]
    for user, user_tasks in by_user.items():
        count = len(user_tasks)
        lines.append(f"\n**{user}** ({count} task{'s' if count != 1 else ''})")
        for t in user_tasks:
            tid = t.get("id", "?")
            active = " (active)" if t.get("is_active") else ""
            status = t.get("status", "active")
            if status == "completed":
                active = " [completed]"
            lines.append(f"- [{tid}] {t['name']}: {t.get('title', t['name'])}{active}")
    return "\n".join(lines)


def _fmt_step_list(data: dict) -> str:
    name = data.get("context_name", "?")
    active_num = data.get("active_task_number")
    lines = [f"**{name}** — steps"]
    for t in data.get("tasks", []):
        num = t["task_number"]
        if t.get("is_deleted"):
            continue
        status = t["status"]
        marker = {"planned": " ", "started": ">", "complete": "x"}.get(status, " ")
        pointer = " <--" if num == active_num else ""
        lines.append(f"  [{marker}] {num}. {t['title']}{pointer}")
    return "\n".join(lines)


def _fmt_step_show(data: dict) -> str:
    num = data.get("sub_index") or data.get("task_number", "?")
    title = data.get("title", "?")
    status = data.get("status", "?")
    desc = data.get("description_md")
    line = f"**Step {num}**: {title} [{status}]"
    if desc:
        line += f"\n{desc}"
    if notes := data.get("notes"):
        line += "\n" + _fmt_notes(notes, "Step notes")
    return line


def get_info(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return tool configuration and available tasks."""
    workspace_dir = (context or {}).get("workspace_dir")
    existing_tasks: list[str] = []

    if workspace_dir:
        try:
            result = _run_plan_cmd(workspace_dir, ["task", "list", "--json"])
            if result.get("success"):
                data = result.get("result", {})
                tasks = data.get("tasks", [])
                existing_tasks = [t.get("name") for t in tasks if t.get("name")]
        except Exception:
            pass

    return {
        "params": {
            "name": {"values": existing_tasks, "default": None},
            "number": {"values": None, "default": None}
        },
        "existing_tasks": existing_tasks,
        "tip": "Ask 'what am I working on?' to see current state"
    }


def _pkg_path() -> Path:
    """Resolve path to the package directory (this module's own directory)."""
    return Path(__file__).resolve().parent


def _load_pkg(pkg_path: Path):
    """Import plan db and context modules. Returns (db_mod, ctx_mod)."""
    import importlib.util

    pkg_spec = importlib.util.spec_from_file_location(
        "mcpp_plan", pkg_path / "__init__.py",
        submodule_search_locations=[str(pkg_path)]
    )
    pkg_module = importlib.util.module_from_spec(pkg_spec)
    sys.modules["mcpp_plan"] = pkg_module
    if pkg_spec.loader:
        pkg_spec.loader.exec_module(pkg_module)

    db_spec = importlib.util.spec_from_file_location("mcpp_plan.db", pkg_path / "db.py")
    plan_db_mod = importlib.util.module_from_spec(db_spec)
    sys.modules["mcpp_plan.db"] = plan_db_mod
    if db_spec.loader:
        db_spec.loader.exec_module(plan_db_mod)

    config_spec = importlib.util.spec_from_file_location("mcpp_plan.config", pkg_path / "config.py")
    config_mod = importlib.util.module_from_spec(config_spec)
    sys.modules["mcpp_plan.config"] = config_mod
    if config_spec.loader:
        config_spec.loader.exec_module(config_mod)

    context_spec = importlib.util.spec_from_file_location("mcpp_plan.context", pkg_path / "context.py")
    plan_ctx = importlib.util.module_from_spec(context_spec)
    sys.modules["mcpp_plan.context"] = plan_ctx
    if context_spec.loader:
        context_spec.loader.exec_module(plan_ctx)

    return plan_db_mod, plan_ctx


def _open_db(plan_db_mod, plan_ctx, workspace_dir: Path):
    """Connect to central DB, ensure schema, resolve project and user.

    Returns (conn, project_dict, is_new_project, user_id, project_id).
    """
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    project, is_new = plan_ctx.ensure_project(conn, str(workspace_dir))
    user_id = plan_db_mod.get_or_create_user(conn, plan_db_mod.get_os_user())
    project_id = project["id"]
    return conn, project, is_new, user_id, project_id


def _run_plan_cmd(workspace_dir: str | Path, cmd_args: list[str]) -> dict[str, Any]:
    """
    Execute a plan command using the Python API directly.

    Args:
        workspace_dir: Working directory for plan.db
        cmd_args: Command arguments (e.g., ["task", "list"])

    Returns:
        Dict with success/error and data
    """
    # Clean up stale module cache from previous naming (v2.*)
    for stale in [k for k in sys.modules if k == "v2" or k.startswith("v2.")]:
        del sys.modules[stale]
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]

    workspace_dir = Path(workspace_dir)

    pkg_path = _pkg_path()

    try:
        plan_db_mod, plan_ctx = _load_pkg(pkg_path)

        # Route commands
        command = cmd_args[0]
        action = cmd_args[1] if len(cmd_args) > 1 else ""

        try:
            if command == "task":
                if action == "new":
                    name = cmd_args[2] if len(cmd_args) > 2 else None
                    if not name:
                        return {"success": False, "error": "task name required"}

                    conn, _project, _is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)

                    # Parse kwargs from flattened args
                    title = None
                    steps_list = []
                    i = 3
                    while i < len(cmd_args):
                        if cmd_args[i] == "--title" and i + 1 < len(cmd_args):
                            title = cmd_args[i + 1]
                            i += 2
                        elif cmd_args[i] == "--step" and i + 1 < len(cmd_args):
                            steps_list.append(plan_ctx.StepInput(title=cmd_args[i + 1]))
                            i += 2
                        else:
                            i += 1

                    if not steps_list:
                        steps_list = [plan_ctx.StepInput(title="New step")]

                    task_id = plan_ctx.create_task(
                        conn,
                        name=name,
                        description_md=title,
                        steps=steps_list,
                        set_active=True,
                        user_id=_user_id,
                        project_id=_project_id,
                    )
                    result = plan_ctx.get_task_show(conn, task_id, project_id=_project_id)
                    conn.close()
                    return {"success": True, "result": result}

                elif action == "list":
                    conn, _project, _is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)
                    status_filter = None
                    show_all_users = False
                    i = 2
                    while i < len(cmd_args):
                        if cmd_args[i] == "--status" and i + 1 < len(cmd_args):
                            status_filter = cmd_args[i + 1]
                            i += 2
                        elif cmd_args[i] == "--all":
                            show_all_users = True
                            i += 1
                        else:
                            i += 1
                    tasks = plan_ctx.list_tasks(
                        conn, status_filter=status_filter,
                        user_id=_user_id, show_all_users=show_all_users,
                        project_id=_project_id,
                    )
                    conn.close()
                    return {"success": True, "result": {"tasks": tasks}}

                else:
                    conn, _project, _is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)

                    if action == "complete":
                        name = cmd_args[2] if len(cmd_args) > 2 else None
                        if not name:
                            conn.close()
                            return {"success": False, "error": "task name required"}
                        plan_ctx.complete_task_context(conn, name, user_id=_user_id, project_id=_project_id)
                        tasks = plan_ctx.list_tasks(conn, status_filter="active", user_id=_user_id, project_id=_project_id)
                        conn.close()
                        return {"success": True, "result": {"completed": name, "tasks": tasks}}

                    elif action == "switch":
                        name = cmd_args[2] if len(cmd_args) > 2 else None
                        if not name:
                            conn.close()
                            return {"success": False, "error": "task name required"}
                        plan_ctx.switch_task(conn, name, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.get_task_status(conn, user_id=_user_id, project_id=_project_id)
                        conn.close()
                        return {"success": True, "result": result}

                    elif action == "show":
                        name = cmd_args[2] if len(cmd_args) > 2 and not cmd_args[2].startswith("--") else None
                        if name:
                            task_id = plan_ctx.resolve_task_id(conn, name, project_id=_project_id)
                        else:
                            task_id = plan_ctx.resolve_active_task_id(conn, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.get_task_show(conn, task_id, project_id=_project_id)
                        conn.close()
                        return {"success": True, "result": result}

                    elif action == "status":
                        result = plan_ctx.get_task_status(conn, user_id=_user_id, project_id=_project_id)
                        conn.close()
                        return {"success": True, "result": result}

                    elif action == "notes":
                        name = None
                        text = None
                        kind = None
                        note_id = None
                        delete_id = None
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--name" and i + 1 < len(cmd_args):
                                name = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--kind" and i + 1 < len(cmd_args):
                                kind = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--id" and i + 1 < len(cmd_args):
                                note_id = int(cmd_args[i + 1])
                                i += 2
                            elif cmd_args[i] == "--delete" and i + 1 < len(cmd_args):
                                delete_id = int(cmd_args[i + 1])
                                i += 2
                            elif not cmd_args[i].startswith("--"):
                                text = cmd_args[i]
                                i += 1
                            else:
                                i += 1

                        if delete_id is not None:
                            plan_ctx.delete_context_note(conn, delete_id)
                            notes = plan_ctx.list_context_notes(conn, context_ref=name, user_id=_user_id, project_id=_project_id)
                            conn.close()
                            return {"success": True, "result": {"notes": notes}}
                        elif text:
                            plan_ctx.add_context_note(conn, text, context_ref=name, user_id=_user_id, project_id=_project_id, kind=kind or "note", note_id=note_id)
                            notes = plan_ctx.list_context_notes(conn, context_ref=name, user_id=_user_id, project_id=_project_id)
                            conn.close()
                            return {"success": True, "result": {"notes": notes}}
                        else:
                            notes = plan_ctx.list_context_notes(conn, context_ref=name, user_id=_user_id, project_id=_project_id, kind=kind)
                            conn.close()
                            return {"success": True, "result": {"notes": notes}}

                    conn.close()

            elif command == "step":
                conn, _project, _is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)

                try:
                    if action == "list":
                        task_ref = None
                        if len(cmd_args) > 2 and not cmd_args[2].startswith("--"):
                            task_ref = cmd_args[2]
                        result = plan_ctx.list_steps(conn, context_ref=task_ref, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "switch":
                        number = int(cmd_args[2]) if len(cmd_args) > 2 else None
                        if number is None:
                            return {"success": False, "error": "step number required"}
                        plan_ctx.switch_step(conn, number, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.get_step_summary(conn, step_number=number, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "show":
                        number = None
                        if len(cmd_args) > 2 and not cmd_args[2].startswith("--"):
                            number = int(cmd_args[2])
                        result = plan_ctx.get_step_summary(conn, step_number=number, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "done":
                        number = int(cmd_args[2]) if len(cmd_args) > 2 else None
                        if number is None:
                            return {"success": False, "error": "step number required"}
                        plan_ctx.complete_step(conn, number, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.get_step_summary(conn, step_number=number, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "new":
                        title = cmd_args[2] if len(cmd_args) > 2 else None
                        if not title:
                            return {"success": False, "error": "step title required"}
                        task_ref = None
                        description_md = None
                        i = 3
                        while i < len(cmd_args):
                            if cmd_args[i] == "--task" and i + 1 < len(cmd_args):
                                task_ref = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--description" and i + 1 < len(cmd_args):
                                description_md = cmd_args[i + 1]
                                i += 2
                            else:
                                i += 1
                        step_id, step_number = plan_ctx.create_step(
                            conn, task_ref, title, description_md=description_md, user_id=_user_id, project_id=_project_id
                        )
                        result = plan_ctx.get_step_summary(conn, step_number=step_number, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "delete":
                        number = int(cmd_args[2]) if len(cmd_args) > 2 else None
                        if number is None:
                            return {"success": False, "error": "step number required"}
                        task_ref = None
                        i = 3
                        while i < len(cmd_args):
                            if cmd_args[i] == "--task" and i + 1 < len(cmd_args):
                                task_ref = cmd_args[i + 1]
                                i += 2
                            else:
                                i += 1
                        plan_ctx.delete_step(conn, number, task_ref=task_ref, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.list_steps(conn, user_id=_user_id, project_id=_project_id)
                        return {"success": True, "result": result}

                    elif action == "reorder":
                        # Parse order from --order flag or remaining positional args
                        order = []
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--order" and i + 1 < len(cmd_args):
                                # Accept comma-separated or JSON list
                                raw = cmd_args[i + 1]
                                order = [int(x.strip()) for x in raw.strip("[]").split(",")]
                                i += 2
                            else:
                                try:
                                    order.append(int(cmd_args[i]))
                                except ValueError:
                                    pass
                                i += 1
                        if not order:
                            return {"success": False, "error": "order is required (list of step numbers in desired order)"}
                        mapping = plan_ctx.reorder_steps(conn, order, user_id=_user_id, project_id=_project_id)
                        result = plan_ctx.list_steps(conn, user_id=_user_id, project_id=_project_id)
                        result["mapping"] = mapping
                        return {"success": True, "result": result}

                    elif action == "notes":
                        number = None
                        text = None
                        kind = None
                        note_id = None
                        delete_id = None
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--step-number" and i + 1 < len(cmd_args):
                                number = int(cmd_args[i + 1])
                                i += 2
                            elif cmd_args[i] == "--kind" and i + 1 < len(cmd_args):
                                kind = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--id" and i + 1 < len(cmd_args):
                                note_id = int(cmd_args[i + 1])
                                i += 2
                            elif cmd_args[i] == "--delete" and i + 1 < len(cmd_args):
                                delete_id = int(cmd_args[i + 1])
                                i += 2
                            elif not cmd_args[i].startswith("--"):
                                text = cmd_args[i]
                                i += 1
                            else:
                                i += 1

                        if delete_id is not None:
                            plan_ctx.delete_step_note(conn, delete_id)
                            notes = plan_ctx.list_step_notes(conn, step_number=number, user_id=_user_id, project_id=_project_id)
                            return {"success": True, "result": {"notes": notes}}
                        elif text:
                            plan_ctx.add_step_note(conn, text, step_number=number, user_id=_user_id, project_id=_project_id, kind=kind or "note", note_id=note_id)
                            notes = plan_ctx.list_step_notes(conn, step_number=number, user_id=_user_id, project_id=_project_id)
                            return {"success": True, "result": {"notes": notes}}
                        else:
                            notes = plan_ctx.list_step_notes(conn, step_number=number, user_id=_user_id, project_id=_project_id, kind=kind)
                            return {"success": True, "result": {"notes": notes}}
                finally:
                    conn.close()

            elif command == "project":
                conn, project, is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)
                try:
                    if action == "show":
                        return {"success": True, "result": project or {}}

                    elif action == "set":
                        name = None
                        description = None
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--name" and i + 1 < len(cmd_args):
                                name = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--description" and i + 1 < len(cmd_args):
                                description = cmd_args[i + 1]
                                i += 2
                            else:
                                i += 1
                        result = plan_ctx.set_project(conn, project_id=_project_id, project_name=name, description_md=description)
                        return {"success": True, "result": result}
                finally:
                    conn.close()

            return {"success": False, "error": f"Unknown command: {command} {action}"}

        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Failed to load plan module: {e}",
            "traceback": traceback.format_exc()
        }


def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a plan command via MCP tool interface."""
    workspace_dir = (context or {}).get("workspace_dir", ".")

    # Map tool names to handler functions
    tool_map = {
        # Task tools (top-level grouping)
        "plan_task_new": _cmd_task_new,
        "plan_task_list": _cmd_task_list,
        "plan_task_complete": _cmd_task_complete,
        "plan_task_switch": _cmd_task_switch,
        "plan_task_show": _cmd_task_show,
        "plan_task_status": _cmd_task_status,
        "plan_task_notes": _cmd_task_notes,  # backward compat
        "plan_task_notes_set": _cmd_task_notes_set,
        "plan_task_notes_get": _cmd_task_notes_get,
        "plan_task_notes_delete": _cmd_task_notes_delete,
        # Step tools (individual items)
        "plan_step_switch": _cmd_step_switch,
        "plan_step_show": _cmd_step_show,
        "plan_step_list": _cmd_step_list,
        "plan_step_done": _cmd_step_done,
        "plan_step_notes": _cmd_step_notes,  # backward compat
        "plan_step_notes_set": _cmd_step_notes_set,
        "plan_step_notes_get": _cmd_step_notes_get,
        "plan_step_notes_delete": _cmd_step_notes_delete,
        "plan_step_new": _cmd_step_new,
        "plan_step_delete": _cmd_step_delete,
        "plan_step_reorder": _cmd_step_reorder,
        # User tools
        "plan_user_show": _cmd_user_show,
        "plan_user_set": _cmd_user_set,
        # Project tools (workspace metadata)
        "plan_project_show": _cmd_project_show,
        "plan_project_set": _cmd_project_set,
        # Config tools
        "plan_config_show": _cmd_config_show,
        "plan_config_set": _cmd_config_set,
        # Task adoption
        "plan_task_adopt": _cmd_task_adopt,
        # Report tools
        "plan_project_report": _cmd_project_report,
        "plan_task_report": _cmd_task_report,
        # Utility
        "plan_readme": _cmd_readme,
        # Git operations
        "plan_checkpoint": _cmd_checkpoint,
        "plan_commit": _cmd_commit,
        "plan_push": _cmd_push,
        "plan_restore": _cmd_restore,
        "plan_log": _cmd_log,
        "plan_status": _cmd_status,
        "plan_diff": _cmd_diff,
    }

    handler = tool_map.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    try:
        result = handler(workspace_dir, arguments)
        if not result.get("success"):
            return result

        # Read project metadata for injection and nudge
        global _project_nudge_sent
        try:
            pkg_path = _pkg_path()
            plan_db_mod, plan_ctx = _load_pkg(pkg_path)
            conn, project, _is_new, _user_id, _proj_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
            conn.close()

            # Inject project name into all result dicts
            if project and isinstance(result.get("result"), dict):
                result["result"]["project_name"] = project.get("project_name")

            # One-time nudge if project description is missing
            if not _project_nudge_sent:
                if tool_name == "plan_project_set":
                    _project_nudge_sent = True
                elif not project.get("description_md"):
                    nudge = (
                        "\n\n---\n**Project info missing.** "
                        "Please call `plan_project_set` with a `name` and `description` "
                        "to identify this project."
                    )
                    display = result.get("display", "")
                    result["display"] = (display + nudge) if display else nudge.lstrip()
                    _project_nudge_sent = True
                else:
                    _project_nudge_sent = True
        except Exception:
            pass

        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Task command handlers (top-level grouping) ──

def _cmd_task_new(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan new task <name> --title <title> --step <step1> --step <step2>"""
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}

    cmd = ["task", "new", name, "--json"]

    if title := args.get("title"):
        cmd.extend(["--title", title])

    if steps := args.get("steps"):
        for step in (steps if isinstance(steps, list) else [steps]):
            cmd.extend(["--step", str(step)])

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_task_show(r.get("result", {})))


def _cmd_task_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan list tasks [--status <filter>] [--all] --json"""
    cmd = ["task", "list"]
    if not args.get("show_completed"):
        cmd.extend(["--status", "active"])
    if args.get("show_all"):
        cmd.append("--all")
    cmd.append("--json")
    r = _run_plan_cmd(workspace_dir, cmd)
    tasks = r.get("result", {}).get("tasks", [])
    show_all = args.get("show_all", False)
    return _with_display(r, _fmt_task_list(tasks, grouped=show_all))


def _cmd_task_complete(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan task complete <name>"""
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}
    r = _run_plan_cmd(workspace_dir, ["task", "complete", name])
    return _with_display(r, f"Completed task **{name}**.")


def _cmd_task_switch(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan switch task <name> --json"""
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}

    r = _run_plan_cmd(workspace_dir, ["task", "switch", name, "--json"])
    return _with_display(r, _fmt_task_status(r.get("result", {})))


def _cmd_task_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan task show [name] --json"""
    cmd = ["task", "show"]
    if name := args.get("name"):
        cmd.append(name)
    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_task_show(r.get("result", {})))


def _cmd_task_status(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan status --json"""
    r = _run_plan_cmd(workspace_dir, ["task", "status", "--json"])
    return _with_display(r, _fmt_task_status(r.get("result", {})))


def _cmd_task_notes(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan task notes [text] [--name <name>] [--kind <kind>] (backward compat)"""
    cmd = ["task", "notes"]

    if text := args.get("text"):
        cmd.append(text)

    if name := args.get("name"):
        cmd.extend(["--name", name])

    if kind := args.get("kind"):
        cmd.extend(["--kind", kind])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Task notes"))


def _cmd_task_notes_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Set (upsert) a note on a task."""
    text = args.get("text")
    if not text:
        return {"success": False, "error": "text is required"}

    cmd = ["task", "notes", text]

    if name := args.get("name"):
        cmd.extend(["--name", name])

    if kind := args.get("kind"):
        cmd.extend(["--kind", kind])

    if note_id := args.get("id"):
        cmd.extend(["--id", str(note_id)])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Task notes"))


def _cmd_task_notes_get(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """View notes on a task."""
    cmd = ["task", "notes"]

    if name := args.get("name"):
        cmd.extend(["--name", name])

    if kind := args.get("kind"):
        cmd.extend(["--kind", kind])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Task notes"))


def _cmd_task_notes_delete(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Delete a note from a task by ID."""
    note_id = args.get("id")
    if note_id is None:
        return {"success": False, "error": "id is required"}

    cmd = ["task", "notes", "--delete", str(note_id)]

    if name := args.get("name"):
        cmd.extend(["--name", name])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Task notes"))


# ── Task adopt handler ──

def _cmd_task_adopt(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Adopt (deep-copy) another user's task into your own task list."""
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required (source task name to adopt)"}

    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        new_name = args.get("new_name")
        reset = args.get("reset", True)
        new_context_id = plan_ctx.adopt_context(
            conn,
            source_name=name,
            new_name=new_name,
            reset=reset,
            set_active=True,
            user_id=user_id,
            project_id=project_id,
        )
        result = plan_ctx.get_task_show(conn, new_context_id, project_id=project_id)
        display = f"Adopted task **{name}**" + (f" as **{new_name}**" if new_name else "") + "\n\n"
        display += _fmt_task_show(result)
        return _with_display({"success": True, "result": result}, display)
    finally:
        conn.close()


# ── Step command handlers (individual items) ──

def _cmd_step_switch(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan switch step <number> --json"""
    number = args.get("number")
    if number is None:
        return {"success": False, "error": "number is required"}

    r = _run_plan_cmd(workspace_dir, ["step", "switch", str(number), "--json"])
    return _with_display(r, _fmt_step_show(r.get("result", {})))


def _cmd_step_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step show [number] --json"""
    cmd = ["step", "show"]
    if number := args.get("number"):
        cmd.append(str(number))
    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_step_show(r.get("result", {})))


def _cmd_step_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step list [task] --json"""
    cmd = ["step", "list"]
    if task_name := args.get("task"):
        cmd.append(task_name)
    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_step_list(r.get("result", {})))


def _cmd_step_done(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step done <number> --json"""
    number = args.get("number")
    if number is None:
        return {"success": False, "error": "number is required"}

    r = _run_plan_cmd(workspace_dir, ["step", "done", str(number), "--json"])
    return _with_display(r, _fmt_step_show(r.get("result", {})))


def _cmd_step_notes(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step notes [text] [--step-number <number>] [--kind <kind>] --json (backward compat)"""
    cmd = ["step", "notes"]

    if text := args.get("text"):
        cmd.append(text)

    if number := args.get("number"):
        cmd.extend(["--step-number", str(number)])

    if kind := args.get("kind"):
        cmd.extend(["--kind", kind])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Step notes"))


def _cmd_step_notes_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Set (upsert) a note on a step."""
    text = args.get("text")
    if not text:
        return {"success": False, "error": "text is required"}

    cmd = ["step", "notes", text]

    if number := args.get("number"):
        cmd.extend(["--step-number", str(number)])

    if note_id := args.get("id"):
        cmd.extend(["--id", str(note_id)])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Step notes"))


def _cmd_step_notes_get(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """View notes on a step."""
    cmd = ["step", "notes"]

    if number := args.get("number"):
        cmd.extend(["--step-number", str(number)])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Step notes"))


def _cmd_step_notes_delete(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Delete a note from a step by ID."""
    note_id = args.get("id")
    if note_id is None:
        return {"success": False, "error": "id is required"}

    cmd = ["step", "notes", "--delete", str(note_id)]

    if number := args.get("number"):
        cmd.extend(["--step-number", str(number)])

    cmd.append("--json")

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_notes(r.get("result", {}).get("notes", []), "Step notes"))


def _cmd_step_new(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step new <title> [--task <name>] [--description <md>]"""
    title = args.get("title")
    if not title:
        return {"success": False, "error": "title is required"}

    cmd = ["step", "new", title]

    if task_name := args.get("task"):
        cmd.extend(["--task", task_name])

    if description := args.get("description"):
        cmd.extend(["--description", description])

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_step_show(r.get("result", {})))


def _cmd_step_delete(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step delete <number> [--task <name>]"""
    number = args.get("number")
    if number is None:
        return {"success": False, "error": "number is required"}

    cmd = ["step", "delete", str(number)]

    if task_name := args.get("task"):
        cmd.extend(["--task", task_name])

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_step_list(r.get("result", {})))


def _cmd_step_reorder(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan step reorder --order <list of step numbers in desired order>"""
    order = args.get("order")
    if not order or not isinstance(order, list):
        return {"success": False, "error": "order is required (list of step numbers in desired order)"}

    cmd = ["step", "reorder", "--order", ",".join(str(n) for n in order)]
    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_step_list(r.get("result", {})))


def _fmt_user(data: dict) -> str:
    login = data.get("name", "?")
    alias = data.get("display_name")
    if alias:
        return f"**{alias}** (login: {login})"
    return f"**{login}**"


# ── User command handlers ──

def _cmd_user_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Show current user info."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, _project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    user = plan_db_mod.get_user(conn, user_id)
    conn.close()
    if not user:
        return {"success": False, "error": "User not found"}
    user["project_name"] = _project.get("project_name") if _project else None
    return _with_display({"success": True, "result": user}, _fmt_user(user))


def _cmd_user_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Set display name for current user."""
    alias = args.get("alias")
    if not alias:
        return {"success": False, "error": "alias is required"}
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, _project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    user = plan_db_mod.set_user_display_name(conn, user_id, alias)
    conn.close()
    return _with_display({"success": True, "result": user}, _fmt_user(user))


def _fmt_project(data: dict) -> str:
    name = data.get("project_name", "unnamed")
    path = data.get("absolute_path", "")
    desc = data.get("description_md")
    line = f"**Project**: {name}"
    if desc:
        line += f"\n{desc}"
    if path:
        line += f"\nPath: {path}"
    return line


# ── Project command handlers ──

def _cmd_project_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan project show"""
    r = _run_plan_cmd(workspace_dir, ["project", "show"])
    return _with_display(r, _fmt_project(r.get("result", {})))


def _cmd_project_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan project set [--name <name>] [--description <desc>]"""
    cmd = ["project", "set"]
    if name := args.get("name"):
        cmd.extend(["--name", name])
    if description := args.get("description"):
        cmd.extend(["--description", description])
    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_project(r.get("result", {})))


# ── Config command handlers ──

def _cmd_config_show(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Show current config (merged defaults + file overrides)."""
    from mcpp_plan.config import get_config, DEFAULTS, config_path
    cfg = get_config()
    lines = ["**Configuration**", f"File: `{config_path()}`"]
    for section, keys in cfg.items():
        if isinstance(keys, dict):
            lines.append(f"\n**{section}**")
            defaults_section = DEFAULTS.get(section, {})
            for key, value in keys.items():
                default = defaults_section.get(key) if isinstance(defaults_section, dict) else None
                suffix = "" if value == default else f" (default: {default})"
                lines.append(f"  - **{key}**: `{value}`{suffix}")
    return {"success": True, "result": cfg, "display": "\n".join(lines)}


def _cmd_config_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Set a config key within a section."""
    section = args.get("section")
    key = args.get("key")
    value = args.get("value")
    if not section:
        return {"success": False, "error": "section is required"}
    if not key:
        return {"success": False, "error": "key is required"}
    if value is None:
        return {"success": False, "error": "value is required"}
    from mcpp_plan.config import set_config
    cfg = set_config(section, key, value)
    return {"success": True, "result": cfg, "display": f"Set **{section}.{key}** = `{value}`"}


# ── Report command handlers ──

def _fmt_project_report(data: dict) -> str:
    """Format a project report as markdown."""
    from datetime import datetime, timezone
    project = data.get("project", {})
    tasks = data.get("tasks", [])
    cfg = data.get("config", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    name = project.get("project_name", "unnamed")
    lines.append(f"# Project Report: {name}")
    lines.append("")
    if desc := project.get("description_md"):
        lines.append(desc)
        lines.append("")
    lines.append(f"**Path**: `{project.get('absolute_path', '?')}`")
    lines.append(f"**Generated**: {now}")
    lines.append("")

    # Config summary
    workflow = cfg.get("workflow", {})
    if workflow:
        lines.append("## Configuration")
        lines.append("")
        for k, v in workflow.items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")

    # Task overview
    lines.append("## Tasks")
    lines.append("")
    if not tasks:
        lines.append("No tasks.")
    else:
        lines.append("| # | Task | Status | Progress |")
        lines.append("|---|------|--------|----------|")
        for i, t in enumerate(tasks, 1):
            status = t.get("status", "active")
            done = t.get("steps_done", 0)
            total = t.get("steps_total", 0)
            progress = f"{done}/{total}" if total > 0 else "—"
            lines.append(f"| {i} | {t['name']} | {status} | {progress} |")
        lines.append("")

    # Per-task detail
    for t in tasks:
        lines.append(f"### {t['name']}")
        if t.get("title") and t["title"] != t["name"]:
            lines.append(f"*{t['title']}*")
        lines.append("")
        if goal := t.get("goal"):
            lines.append(f"**Goal**: {goal}")
            lines.append("")
        if plan := t.get("plan"):
            lines.append(f"**Plan**: {plan}")
            lines.append("")
        steps = t.get("steps", [])
        if steps:
            for s in steps:
                if s.get("is_deleted"):
                    continue
                status = s["status"]
                marker = {"planned": " ", "started": ">", "complete": "x"}.get(status, " ")
                lines.append(f"- [{marker}] {s['task_number']}. {s['title']}")
            lines.append("")

    return "\n".join(lines)


def _fmt_task_report(data: dict) -> str:
    """Format a single task report as markdown."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    name = data.get("name", "?")
    title = data.get("title", name)
    status = data.get("status", "?")

    lines.append(f"# Task Report: {name}")
    lines.append("")
    if title != name:
        lines.append(f"*{title}*")
        lines.append("")
    lines.append(f"**Status**: {status}")
    lines.append(f"**Generated**: {now}")
    lines.append("")

    # Goal
    if goals := data.get("goals"):
        lines.append("## Goal")
        lines.append("")
        for g in goals:
            lines.append(g)
        lines.append("")

    # Plan
    if plans := data.get("plans"):
        lines.append("## Plan")
        lines.append("")
        for p in plans:
            lines.append(p)
        lines.append("")

    # Steps
    steps = data.get("steps", [])
    active_step = data.get("active_step")
    if steps:
        lines.append("## Steps")
        lines.append("")
        lines.append("| # | Step | Status |")
        lines.append("|---|------|--------|")
        for s in steps:
            marker = " <--" if s["number"] == active_step else ""
            lines.append(f"| {s['number']} | {s['title']} | {s['status']}{marker} |")
        lines.append("")

        # Step details (descriptions and notes)
        for s in steps:
            has_detail = s.get("description") or s.get("notes")
            if not has_detail:
                continue
            lines.append(f"### Step {s['number']}: {s['title']}")
            lines.append("")
            if desc := s.get("description"):
                lines.append(desc)
                lines.append("")
            if notes := s.get("notes"):
                for n in notes:
                    kind = n.get("kind", "note")
                    kind_tag = f"[{kind}] " if kind != "note" else ""
                    lines.append(f"- {kind_tag}{n['note_md']}")
                lines.append("")

    # Task-level notes
    if notes := data.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            lines.append(f"- {n['note_md']}")
        lines.append("")

    return "\n".join(lines)


def _cmd_project_report(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Generate a project report and write it to the workspace directory."""
    from datetime import datetime
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        data = plan_ctx.get_project_report_data(conn, user_id=user_id, project_id=project_id)
        md = _fmt_project_report(data)
        date_str = datetime.now().strftime("%y%m%d")
        filename = f"project_report_{date_str}.md"
        filepath = Path(workspace_dir) / filename
        filepath.write_text(md, encoding="utf-8")
        return {
            "success": True,
            "result": {"file": str(filepath), "content": md},
            "display": f"Report written to `{filename}`\n\n{md}",
        }
    finally:
        conn.close()


def _cmd_task_report(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Generate a task report and write it to the workspace directory."""
    from datetime import datetime
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        name = args.get("name")
        data = plan_ctx.get_task_report_data(conn, context_ref=name, user_id=user_id, project_id=project_id)
        md = _fmt_task_report(data)
        date_str = datetime.now().strftime("%y%m%d")
        task_name = data.get("name", "task")
        filename = f"task_report_{task_name}_{date_str}.md"
        filepath = Path(workspace_dir) / filename
        filepath.write_text(md, encoding="utf-8")
        return {
            "success": True,
            "result": {"file": str(filepath), "content": md},
            "display": f"Report written to `{filename}`\n\n{md}",
        }
    finally:
        conn.close()


def _cmd_readme(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return the plan README.md as formatted human-readable text."""
    readme_path = Path(__file__).resolve().parent / "README.md"
    if not readme_path.exists():
        return {"success": False, "error": f"README.md not found at {readme_path}"}

    content = readme_path.read_text(encoding="utf-8")
    return {"success": True, "result": content}


# ── Git command handlers ──

def _load_git_mod():
    """Import the git module."""
    import importlib.util
    pkg_path = _pkg_path()
    spec = importlib.util.spec_from_file_location("mcpp_plan.git", pkg_path / "git.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mcpp_plan.git"] = mod
    if spec.loader:
        spec.loader.exec_module(mod)
    return mod


def _get_active_context_info(plan_db_mod, plan_ctx, conn, user_id, project_id):
    """Get active task name and active step number/title for git tagging."""
    context_id = plan_ctx.resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    context_row = conn.execute(
        "SELECT name FROM contexts WHERE id = ?", (context_id,)
    ).fetchone()
    task_name = context_row["name"] if context_row else None

    state_row = conn.execute(
        "SELECT active_task_id FROM context_state WHERE context_id = ?", (context_id,)
    ).fetchone()
    step_number = None
    step_title = None
    if state_row and state_row["active_task_id"]:
        step_row = conn.execute(
            "SELECT sub_index, title FROM tasks WHERE id = ?",
            (state_row["active_task_id"],)
        ).fetchone()
        if step_row:
            step_number = step_row["sub_index"]
            step_title = step_row["title"]

    return task_name, step_number, step_title


def _cmd_checkpoint(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Save current state as a checkpoint commit."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    git_mod = _load_git_mod()
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))

    try:
        user_name = plan_db_mod.get_os_user()
        task_name, step_number, step_title = _get_active_context_info(
            plan_db_mod, plan_ctx, conn, user_id, project_id
        )

        if git_mod.is_clean(workspace_dir):
            return {"success": False, "error": "Nothing to checkpoint — working tree is clean."}

        message = args.get("message")
        if not message:
            if step_number and step_title:
                message = f"checkpoint: step {step_number} — {step_title}"
            elif task_name:
                message = f"checkpoint: {task_name}"
            else:
                message = "checkpoint"

        tag = git_mod.McppTag(user=user_name, task=task_name, step=step_number)
        full_message = git_mod.build_message(message, tag)

        git_mod.add_all(workspace_dir)
        sha = git_mod.commit(workspace_dir, full_message)
        files = git_mod.diff_stat(workspace_dir, sha)

        display = f"Checkpoint **{sha[:8]}**\n"
        if files:
            display += f"{len(files)} file(s): {', '.join(files)}"

        return {
            "success": True,
            "result": {"sha": sha, "files": files, "message": message},
            "display": display,
        }
    finally:
        conn.close()


def _cmd_commit(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Commit with a meaningful message."""
    message = args.get("message")
    if not message:
        return {"success": False, "error": "message is required"}

    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    git_mod = _load_git_mod()
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))

    try:
        user_name = plan_db_mod.get_os_user()
        task_name, step_number, _ = _get_active_context_info(
            plan_db_mod, plan_ctx, conn, user_id, project_id
        )

        if git_mod.is_clean(workspace_dir):
            return {"success": False, "error": "Nothing to commit — working tree is clean."}

        tag = git_mod.McppTag(user=user_name, task=task_name, step=step_number)
        full_message = git_mod.build_message(message, tag)

        git_mod.add_all(workspace_dir)
        sha = git_mod.commit(workspace_dir, full_message)
        files = git_mod.diff_stat(workspace_dir, sha)

        display = f"Committed **{sha[:8]}**: {message}\n"
        if files:
            display += f"{len(files)} file(s): {', '.join(files)}"

        return {
            "success": True,
            "result": {"sha": sha, "files": files, "message": message},
            "display": display,
        }
    finally:
        conn.close()


def _cmd_push(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Pull (fast-forward only) then push."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    git_mod = _load_git_mod()

    if not git_mod.has_remote(workspace_dir):
        return {"success": False, "error": "No remote configured."}

    ok, msg = git_mod.pull_ff_only(workspace_dir)
    if not ok:
        return {
            "success": False,
            "error": f"Pull failed (remote has diverged): {msg}",
            "display": f"Pull failed: {msg}\nResolve manually before pushing.",
        }

    ok, msg = git_mod.push(workspace_dir)
    if not ok:
        return {"success": False, "error": f"Push failed: {msg}"}

    branch = git_mod.current_branch(workspace_dir)
    display = f"Pushed **{branch}** to remote."
    return {"success": True, "result": {"branch": branch, "message": msg}, "display": display}


def _cmd_restore(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Restore (reverse-commit) a previous checkpoint."""
    sha = args.get("sha")
    if not sha:
        return {"success": False, "error": "sha is required"}

    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    git_mod = _load_git_mod()
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))

    try:
        user_name = plan_db_mod.get_os_user()

        # Verify the commit has an mcpp tag belonging to current user
        commit_msg = git_mod.get_commit_message(workspace_dir, sha)
        tag = git_mod.parse_tag(commit_msg)
        if not tag:
            return {"success": False, "error": f"Commit {sha[:8]} has no mcpp tag — cannot verify ownership."}
        if tag.user != user_name:
            return {"success": False, "error": f"Commit {sha[:8]} belongs to user '{tag.user}', not '{user_name}'."}

        # Get files changed in that commit
        files = git_mod.diff_stat(workspace_dir, sha)
        if not files:
            return {"success": False, "error": f"Commit {sha[:8]} has no file changes."}

        # Check which files have been modified by OTHER users since
        skipped = []
        safe_files = []
        for filepath in files:
            subsequent = git_mod.log_file_since(workspace_dir, sha, filepath)
            other_users = set()
            for entry in subsequent:
                entry_tag = entry.get("tag")
                if entry_tag and entry_tag.user and entry_tag.user != user_name:
                    other_users.add(entry_tag.user)
            if other_users:
                skipped.append({"file": filepath, "users": sorted(other_users)})
            else:
                safe_files.append(filepath)

        if not safe_files:
            skip_display = "\n".join(
                f"  - {s['file']} (modified by {', '.join(s['users'])})" for s in skipped
            )
            return {
                "success": False,
                "error": "All files in this commit were modified by other users since.",
                "display": f"Cannot restore {sha[:8]} — all files modified by others:\n{skip_display}",
            }

        # Generate reverse patch, filtered to safe files
        full_patch = git_mod.reverse_patch(workspace_dir, sha)
        if not full_patch.strip():
            return {"success": False, "error": f"Could not generate reverse patch for {sha[:8]}."}

        filtered_patch = git_mod.filter_patch_by_files(full_patch, set(safe_files))
        if not filtered_patch.strip():
            return {"success": False, "error": "Filtered patch is empty after removing conflicting files."}

        # Apply the patch
        ok, apply_msg = git_mod.apply_patch(workspace_dir, filtered_patch)
        if not ok:
            return {"success": False, "error": f"Patch failed to apply: {apply_msg}"}

        # Commit the revert
        original_subject = git_mod.strip_tag(commit_msg).split("\n")[0]
        task_name, step_number, _ = _get_active_context_info(
            plan_db_mod, plan_ctx, conn, user_id, project_id
        )
        revert_tag = git_mod.McppTag(user=user_name, task=task_name, step=step_number)
        revert_message = git_mod.build_message(f"revert: {original_subject}", revert_tag)

        git_mod.add_all(workspace_dir)
        revert_sha = git_mod.commit(workspace_dir, revert_message)

        # Build display
        display_lines = [f"Reverted **{sha[:8]}** as **{revert_sha[:8]}**"]
        display_lines.append(f"Files restored: {', '.join(safe_files)}")
        if skipped:
            display_lines.append("Files skipped (modified by other users):")
            for s in skipped:
                display_lines.append(f"  - {s['file']} ({', '.join(s['users'])})")

        return {
            "success": True,
            "result": {
                "original_sha": sha,
                "revert_sha": revert_sha,
                "restored_files": safe_files,
                "skipped_files": skipped,
            },
            "display": "\n".join(display_lines),
        }
    finally:
        conn.close()


def _cmd_log(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Show commit history filtered by user/task/step."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    git_mod = _load_git_mod()
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))

    try:
        user_filter = args.get("user")
        task_filter = args.get("task")
        step_filter = args.get("step")
        show_all = args.get("show_all", False)
        max_count = args.get("max_count", 50)

        # Default: current user's commits for active task
        if not show_all and not user_filter:
            user_filter = plan_db_mod.get_os_user()
        if not show_all and not task_filter:
            try:
                task_name, _, _ = _get_active_context_info(
                    plan_db_mod, plan_ctx, conn, user_id, project_id
                )
                task_filter = task_name
            except Exception:
                pass

        entries = git_mod.log(workspace_dir, max_count=max_count)

        # Filter by mcpp tag
        filtered = []
        for e in entries:
            tag = e.get("tag")
            if not show_all and not tag:
                continue
            if user_filter and (not tag or tag.user != user_filter):
                continue
            if task_filter and (not tag or tag.task != task_filter):
                continue
            if step_filter is not None and (not tag or tag.step != step_filter):
                continue
            filtered.append(e)

        # Format display
        if not filtered:
            return {"success": True, "result": {"entries": []}, "display": "No matching commits."}

        lines = [f"**Log** ({len(filtered)} commits)"]
        for e in filtered:
            sha_short = e["sha"][:8]
            tag = e.get("tag")
            user_str = tag.user if tag else e["author"]
            subject = git_mod.strip_tag(f"{e['subject']}\n{e['body']}").split("\n")[0]
            date_short = e["date"][:10]
            step_str = f" step {tag.step}" if tag and tag.step else ""
            lines.append(f"  {sha_short} {date_short} [{user_str}{step_str}] {subject}")

        result_entries = []
        for e in filtered:
            tag = e.get("tag")
            result_entries.append({
                "sha": e["sha"],
                "date": e["date"],
                "user": tag.user if tag else e["author"],
                "task": tag.task if tag else None,
                "step": tag.step if tag else None,
                "subject": git_mod.strip_tag(f"{e['subject']}\n{e['body']}").split("\n")[0],
            })

        return {
            "success": True,
            "result": {"entries": result_entries},
            "display": "\n".join(lines),
        }
    finally:
        conn.close()


def _cmd_status(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Show uncommitted changes with user ownership annotations."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    git_mod = _load_git_mod()

    entries = git_mod.status_porcelain(workspace_dir)
    if not entries:
        return {"success": True, "result": {"files": []}, "display": "Working tree is clean."}

    # Annotate each file with last committer from mcpp tags
    annotated = []
    for e in entries:
        filepath = e["path"]
        last_user = None
        # Check last commit that touched this file
        try:
            recent = git_mod.log(workspace_dir, max_count=5)
            for commit_entry in recent:
                files_in_commit = git_mod.diff_stat(workspace_dir, commit_entry["sha"])
                if filepath in files_in_commit:
                    tag = commit_entry.get("tag")
                    if tag and tag.user:
                        last_user = tag.user
                    break
        except Exception:
            pass

        annotated.append({
            "status": e["status"],
            "path": filepath,
            "last_user": last_user,
        })

    # Format
    status_map = {"M": "modified", "A": "added", "D": "deleted", "??": "new", "MM": "modified"}
    lines = [f"**Status** ({len(annotated)} files)"]
    for a in annotated:
        status_label = status_map.get(a["status"], a["status"])
        user_str = f" [{a['last_user']}]" if a["last_user"] else ""
        lines.append(f"  {status_label}: {a['path']}{user_str}")

    return {
        "success": True,
        "result": {"files": annotated},
        "display": "\n".join(lines),
    }


def _cmd_diff(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Show diff between checkpoints or since last checkpoint."""
    for stale in [k for k in sys.modules if k == "mcpp_plan" or k.startswith("mcpp_plan.")]:
        del sys.modules[stale]
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    git_mod = _load_git_mod()

    from_ref = args.get("from")
    to_ref = args.get("to")

    if from_ref and to_ref:
        # Diff between two specific refs
        diff_text = git_mod.diff_range(workspace_dir, from_ref, to_ref)
    elif from_ref:
        # Diff from ref to working tree
        diff_text = git_mod.diff_working(workspace_dir, from_ref)
    else:
        # Diff since last mcpp checkpoint for current user/task
        conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
        try:
            user_name = plan_db_mod.get_os_user()
            task_name = None
            try:
                task_name, _, _ = _get_active_context_info(
                    plan_db_mod, plan_ctx, conn, user_id, project_id
                )
            except Exception:
                pass

            entries = git_mod.log(workspace_dir, max_count=100)
            last_sha = None
            for e in entries:
                tag = e.get("tag")
                if tag and tag.user == user_name:
                    if task_name is None or tag.task == task_name:
                        last_sha = e["sha"]
                        break

            if last_sha:
                diff_text = git_mod.diff_working(workspace_dir, last_sha)
            else:
                diff_text = git_mod.diff_working(workspace_dir, "HEAD")
        finally:
            conn.close()

    if not diff_text.strip():
        return {"success": True, "result": {"diff": ""}, "display": "No differences."}

    # Truncate for display if very long
    display = diff_text
    if len(display) > 5000:
        display = display[:5000] + f"\n... ({len(diff_text)} chars total, truncated)"

    return {
        "success": True,
        "result": {"diff": diff_text},
        "display": f"```diff\n{display}\n```",
    }
