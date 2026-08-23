"""
Plan: Task & Step Manager (MCP Tool Wrapper)

Exposes plan task and step operations as MCP tools.
Operates on workspace-local plan.db for autonomous task tracking.
"""

from __future__ import annotations

import json
import logging
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


def _fmt_inline_attachments(workspace_dir: str, *, project_id=None, context_id=None, task_id=None) -> str:
    """Load and format file attachments for inline display in show tools. Returns '' if none."""
    try:
        pkg_path = _pkg_path()
        plan_db_mod, plan_ctx = _load_pkg(pkg_path)
        cfg_mod = _load_config_mod()
        max_lines = cfg_mod.get_config().get("attachments", {}).get("inline_lines", 100)
        db_path = plan_db_mod.default_db_path()
        conn = plan_db_mod.connect(db_path)
        plan_db_mod.ensure_schema(conn)
        try:
            attachments = plan_ctx.list_attachments(
                conn, workspace_dir,
                project_id=project_id, context_id=context_id, task_id=task_id,
            )
        finally:
            conn.close()
        if not attachments:
            return ""
        lines = ["\n**Attachments**"]
        for a in attachments:
            label_tag = f" — {a['label']}" if a.get("label") else ""
            if a["broken"]:
                lines.append(f"  `{a['file_path']}` ({a['kind']}){label_tag} ⚠ file not found")
            else:
                c = plan_ctx.read_attachment_content(a["file_path"], workspace_dir, max_lines)
                lines.append(f"  `{a['file_path']}` ({a['kind']}){label_tag}")
                lines.append(f"```\n{c['content']}\n```")
                if c["truncated"]:
                    lines.append(f"  *({c['line_count']} lines total — truncated at {max_lines})*")
        return "\n".join(lines)
    except Exception:
        return ""


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


def _fmt_task_titles_only(data: dict) -> str:
    name = data.get("context_name", "?")
    title = data.get("context_title", name)
    active_num = data.get("active_task_number")
    lines = [f"**{name}**: {title}"]
    for t in data.get("tasks", []):
        if t.get("is_deleted"):
            continue
        num = t["task_number"]
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


def _display_task_no_steps(r: dict) -> str:
    """Regenerate task display without step info."""
    lines = [f"**{r.get('context_name', '?')}**: {r.get('context_title', '')}"]
    if g := r.get("goal"):
        lines.append(f"  **Goal**: {g}")
    if p := r.get("plan"):
        lines.append(f"  **Plan**: {p}")
    if notes := r.get("notes"):
        lines.append(_fmt_notes(notes, "Task notes"))
    return "\n".join(lines)


def _display_status_no_steps(r: dict) -> str:
    """Regenerate status display without step info."""
    return f"**{r.get('context_name', '?')}**: {r.get('context_title', '')}"


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


def _load_config_mod():
    """Load config module standalone (no dependency on _load_pkg)."""
    import importlib.util as ilu
    cfg_path = Path(__file__).resolve().parent / "config.py"
    spec = ilu.spec_from_file_location("_plan_config_rx", str(cfg_path))
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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

    Override chain:
    1. User's project override (set by plan_project_select)
    2. workspace_dir auto-detect (existing behaviour)

    Returns (conn, project_dict, is_new_project, user_id, project_id).
    """
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    user_id = plan_db_mod.get_or_create_user(conn, plan_db_mod.get_os_user())

    # Check for project override — web requests only (workspace_dir is not a real dir)
    if not Path(workspace_dir).is_dir():
        override_id = plan_ctx.get_active_project_override(conn, user_id)
        if override_id is not None:
            project = plan_ctx.get_project(conn, project_id=override_id)
            if project:
                return conn, project, False, user_id, project["id"]

    if not Path(workspace_dir).is_absolute():
        conn.close()
        raise ValueError(
            f"workspace_dir '{workspace_dir}' is not an absolute path — "
            "cannot resolve project. Ensure the MCP server is configured with an absolute workspace."
        )

    project, is_new = plan_ctx.ensure_project(conn, str(workspace_dir))
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
                    area = None
                    steps_list = []
                    i = 3
                    while i < len(cmd_args):
                        if cmd_args[i] == "--title" and i + 1 < len(cmd_args):
                            title = cmd_args[i + 1]
                            i += 2
                        elif cmd_args[i] == "--step" and i + 1 < len(cmd_args):
                            steps_list.append(plan_ctx.StepInput(title=cmd_args[i + 1]))
                            i += 2
                        elif cmd_args[i] == "--area" and i + 1 < len(cmd_args):
                            area = cmd_args[i + 1]
                            i += 2
                        else:
                            i += 1

                    if not steps_list:
                        steps_list = [plan_ctx.StepInput(title="New step")]

                    if area:
                        err = plan_ctx.validate_area(conn, area, project_id=_project_id)
                        if err:
                            conn.close()
                            return {"success": False, "error": err}

                    task_id = plan_ctx.create_task(
                        conn,
                        name=name,
                        description_md=title,
                        steps=steps_list,
                        set_active=True,
                        user_id=_user_id,
                        project_id=_project_id,
                        area=area,
                    )
                    result = plan_ctx.get_task_show(conn, task_id, project_id=_project_id)
                    conn.close()
                    return {"success": True, "result": result}

                elif action == "list":
                    conn, _project, _is_new, _user_id, _project_id = _open_db(plan_db_mod, plan_ctx, workspace_dir)
                    status_filter = None
                    show_all_users = False
                    area_filter = None
                    i = 2
                    while i < len(cmd_args):
                        if cmd_args[i] == "--status" and i + 1 < len(cmd_args):
                            status_filter = cmd_args[i + 1]
                            i += 2
                        elif cmd_args[i] == "--all":
                            show_all_users = True
                            i += 1
                        elif cmd_args[i] == "--area" and i + 1 < len(cmd_args):
                            area_filter = cmd_args[i + 1]
                            i += 2
                        else:
                            i += 1
                    if area_filter:
                        err = plan_ctx.validate_area(conn, area_filter, project_id=_project_id)
                        if err:
                            conn.close()
                            return {"success": False, "error": err}
                    tasks = plan_ctx.list_tasks(
                        conn, status_filter=status_filter,
                        user_id=_user_id, show_all_users=show_all_users,
                        project_id=_project_id, area_filter=area_filter,
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
                        if task_ref:
                            # get_step_summary resolves via active context — wrong when task_ref
                            # differs. Query by step_id directly to avoid false "not found" error.
                            row = conn.execute(
                                "SELECT id, context_id, task_number, title, description_md, status, "
                                "parent_id, sort_index, sub_index, created_at, updated_at, completed_at "
                                "FROM tasks WHERE id = ?",
                                (step_id,),
                            ).fetchone()
                            result = dict(row) if row else {}
                            result["notes"] = []
                        else:
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
                if action == "relink":
                    db_path = plan_db_mod.default_db_path()
                    conn = plan_db_mod.connect(db_path)
                    plan_db_mod.ensure_schema(conn)
                    try:
                        project_id = None
                        old_path = None
                        name = None
                        new_path = str(workspace_dir)
                        new_name = None
                        i = 2
                        while i < len(cmd_args):
                            if cmd_args[i] == "--project-id" and i + 1 < len(cmd_args):
                                project_id = int(cmd_args[i + 1])
                                i += 2
                            elif cmd_args[i] == "--old-path" and i + 1 < len(cmd_args):
                                old_path = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--name" and i + 1 < len(cmd_args):
                                name = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--new-path" and i + 1 < len(cmd_args):
                                new_path = cmd_args[i + 1]
                                i += 2
                            elif cmd_args[i] == "--new-name" and i + 1 < len(cmd_args):
                                new_name = cmd_args[i + 1]
                                i += 2
                            else:
                                i += 1
                        result = plan_ctx.relink_project(
                            conn,
                            project_id=project_id,
                            old_path=old_path,
                            name=name,
                            new_path=new_path,
                            new_name=new_name,
                        )
                        return {"success": True, "result": result}
                    finally:
                        conn.close()

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


def _ensure_file_logging() -> None:
    """Add a rotating file handler to the mcpp logger, writing to plan.log in the module directory."""
    from logging.handlers import RotatingFileHandler
    logger = logging.getLogger("mcpp")
    # Check for existing file handler (survives module reimport)
    if any(isinstance(h, (logging.FileHandler, RotatingFileHandler)) for h in logger.handlers):
        return
    try:
        log_file = Path(__file__).resolve().parent / "plan.log"
        handler = RotatingFileHandler(
            str(log_file), maxBytes=1_000_000, backupCount=3, encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s %(process)d %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    except Exception:
        pass


_tool_log = logging.getLogger("mcpp.tool")


def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a plan command via MCP tool interface."""
    workspace_dir = (context or {}).get("workspace_dir", ".")
    _ensure_file_logging()
    _tool_log.debug("CALL %s args=%s", tool_name, arguments)

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
        "plan_project_list": _cmd_project_list,
        "plan_project_set": _cmd_project_set,
        "plan_project_select": _cmd_project_select,
        "plan_project_relink": _cmd_project_relink,
        "plan_project_purge": _cmd_project_purge,
        # File attachment tools
        "plan_file_attach": _cmd_file_attach,
        "plan_file_detach": _cmd_file_detach,
        "plan_file_list": _cmd_file_list,
        # Config tools
        "plan_config_show": _cmd_config_show,
        # plan_config_set removed — config is operator-only (edit config.yaml directly)
        # Task adoption
        "plan_task_adopt": _cmd_task_adopt,
        "plan_task_move": _cmd_task_move,
        "plan_task_rename": _cmd_task_rename,
        "plan_step_retitle": _cmd_step_retitle,
        # Area tools
        "plan_area_new":      _cmd_area_new,
        "plan_area_list":     _cmd_area_list,
        "plan_area_rename":   _cmd_area_rename,
        "plan_area_delete":   _cmd_area_delete,
        "plan_area_describe": _cmd_area_describe,
        "plan_task_set_area": _cmd_task_set_area,
        # Roadmap tools
        "plan_roadmap_focus": _cmd_roadmap_focus,
        "plan_roadmap_next":  _cmd_roadmap_next,
        "plan_roadmap_all":   _cmd_roadmap_all,
        # Report tools
        "plan_project_report": _cmd_project_report,
        "plan_task_report": _cmd_task_report,
        # Utility
        "plan_readme": _cmd_readme,
    }

    # Git tools moved permanently to mcpp-git (dev_* tools)
    _MOVED_TOOLS = {
        "plan_checkpoint": "dev_checkpoint",
        "plan_commit": "dev_commit",
        "plan_push": "dev_push",
        "plan_sync": "dev_sync",
        "plan_file_restore": "dev_file_restore",
        "plan_log": "dev_log",
        "plan_status": "dev_status",
        "plan_diff": "dev_diff",
        "plan_show": "dev_show",
        "plan_file_history": "dev_file_history",
        "plan_file_owner": "dev_file_owner",
    }

    if tool_name in _MOVED_TOOLS:
        new_name = _MOVED_TOOLS[tool_name]
        return {
            "success": False,
            "error": f"'{tool_name}' has been permanently moved to mcpp-git. Use '{new_name}' instead.",
        }

    handler = tool_map.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    # RX filter: block disabled feature tools
    _cfg_mod = _load_config_mod()
    _blocked = _cfg_mod.disabled_tools()
    if tool_name in _blocked:
        feature = "steps"
        return {"success": False, "error": f"Tool '{tool_name}' is disabled (enable_{feature}: false in config.yaml)"}

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

            # Clear stale active-context cursor: active_context_id for this
            # user+project must belong to this project (can drift after move_task).
            if _user_id and _proj_id:
                _stale = conn.execute(
                    "SELECT us.active_context_id FROM user_state us "
                    "JOIN contexts c ON c.id = us.active_context_id "
                    "WHERE us.user_id = ? AND us.project_id = ? AND c.project_id != ?",
                    (_user_id, _proj_id, _proj_id),
                ).fetchone()
                if _stale:
                    plan_db_mod.upsert_user_state(conn, _user_id, _proj_id, None)
                    conn.commit()

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

            # Nag: any task in this project where all steps are done but task not closed
            if tool_name != "plan_task_complete" and _proj_id:
                rows = conn.execute(
                    "SELECT c.name FROM contexts c "
                    "WHERE c.project_id = ? AND c.status = 'active' "
                    "AND (SELECT COUNT(*) FROM tasks t WHERE t.context_id = c.id AND t.is_deleted = 0) > 0 "
                    "AND (SELECT COUNT(*) FROM tasks t WHERE t.context_id = c.id AND t.is_deleted = 0 AND t.status != 'completed') = 0",
                    (_proj_id,),
                ).fetchall()
                if rows:
                    names = ", ".join(f"`{r[0]}`" for r in rows)
                    nag = (
                        f"\n\n---\n⚠ {len(rows)} task(s) have all steps complete but are not closed: "
                        f"{names}. Call `plan_task_complete` for each."
                    )
                    result["display"] = (result.get("display", "") + nag)

            # Nag: active tasks with no activity for stale_task_days days
            _stale_days = _load_config_mod().get_config().get("workflow", {}).get("stale_task_days", 0)
            if _stale_days and _proj_id:
                stale_rows = conn.execute(
                    "SELECT c.name FROM contexts c "
                    "WHERE c.project_id = ? AND c.status = 'active' "
                    "AND MAX("
                    "    c.updated_at,"
                    "    COALESCE("
                    "        (SELECT MAX(t.updated_at) FROM tasks t"
                    "         WHERE t.context_id = c.id AND t.is_deleted = 0),"
                    "        c.updated_at"
                    "    )"
                    ") < datetime('now', ?)",
                    (_proj_id, f"-{_stale_days} days"),
                ).fetchall()
                if stale_rows:
                    snames = ", ".join(f"`{r[0]}`" for r in stale_rows)
                    stale_nag = (
                        f"\n\n---\n⚠ {len(stale_rows)} task(s) have had no activity"
                        f" for {_stale_days}+ days: {snames}. Review or close."
                    )
                    result["display"] = (result.get("display", "") + stale_nag)

            # Nag: project has active tasks but no areas defined in plan.db
            if _proj_id:
                has_areas = conn.execute(
                    "SELECT 1 FROM areas WHERE project_id = ? LIMIT 1", (_proj_id,)
                ).fetchone()
                if not has_areas:
                    has_tasks = conn.execute(
                        "SELECT 1 FROM contexts WHERE project_id = ? AND status = 'active' LIMIT 1",
                        (_proj_id,),
                    ).fetchone()
                    if has_tasks:
                        result["display"] = (result.get("display", "") +
                            "\n\n---\n📋 No areas defined for this project. "
                            "Use `plan_area_new` to define functional areas and enable area-based tracking.")

            conn.close()
        except Exception:
            pass

        # TX filter: strip step data when steps disabled
        cfg = _load_config_mod().get_config().get("workflow", {})
        if not cfg.get("enable_steps", True) and isinstance(result.get("result"), dict):
            r = result["result"]
            tasks = r.get("tasks")
            if isinstance(tasks, list) and tasks and isinstance(tasks[0], dict):
                if "task_number" in tasks[0]:
                    del r["tasks"]
                else:
                    for entry in tasks:
                        entry.pop("active_task_number", None)
                        entry.pop("active_task_title", None)
            for k in ("active_task_number", "active_task_title",
                       "planned_count", "started_count", "completed_count",
                       "blocked_count", "deleted_count"):
                r.pop(k, None)
            if tool_name in {"plan_task_show", "plan_task_new", "plan_task_adopt"}:
                result["display"] = _display_task_no_steps(r)
            elif tool_name in {"plan_task_status", "plan_task_switch"}:
                result["display"] = _display_status_no_steps(r)

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

    if area := args.get("area"):
        cmd.extend(["--area", area])

    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_task_show(r.get("result", {})))


def _cmd_task_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan list tasks [--status <filter>] [--all] --json"""
    cmd = ["task", "list"]
    if not args.get("show_completed"):
        cmd.extend(["--status", "active"])
    if args.get("show_all"):
        cmd.append("--all")
    if area := args.get("area"):
        cmd.extend(["--area", area])
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
    if args.get("titles_only"):
        display = _fmt_task_titles_only(r.get("result", {}))
    else:
        display = _fmt_task_show(r.get("result", {}))
        display += _fmt_inline_attachments(workspace_dir, context_id=r.get("result", {}).get("context_id"))
    return _with_display(r, display)


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


def _cmd_task_move(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Move a task to a different project."""
    name = args.get("name")
    project_ref = args.get("project")
    if not name:
        return {"success": False, "error": "name is required"}
    if not project_ref:
        return {"success": False, "error": "project is required (target project name or id)"}

    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        # Resolve source context
        try:
            context_id = plan_ctx.resolve_context_id(conn, name, project_id=project_id)
        except Exception:
            return {"success": False, "error": f"Task '{name}' not found in current project."}

        # Resolve target project — by id if numeric, else by name
        if str(project_ref).isdigit():
            target_project = plan_ctx.get_project(conn, project_id=int(project_ref))
        else:
            rows = conn.execute(
                "SELECT id FROM project WHERE project_name = ?", (project_ref,)
            ).fetchall()
            if not rows:
                return {"success": False, "error": f"Target project '{project_ref}' not found."}
            if len(rows) > 1:
                ids = ", ".join(str(r[0]) for r in rows)
                return {"success": False, "error": f"Project name '{project_ref}' is ambiguous (ids: {ids}). Use numeric id instead."}
            target_project = plan_ctx.get_project(conn, project_id=rows[0][0])

        if not target_project:
            return {"success": False, "error": f"Target project '{project_ref}' not found."}

        try:
            result = plan_ctx.move_task(conn, context_id, target_project["id"])
        except ValueError as e:
            return {"success": False, "error": str(e)}

        src = result["from_project"]
        tgt = result["to_project"]
        lines = [
            f"Moved task `{result['name']}` from **{src['project_name']}** to **{tgt['project_name']}**",
            f"  From: `{src['absolute_path']}`",
            f"  To:   `{tgt['absolute_path']}`",
        ]
        if result["attachments"]:
            lines.append("\nAttached files — move manually:")
            for a in result["attachments"]:
                lines.append(f"  `{a['from']}`  →  `{a['to']}`")
        else:
            lines.append("\nNo attached files to move.")

        return {"success": True, "result": result, "display": "\n".join(lines)}
    finally:
        conn.close()


def _cmd_task_rename(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Rename a task's display title (contexts.description_md). Slug unchanged."""
    name = args.get("name")
    title = args.get("title")
    if not name:
        return {"success": False, "error": "name is required"}
    if not title:
        return {"success": False, "error": "title is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.rename_task(conn, name, title, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Renamed `{name}` → {title}"}
    finally:
        conn.close()


def _cmd_step_retitle(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Retitle a step by sub_index. Preserves status, completed_at, and order."""
    number = args.get("number")
    title = args.get("title")
    if number is None:
        return {"success": False, "error": "number is required"}
    if not title:
        return {"success": False, "error": "title is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.retitle_step(conn, number, title, user_id=user_id, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Step {number} retitled → {title}"}
    finally:
        conn.close()


# ── Area command handlers ──

def _cmd_area_new(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name  = args.get("name")
    items = args.get("items")
    if items is not None and name:
        return {"success": False, "error": "supply either 'name' or 'items', not both"}
    if items is not None and len(items) == 0:
        return {"success": False, "error": "items list is empty"}
    if items is None and not name:
        return {"success": False, "error": "name is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        if items:
            created = plan_ctx.create_areas_batch(conn, items, project_id=project_id)
            names = ", ".join(f"**{a['name']}**" for a in created)
            return {"success": True, "result": {"created": len(created), "areas": created},
                    "display": f"Areas created ({len(created)}): {names}"}
        description_md = args.get("description")
        area_class = args.get("class") or None
        priority = args.get("priority")
        scope = args.get("scope") or None
        watch = args.get("watch") or None
        depends = args.get("depends") or None
        result = plan_ctx.create_area(conn, name, description_md=description_md,
                                      project_id=project_id, area_class=area_class,
                                      priority=priority, scope=scope, watch=watch,
                                      depends=depends)
        class_note = f" ({area_class})" if area_class else ""
        return {"success": True, "result": result,
                "display": f"Area created: **{name}**{class_note}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_area_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        areas = plan_ctx.list_areas(conn, project_id=project_id)
        lines = [f"**Areas** ({len(areas)})"]
        for a in areas:
            desc_line = (a.get("description_md") or "").split("\n")[0].strip()
            desc = f" — {desc_line}" if desc_line else ""
            cls = a.get("class") or "unclassed"
            pri = f", priority {a['priority']}" if a.get("priority") is not None else ""
            extra = ""
            if a.get("scope"):
                extra += f"\n      scope: {', '.join(a['scope'])}"
            if a.get("watch"):
                extra += f"\n      watch: {', '.join(a['watch'])}"
            if a.get("depends"):
                extra += f"\n      depends: {', '.join(a['depends'])}"
            lines.append(f"  - {a['name']} ({cls}{pri}){desc}{extra}")
        display = "\n".join(lines) if areas else "No areas defined. Use `plan_area_new` to create one."
        return {"success": True, "result": {"areas": areas}, "display": display}
    finally:
        conn.close()


def _cmd_area_rename(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    new_name = args.get("new_name")
    if not name:
        return {"success": False, "error": "name is required"}
    if not new_name:
        return {"success": False, "error": "new_name is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.rename_area(conn, name, new_name, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Area renamed: **{name}** → **{new_name}**"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_area_delete(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        result = plan_ctx.delete_area(conn, name, project_id=project_id)
        return {"success": True, "result": result,
                "display": f"Area deleted: **{name}**"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_area_describe(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return {"success": False, "error": "name is required"}
    description = args.get("description")
    area_class = args.get("class") or None
    priority = args.get("priority")
    scope = args.get("scope") or None
    watch = args.get("watch") or None
    depends = args.get("depends") or None
    _update_class = "class" in args
    _update_priority = "priority" in args
    _update_desc = "description" in args
    _update_scope = "scope" in args
    _update_watch = "watch" in args
    _update_depends = "depends" in args
    if not any([_update_desc, _update_class, _update_priority,
                _update_scope, _update_watch, _update_depends]):
        return {"success": False,
                "error": "supply at least one of: description, class, priority, scope, watch, depends"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        err = plan_ctx.update_area_description(
            conn, name, description, project_id=project_id,
            area_class=area_class, priority=priority,
            scope=scope, watch=watch, depends=depends,
            _update_class=_update_class, _update_priority=_update_priority,
            _update_desc=_update_desc, _update_scope=_update_scope,
            _update_watch=_update_watch, _update_depends=_update_depends,
        )
        if err:
            return {"success": False, "error": err}
        parts = []
        if _update_desc:
            parts.append("description")
        if _update_class:
            parts.append(f"class={area_class or 'cleared'}")
        if _update_priority:
            parts.append(f"priority={priority}")
        if _update_scope:
            parts.append(f"scope={scope or 'cleared'}")
        if _update_watch:
            parts.append(f"watch={watch or 'cleared'}")
        if _update_depends:
            parts.append(f"depends={depends or 'cleared'}")
        return {"success": True, "result": {"name": name},
                "display": f"Updated **{name}**: {', '.join(parts)}"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_roadmap_focus(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    area = args.get("area")
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    project_name = project.get("project_name", "") if project else ""
    try:
        all_areas = plan_ctx.list_areas(conn, project_id=project_id)
        area_names = [a["name"] for a in all_areas]
        if not area_names:
            return {"success": False, "error": "no areas defined",
                    "result": {"focus": None, "areas": [], "project_name": project_name},
                    "display": f"No areas defined for **{project_name}**.\nUse `plan_area_new` to define areas first."}
        if area is None:
            focus = plan_ctx.get_focus_area(conn, user_id, project_id)
            if focus is None:
                display = (
                    "No focus area set. Use `plan_roadmap_focus` with `area=<name>` to set one, "
                    "or `plan_roadmap_next` to see what to work on.\n"
                    f"Areas: {', '.join(area_names)}"
                )
                return {"success": True,
                        "result": {"focus": None, "areas": area_names, "project_name": project_name},
                        "display": display}
            return {"success": True,
                    "result": {"focus": focus, "areas": area_names, "project_name": project_name},
                    "display": f"Focus: **{focus}**  (project: {project_name})"}
        if area not in area_names:
            return {"success": False,
                    "error": f"unknown area '{area}'. Valid: {', '.join(area_names)}",
                    "result": {"focus": None, "areas": area_names, "project_name": project_name}}
        plan_ctx.set_focus_area(conn, user_id, project_id, area)
        return {"success": True,
                "result": {"focus": area, "areas": area_names, "project_name": project_name},
                "display": f"Focus set: **{area}**  (project: {project_name})"}
    finally:
        conn.close()


def _cmd_roadmap_next(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    project_name = project.get("project_name", "") if project else ""
    try:
        data = plan_ctx.roadmap_all_data(conn, project_id)
        areas = data["areas"]
        unfiled = data["unfiled"]
        if not areas:
            unfiled_note = (f"\n\n**IN NO AREA:** {len(unfiled)} active task(s) with no area assigned."
                            if unfiled else "")
            return {"success": False,
                    "error": "no areas defined — use plan_area_new first",
                    "result": {"ranked": [], "parked": [], "unfiled": unfiled,
                               "focus": None, "project_name": project_name},
                    "display": f"**Roadmap next** (project: {project_name})\n\nNo areas defined. Use `plan_area_new` to create areas.{unfiled_note}"}
        focus = plan_ctx.get_focus_area(conn, user_id, project_id)
        all_with_open = [a for a in areas if a["open"] > 0]
        # Separate gated (open depends) from ungated
        gated = sorted([a for a in all_with_open if a.get("open_depends")],
                       key=lambda a: a["open"], reverse=True)
        ranked = sorted([a for a in all_with_open if not a.get("open_depends")],
                        key=lambda a: a["open"], reverse=True)
        done = [a for a in areas if a["open"] == 0 and a["complete"] > 0]
        never_examined = [a for a in areas if a["open"] == 0 and a["complete"] == 0]
        lines = [f"**Roadmap next** (project: {project_name})"]
        if focus:
            lines.append(f"Focus: **{focus}**")
        lines.append("")
        if ranked:
            product_ranked = [a for a in ranked if a.get("class") == "product"]
            tooling_ranked = [a for a in ranked if a.get("class") == "tooling"]
            unclassed_ranked = [a for a in ranked if not a.get("class")]
            def _ranked_rows(group):
                rows = []
                for a in group:
                    marker = " ← focus" if a["name"] == focus else ""
                    rows.append(f"  - **{a['name']}** — {a['open']} open task(s){marker}")
                return rows
            if product_ranked:
                lines.append("**Work now — Product:**")
                lines.extend(_ranked_rows(product_ranked))
            if tooling_ranked:
                if product_ranked:
                    lines.append("")
                lines.append("**Work now — Tooling:**")
                lines.extend(_ranked_rows(tooling_ranked))
            if unclassed_ranked:
                if product_ranked or tooling_ranked:
                    lines.append("")
                lines.append("**Work now — Unclassed:**")
                lines.extend(_ranked_rows(unclassed_ranked))
        else:
            lines.append("_No areas have open tasks._")
        if gated:
            lines.append("")
            lines.append("**Gated** (blocked by unfinished dependency):")
            for a in gated:
                gate_names = ", ".join(a["open_depends"])
                marker = " ← focus" if a["name"] == focus else ""
                lines.append(f"  - **{a['name']}** — {a['open']} open task(s), gated by: {gate_names}{marker}")
        if done:
            lines.append("")
            lines.append("**Done:**")
            for a in done:
                date_str = f" (last closed {a['last_closed'][:10]})" if a.get("last_closed") else ""
                lines.append(f"  - {a['name']} — {a['complete']} complete{date_str}")
        if never_examined:
            lines.append("")
            lines.append("**Never examined:**")
            for a in never_examined:
                lines.append(f"  - {a['name']}")
        if unfiled:
            total_open_steps = sum(u.get("open_steps") or 0 for u in unfiled)
            step_note = f" ({total_open_steps} open steps total)" if total_open_steps > 0 else ""
            lines.append("")
            lines.append(
                f"**IN NO AREA:** {len(unfiled)} active task(s){step_note} — assign with `plan_task_set_area`"
            )
        return {
            "success": True,
            "result": {
                "ranked": [{"name": a["name"], "open": a["open"],
                            "why": f"{a['open']} open task(s)"} for a in ranked],
                "gated": [{"name": a["name"], "open": a["open"],
                           "open_depends": a["open_depends"]} for a in gated],
                "done": [{"name": a["name"], "complete": a["complete"],
                          "last_closed": a.get("last_closed")} for a in done],
                "never_examined": [{"name": a["name"]} for a in never_examined],
                "unfiled": [{"name": u["name"]} for u in unfiled],
                "focus": focus,
                "project_name": project_name,
            },
            "display": "\n".join(lines),
        }
    finally:
        conn.close()


def _cmd_roadmap_all(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    project_name = project.get("project_name", "") if project else ""
    try:
        data = plan_ctx.roadmap_all_data(conn, project_id)
        areas = data["areas"]
        unfiled = data["unfiled"]
        if not areas:
            unfiled_lines = []
            if unfiled:
                unfiled_lines = ["", f"**IN NO AREA** ({len(unfiled)} active task(s)):"]
                unfiled_lines += [f"  - `{u['name']}`" for u in unfiled]
            return {"success": False,
                    "error": "no areas defined — use plan_area_new first",
                    "result": {"areas": [], "unfiled": unfiled, "project_name": project_name},
                    "display": "\n".join([
                        f"**Roadmap** (project: {project_name})", "",
                        "No areas defined. Use `plan_area_new` to create areas.",
                    ] + unfiled_lines)}
        def _area_row(a):
            desc_line = (a.get("description_md") or "").split("\n")[0].strip()
            desc = f" — {desc_line}" if desc_line else ""
            if a["open"] == 0 and a["complete"] > 0:
                date_str = f", last closed {a['last_closed'][:10]}" if a.get("last_closed") else ""
                marker = f" **(done{date_str})**"
            elif a["open"] == 0 and a["complete"] == 0:
                marker = " **(never examined)**"
            else:
                marker = ""
            extra = ""
            if a.get("depends"):
                open_dep = a.get("open_depends") or []
                dep_str = ", ".join(
                    f"{d} ({'open' if d in open_dep else 'done'})" for d in a["depends"]
                )
                extra += f"\n      depends: {dep_str}"
            if a.get("watch"):
                extra += f"\n      watch: {', '.join(a['watch'])}"
            return f"  - **{a['name']}**{desc}: {a['open']} open, {a['complete']} complete{marker}{extra}"

        product = [a for a in areas if a.get("class") == "product"]
        tooling = [a for a in areas if a.get("class") == "tooling"]
        unclassed = [a for a in areas if not a.get("class")]
        lines = [f"**Roadmap** (project: {project_name})", ""]
        if product:
            lines.append("**Product**")
            lines.extend(_area_row(a) for a in product)
        if tooling:
            if product:
                lines.append("")
            lines.append("**Tooling**")
            lines.extend(_area_row(a) for a in tooling)
        if unclassed:
            if product or tooling:
                lines.append("")
            lines.append("**Unclassed** (use `plan_area_describe` to set class)")
            lines.extend(_area_row(a) for a in unclassed)
        if unfiled:
            total_open_steps = sum(u.get("open_steps") or 0 for u in unfiled)
            step_note = f" — {total_open_steps} open steps across these tasks" if total_open_steps > 0 else ""
            lines.append("")
            lines.append(f"**IN NO AREA** ({len(unfiled)} active task(s){step_note}):")
            for u in unfiled:
                step_str = f" ({u['open_steps']} open steps)" if u.get("open_steps") else ""
                lines.append(f"  - `{u['name']}`{step_str}")
        return {
            "success": True,
            "result": {"areas": areas, "unfiled": unfiled, "project_name": project_name},
            "display": "\n".join(lines),
        }
    finally:
        conn.close()


def _cmd_task_set_area(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    area = args.get("area")
    if not name:
        return {"success": False, "error": "name is required"}
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, _project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        if area:
            err = plan_ctx.validate_area(conn, area, project_id=project_id)
            if err:
                return {"success": False, "error": err}
        context_id = plan_ctx.resolve_context_id(conn, name, project_id=project_id)
        now = plan_db_mod.utc_now_iso()
        conn.execute("UPDATE contexts SET area = ?, updated_at = ? WHERE id = ?",
                     (area, now, context_id))
        conn.commit()
        action = f"→ {area}" if area else "cleared"
        return {"success": True, "result": {"name": name, "area": area},
                "display": f"Area {action} on `{name}`"}
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
    display = _fmt_step_show(r.get("result", {}))
    display += _fmt_inline_attachments(workspace_dir, task_id=r.get("result", {}).get("id"))
    return _with_display(r, display)


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
    display = _fmt_project(r.get("result", {}))
    display += _fmt_inline_attachments(workspace_dir, project_id=r.get("result", {}).get("id"))
    return _with_display(r, display)


def _cmd_project_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """List all known projects."""
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    try:
        projects = plan_ctx.list_projects(conn)
        lines = ["**Projects**"]
        for p in projects:
            desc = f" — {p['description_md']}" if p.get("description_md") else ""
            lines.append(f"- [{p['id']}] **{p['project_name']}** `{p['absolute_path']}`{desc}")
        if not projects:
            lines.append("No projects found.")
        return {"success": True, "result": {"projects": projects}, "display": "\n".join(lines)}
    finally:
        conn.close()


def _cmd_project_select(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Select active project (web server only, key-gated). Pass project_id=0 to clear."""
    key = args.get("key")
    project_id = args.get("project_id")
    if project_id is None:
        return {"success": False, "error": "project_id is required"}

    cfg_mod = _load_config_mod()

    # project_id=0 (clear override) always requires web key
    if project_id == 0 and not cfg_mod.check_web_key(key):
        return {"success": False, "error": "Invalid or missing web API key."}

    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    try:
        user_id = plan_db_mod.get_or_create_user(conn, plan_db_mod.get_os_user())

        # project_id=0 clears the override
        if project_id == 0:
            plan_ctx.set_active_project_override(conn, user_id, None)
            return {
                "success": True,
                "result": {},
                "display": "Project override cleared. Falling back to workspace auto-detect.",
            }

        # Verify the project exists
        project = plan_ctx.get_project(conn, project_id=project_id)
        if not project:
            return {"success": False, "error": f"Project {project_id} not found."}

        # Self-select exemption: skip key gate when the requested project's path matches
        # the caller's workspace (agent re-selecting its own project, not a cross-project switch).
        project_path = project.get("absolute_path", "")
        is_self_select = (
            Path(workspace_dir).is_dir()
            and bool(project_path)
            and Path(workspace_dir).resolve() == Path(project_path)
        )
        if not is_self_select and not cfg_mod.check_web_key(key):
            return {"success": False, "error": "Invalid or missing web API key."}

        plan_ctx.set_active_project_override(conn, user_id, project_id)
        return {
            "success": True,
            "result": project,
            "display": f"Active project set to **{project['project_name']}** (id:{project_id})",
        }
    finally:
        conn.close()


def _cmd_project_set(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """plan project set [--name <name>] [--description <desc>]"""
    # If web.key is configured AND this is a web request (no real workspace), require the key.
    # Local agents with a real workspace_dir are always allowed to set project metadata.
    cfg_mod = _load_config_mod()
    configured_key = cfg_mod.get_config().get("web", {}).get("key", "")
    is_web_request = configured_key and not Path(workspace_dir).is_dir()
    if is_web_request:
        provided_key = args.get("key")
        if not cfg_mod.check_web_key(provided_key):
            return {"success": False, "error": "Invalid or missing web API key. project_set requires 'key' when web.key is configured."}

    cmd = ["project", "set"]
    if name := args.get("name"):
        cmd.extend(["--name", name])
    if description := args.get("description"):
        cmd.extend(["--description", description])
    r = _run_plan_cmd(workspace_dir, cmd)
    return _with_display(r, _fmt_project(r.get("result", {})))


def _cmd_project_relink(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Relink an existing project record to this workspace path."""
    selectors = [args.get("project_id") is not None, args.get("old_path") is not None, args.get("name") is not None]
    if sum(selectors) != 1:
        return {"success": False, "error": "Provide exactly one of project_id, old_path, or name."}

    cmd = ["project", "relink"]
    if args.get("project_id") is not None:
        cmd.extend(["--project-id", str(args["project_id"])])
    if old_path := args.get("old_path"):
        cmd.extend(["--old-path", old_path])
    if name := args.get("name"):
        cmd.extend(["--name", name])
    if new_path := args.get("new_path"):
        cmd.extend(["--new-path", new_path])
    if new_name := args.get("new_name"):
        cmd.extend(["--new-name", new_name])

    r = _run_plan_cmd(workspace_dir, cmd)
    display = "Relinked project to current workspace.\n\n" + _fmt_project(r.get("result", {}))
    return _with_display(r, display)


def _cmd_project_purge(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Permanently delete a project and all its data from the database."""
    if not args.get("confirm"):
        return {"success": False, "error": "confirm=true is required to purge a project."}

    force = bool(args.get("force", False))
    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    try:
        # Resolve which project to purge
        selectors = [args.get("project_id") is not None, args.get("name") is not None]
        if sum(selectors) > 1:
            return {"success": False, "error": "Provide at most one of project_id or name (omit both to purge current workspace project)."}

        if args.get("project_id") is not None:
            project = plan_ctx.get_project(conn, project_id=int(args["project_id"]))
            if not project:
                return {"success": False, "error": f"Project id {args['project_id']} not found."}
            project_id = project["id"]
        elif args.get("name") is not None:
            rows = conn.execute(
                "SELECT id FROM project WHERE project_name = ?", (args["name"],)
            ).fetchall()
            if not rows:
                return {"success": False, "error": f"Project named '{args['name']}' not found."}
            if len(rows) > 1:
                ids = ", ".join(str(r["id"] if hasattr(r, '__getitem__') else r[0]) for r in rows)
                return {"success": False, "error": f"Project name '{args['name']}' is ambiguous (ids: {ids}). Use project_id instead."}
            project_id = rows[0][0]
        else:
            _, project, _is_new, _user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))

        # Export before deletion — data is still intact at this point
        from datetime import datetime
        export_path = None
        try:
            export_data = plan_ctx.get_project_report_data(conn, project_id=project_id)
            export_md = _fmt_project_report(export_data)
            proj_row = plan_ctx.get_project(conn, project_id=project_id)
            safe_name = (proj_row or {}).get("project_name", "project").replace(" ", "-")
            date_str = datetime.now().strftime("%y%m%d")
            filename = f"project_export_{safe_name}_{date_str}.md"
            ws_path = Path((proj_row or {}).get("absolute_path", ""))
            write_dir = ws_path if ws_path.is_dir() else _pkg_path()
            export_path = write_dir / filename
            export_path.write_text(export_md, encoding="utf-8")
        except Exception:
            export_path = None

        try:
            result = plan_ctx.purge_project(conn, project_id, force=force)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        p = result["project"]
        d = result["deleted"]
        lines = [
            f"**Purged**: {p['project_name']} (`{p['absolute_path']}`)",
            f"  {d.get('contexts', 0)} tasks, {d.get('tasks', 0)} steps, "
            f"{d.get('context_notes', 0) + d.get('task_notes', 0)} notes, "
            f"{d.get('attachments', 0)} attachments, "
            f"{d.get('changelog', 0)} changelog entries removed.",
        ]
        if export_path:
            lines.append(f"  Export saved to `{export_path}`")
            result["export_path"] = str(export_path)
        return {"success": True, "result": result, "display": "\n".join(lines)}
    finally:
        conn.close()


# ── File attachment command handlers ──

def _cmd_file_attach(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Attach a workspace-relative file to a project, task, or step."""
    file_path = args.get("file_path")
    if not file_path:
        return {"success": False, "error": "file_path is required."}

    scope = args.get("scope", "task")
    label = args.get("label")
    kind = args.get("kind", "ref")

    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    try:
        context_id = None
        task_id = None
        pid = None

        if scope == "project":
            pid = project_id
        elif scope == "step":
            context_id = plan_ctx.resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            state = conn.execute(
                "SELECT active_task_id FROM context_state WHERE context_id = ?", (context_id,)
            ).fetchone()
            if not state or not state["active_task_id"]:
                return {"success": False, "error": "No active step to attach to."}
            task_id = state["active_task_id"]
            context_id = None
        else:
            context_id = plan_ctx.resolve_active_context_id(conn, user_id=user_id, project_id=project_id)

        result = plan_ctx.attach_file(
            conn, file_path, workspace_dir,
            label=label, kind=kind,
            project_id=pid, context_id=context_id, task_id=task_id,
        )
        scope_label = {"project": "project", "step": "step", "task": "task"}[scope]
        display = f"Attached `{file_path}` to {scope_label} (id:{result['id']})"
        if label:
            display += f" — {label}"
        return {"success": True, "result": result, "display": display}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_file_detach(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """Remove a file attachment by ID."""
    attachment_id = args.get("id")
    if attachment_id is None:
        return {"success": False, "error": "id is required."}

    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    db_path = plan_db_mod.default_db_path()
    conn = plan_db_mod.connect(db_path)
    plan_db_mod.ensure_schema(conn)
    try:
        plan_ctx.detach_file(conn, int(attachment_id))
        return {"success": True, "result": {}, "display": f"Attachment {attachment_id} removed."}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _cmd_file_list(workspace_dir: str, args: dict[str, Any]) -> dict[str, Any]:
    """List file attachments for a project, task, or step."""
    scope = args.get("scope", "task")

    pkg_path = _pkg_path()
    plan_db_mod, plan_ctx = _load_pkg(pkg_path)
    conn, project, _is_new, user_id, project_id = _open_db(plan_db_mod, plan_ctx, Path(workspace_dir))
    cfg_mod = _load_config_mod()
    max_lines = cfg_mod.get_config().get("attachments", {}).get("inline_lines", 100)
    try:
        context_id = None
        task_id = None
        pid = None

        if scope == "project":
            pid = project_id
        elif scope == "step":
            ctx_id = plan_ctx.resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            state = conn.execute(
                "SELECT active_task_id FROM context_state WHERE context_id = ?", (ctx_id,)
            ).fetchone()
            if not state or not state["active_task_id"]:
                return {"success": False, "error": "No active step."}
            task_id = state["active_task_id"]
        else:
            context_id = plan_ctx.resolve_active_context_id(conn, user_id=user_id, project_id=project_id)

        attachments = plan_ctx.list_attachments(
            conn, workspace_dir,
            project_id=pid, context_id=context_id, task_id=task_id,
        )

        lines = [f"**Attachments** ({scope})"]
        for a in attachments:
            broken_tag = " ⚠ broken" if a["broken"] else ""
            label_tag = f" — {a['label']}" if a.get("label") else ""
            lines.append(f"\n[{a['id']}] `{a['file_path']}` ({a['kind']}){label_tag}{broken_tag}")
            if not a["broken"]:
                content_data = plan_ctx.read_attachment_content(a["file_path"], workspace_dir, max_lines)
                lines.append(f"```\n{content_data['content']}\n```")
                if content_data["truncated"]:
                    lines.append(f"*({content_data['line_count']} lines total — truncated at {max_lines})*")
        if not attachments:
            lines.append("No attachments.")

        return {"success": True, "result": {"attachments": attachments}, "display": "\n".join(lines)}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


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
