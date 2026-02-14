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
        lines.append(f"- {kind_tag}{n['note']}{actor}")
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
            if status == "archived":
                active = " [archived]"
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
            if status == "archived":
                active = " [archived]"
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
    num = data.get("task_number", "?")
    title = data.get("title", "?")
    status = data.get("status", "?")
    desc = data.get("description_md")
    line = f"**Step {num}**: {title} [{status}]"
    if desc:
        line += f"\n{desc}"
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

                    if action == "archive":
                        name = cmd_args[2] if len(cmd_args) > 2 else None
                        if not name:
                            conn.close()
                            return {"success": False, "error": "task name required"}
                        plan_ctx.archive_task(conn, name, user_id=_user_id, project_id=_project_id)
                        tasks = plan_ctx.list_tasks(conn, status_filter="active", user_id=_user_id, project_id=_project_id)
                        conn.close()
                        return {"success": True, "result": {"archived": name, "tasks": tasks}}

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
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--name" and i + 1 < len(cmd_args):
                                name = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--kind" and i + 1 < len(cmd_args):
                                kind = cmd_args[i + 1]
                                i += 2
                            elif not cmd_args[i].startswith("--"):
                                text = cmd_args[i]
                                i += 1
                            else:
                                i += 1

                        if text:
                            plan_ctx.add_context_note(conn, text, context_ref=name, user_id=_user_id, project_id=_project_id, kind=kind or "note")
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

                    elif action == "notes":
                        number = None
                        text = None
                        kind = None
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--step-number" and i + 1 < len(cmd_args):
                                number = int(cmd_args[i + 1])
                                i += 2
                            elif cmd_args[i] == "--kind" and i + 1 < len(cmd_args):
                                kind = cmd_args[i + 1]
                                i += 2
                            elif not cmd_args[i].startswith("--"):
                                text = cmd_args[i]
                                i += 1
                            else:
                                i += 1

                        if text:
                            plan_ctx.add_step_note(conn, text, step_number=number, user_id=_user_id, project_id=_project_id, kind=kind or "note")
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
        "plan_task_archive": _cmd_task_archive,
        "plan_task_switch": _cmd_task_switch,
        "plan_task_show": _cmd_task_show,
        "plan_task_status": _cmd_task_status,
        "plan_task_notes": _cmd_task_notes,
        # Step tools (individual items)
        "plan_step_switch": _cmd_step_switch,
        "plan_step_show": _cmd_step_show,
        "plan_step_list": _cmd_step_list,
        "plan_step_done": _cmd_step_done,
        "plan_step_notes": _cmd_step_notes,
        "plan_step_new": _cmd_step_new,
        "plan_step_delete": _cmd_step_delete,
        # User tools
        "plan_user_show": _cmd_user_show,
        "plan_user_set": _cmd_user_set,
        # Project tools (workspace metadata)
        "plan_project_show": _cmd_project_show,
        "plan_project_set": _cmd_project_set,
        # Config tools
        "plan_config_show": _cmd_config_show,
        "plan_config_set": _cmd_config_set,
        # Utility
        "plan_readme": _cmd_readme,
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
    if not args.get("show_archived"):
        cmd.extend(["--status", "active"])
    if args.get("show_all"):
        cmd.append("--all")
    cmd.append("--json")
    r = _run_plan_cmd(workspace_dir, cmd)
    tasks = r.get("result", {}).get("tasks", [])
    show_all = args.get("show_all", False)
    return _with_display(r, _fmt_task_list(tasks, grouped=show_all))


def _cmd_task_archive(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan task archive <name>"""
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}
    r = _run_plan_cmd(workspace_dir, ["task", "archive", name])
    return _with_display(r, f"Archived task **{name}**.")


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
    """plan task notes [text] [--name <name>] [--kind <kind>]"""
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
    """plan step notes [text] [--step-number <number>] [--kind <kind>] --json"""
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
    from config import get_config, DEFAULTS, config_path
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
    from config import set_config
    cfg = set_config(section, key, value)
    return {"success": True, "result": cfg, "display": f"Set **{section}.{key}** = `{value}`"}


def _cmd_readme(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return the plan README.md as formatted human-readable text."""
    readme_path = Path(__file__).resolve().parent / "README.md"
    if not readme_path.exists():
        return {"success": False, "error": f"README.md not found at {readme_path}"}

    content = readme_path.read_text(encoding="utf-8")
    return {"success": True, "result": content}
