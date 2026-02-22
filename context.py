"""Context operations for V2 (DB-backed)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Optional

from . import db

STATUS_PLANNED = "planned"
STATUS_STARTED = "started"
STATUS_COMPLETE = "complete"
STATUS_DELETED = "deleted"


@dataclass(frozen=True)
class TaskInput:
    title: str
    description_md: Optional[str] = None
    parent_id: Optional[int] = None
    sort_index: Optional[int] = None
    sub_index: Optional[int] = None


def resolve_context_id(conn, context_ref: str | int, project_id: int | None = None) -> int:
    """Resolve a context reference to an integer ID, optionally scoped to a project."""
    if isinstance(context_ref, int):
        row = conn.execute(
            "SELECT id FROM contexts WHERE id = ?",
            (context_ref,),
        ).fetchone()
        if row:
            return int(row["id"])
        raise ValueError(f"Context id {context_ref} not found.")

    try:
        context_id = int(str(context_ref))
    except ValueError:
        context_id = None

    if context_id is not None:
        row = conn.execute(
            "SELECT id FROM contexts WHERE id = ?",
            (context_id,),
        ).fetchone()
        if row:
            return int(row["id"])

    # Name lookup: scope to project if provided.
    if project_id is not None:
        row = conn.execute(
            "SELECT id FROM contexts WHERE name = ? AND project_id = ?",
            (str(context_ref), project_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM contexts WHERE name = ?",
            (str(context_ref),),
        ).fetchone()
    if not row:
        raise ValueError(f"Context '{context_ref}' not found.")
    return int(row["id"])


def resolve_active_context_id(conn, user_id: int | None = None, project_id: int | None = None) -> int:
    if user_id is not None:
        context_id = db.get_active_context_id_for_user(conn, user_id, project_id=project_id)
    else:
        context_id = db.get_active_context_id(conn)
    if context_id is None:
        raise ValueError("No active context is set.")
    return int(context_id)


def _next_step_payload(
    action: str,
    reason: str,
    allowed: list[str],
    target: Optional[dict] = None,
) -> str:
    payload = {
        "action": action,
        "reason": reason,
        "allowed": allowed,
        "target": target or {},
    }
    return json.dumps(payload)


def _set_next_step_for_active_task(
    conn,
    context_id: int,
    active_task_id: int,
    active_task_number: int,
    now: str,
) -> None:
    next_step = _next_step_payload(
        action="task.done",
        reason="Active task in progress.",
        allowed=[
            "task.done",
            "task.switch",
            "task.new",
            "task.show",
            "task.status",
            "task.logs",
            "task.list",
            "plan.show",
            "plan.status",
            "plan.logs",
            "context.show",
            "context.status",
            "context.logs",
            "context.list",
            "context.switch",
        ],
        target={"task_number": active_task_number},
    )
    conn.execute(
        "UPDATE context_state SET next_step = ?, updated_at = ? WHERE context_id = ?",
        (next_step, now, context_id),
    )


def _set_next_step_for_new_task(conn, context_id: int, now: str) -> None:
    next_step = _next_step_payload(
        action="task.new",
        reason="No active task is set.",
        allowed=[
            "task.new",
            "plan.show",
            "plan.status",
            "context.show",
            "context.status",
            "context.logs",
            "context.list",
            "context.switch",
        ],
    )
    conn.execute(
        "UPDATE context_state SET next_step = ?, updated_at = ? WHERE context_id = ?",
        (next_step, now, context_id),
    )


def create_task(
    conn,
    context_ref: str | int | None,
    title: str,
    description_md: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_index: Optional[int] = None,
    sub_index: Optional[int] = None,
    actor: Optional[str] = None,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> tuple[int, int]:
    """Create a new task for a context."""
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        context_id = (
            resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            if context_ref is None
            else resolve_context_id(conn, context_ref, project_id=project_id)
        )

        if parent_id is not None and sort_index is not None:
            raise ValueError("sort_index is only valid for top-level tasks.")

        if parent_id is not None:
            parent = conn.execute(
                "SELECT id FROM tasks WHERE id = ? AND context_id = ?",
                (parent_id, context_id),
            ).fetchone()
            if not parent:
                raise ValueError(
                    f"Parent task {parent_id} not found in context {context_id}."
                )

        if parent_id is None and sort_index is None:
            row = conn.execute(
                "SELECT MAX(sort_index) AS max_sort FROM tasks "
                "WHERE context_id = ? AND parent_id IS NULL",
                (context_id,),
            ).fetchone()
            max_sort = row["max_sort"] if row else None
            sort_index = (int(max_sort) if max_sort is not None else 0) + 1

        if sub_index is None:
            row = conn.execute(
                "SELECT MAX(sub_index) AS max_sub FROM tasks "
                "WHERE context_id = ? AND is_deleted = 0",
                (context_id,),
            ).fetchone()
            max_sub = row["max_sub"] if row else None
            sub_index = (int(max_sub) if max_sub is not None else 0) + 1

        row = conn.execute(
            "SELECT MAX(task_number) AS max_num FROM tasks WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        max_num = row["max_num"] if row else None
        task_number = (int(max_num) if max_num is not None else 0) + 1

        cur = conn.execute(
            "INSERT INTO tasks (context_id, task_number, title, description_md, status, is_deleted, parent_id, "
            "sort_index, sub_index, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, 'planned', 0, ?, ?, ?, ?, ?, NULL)",
            (
                context_id,
                task_number,
                title,
                description_md,
                parent_id,
                sort_index,
                sub_index,
                now,
                now,
            ),
        )
        task_id = int(cur.lastrowid)

        # Make the new task active (only one active task per context).
        active_row = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        active_task_id = active_row["active_task_id"] if active_row else None
        if active_task_id:
            conn.execute(
                "UPDATE tasks SET status = 'planned', updated_at = ? WHERE id = ?",
                (now, active_task_id),
            )

        conn.execute(
            "UPDATE tasks SET status = 'started', updated_at = ? WHERE id = ?",
            (now, task_id),
        )

        conn.execute(
            "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
            "last_event = ?, updated_at = ? WHERE context_id = ?",
            (task_id, task_id, "Task Started", now, context_id),
        )
        _set_next_step_for_active_task(conn, context_id, task_id, task_number, now)

        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, task_id, "Task Created", title, now, actor),
        )
        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, task_id, "Task Started", None, now, actor),
        )

        conn.commit()
        return task_id, task_number
    except Exception:
        conn.rollback()
        raise


def create_context(
    conn,
    name: str,
    tasks: Iterable[TaskInput] | None = None,
    description_md: Optional[str] = None,
    next_step: Optional[str] = None,
    status_label: str = "Created",
    set_active: bool = False,
    start_task_index: Optional[int] = None,
    auto_complete_first_task: bool = False,
    actor: Optional[str] = None,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> int:
    """Create a new context and optional initial tasks.

    This is intentionally minimal and DB-backed. No filesystem writes.
    """
    tasks_list = list(tasks or [])
    now = db.utc_now_iso()

    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO contexts (name, status, description_md, user_id, project_id, created_at, updated_at) "
            "VALUES (?, 'active', ?, ?, ?, ?, ?)",
            (name, description_md, user_id, project_id, now, now),
        )
        context_id = int(cur.lastrowid)

        conn.execute(
            "INSERT INTO context_state (context_id, active_task_id, last_task_id, next_step, "
            "status_label, last_event, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                context_id,
                None,
                None,
                next_step,
                status_label,
                "Context Created",
                now,
            ),
        )

        task_ids = _insert_tasks(conn, context_id, tasks_list, now)
        last_task_id = task_ids[-1] if task_ids else None

        if last_task_id:
            conn.execute(
                "UPDATE context_state SET last_task_id = ? WHERE context_id = ?",
                (last_task_id, context_id),
            )

        if auto_complete_first_task and task_ids:
            first_id = task_ids[0]
            conn.execute(
                "UPDATE tasks SET status = 'complete', completed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, first_id),
            )
            conn.execute(
                "UPDATE context_state SET last_task_id = ? WHERE context_id = ?",
                (first_id, context_id),
            )

        active_id = None
        if start_task_index is not None:
            if start_task_index < 1 or start_task_index > len(task_ids):
                raise ValueError("start_task_index is out of range for initial tasks")
            active_id = task_ids[start_task_index - 1]
        elif set_active and task_ids:
            active_id = task_ids[0]

        if active_id is not None:
            conn.execute(
                "UPDATE tasks SET status = 'started', updated_at = ? WHERE id = ?",
                (now, active_id),
            )
            conn.execute(
                "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
                "last_event = ?, updated_at = ? WHERE context_id = ?",
                (active_id, active_id, "Task Started", now, context_id),
            )
            conn.execute(
                "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (context_id, active_id, "Task Started", None, now, actor),
            )
            active_task_number = conn.execute(
                "SELECT task_number FROM tasks WHERE id = ?",
                (active_id,),
            ).fetchone()["task_number"]
            _set_next_step_for_active_task(
                conn, context_id, active_id, int(active_task_number), now
            )
        else:
            _set_next_step_for_new_task(conn, context_id, now)

        if set_active:
            if user_id is not None and project_id is not None:
                db.upsert_user_state(conn, user_id, project_id, context_id)
            db.upsert_global_state(conn, context_id)

        conn.execute(
            "INSERT INTO changelog (context_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?)",
            (context_id, "Context Created", None, now, actor),
        )

        conn.commit()
        return context_id
    except Exception:
        conn.rollback()
        raise


def switch_context(
    conn,
    context_ref: str | int,
    actor: Optional[str] = None,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> int:
    """Set the active context."""
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        context_id = resolve_context_id(conn, context_ref, project_id=project_id)

        # Check if target is completed — gate on config
        ctx_status_row = conn.execute(
            "SELECT status FROM contexts WHERE id = ?", (context_id,),
        ).fetchone()
        if ctx_status_row and ctx_status_row["status"] == "completed":
            from . import config
            cfg = config.get_config()
            if not cfg.get("workflow", {}).get("allow_reopen_completed", False):
                raise ValueError(
                    f"Cannot switch to completed task. "
                    f"Set workflow.allow_reopen_completed to true in config to allow this."
                )
            conn.execute(
                "UPDATE contexts SET status = 'active', updated_at = ? WHERE id = ?",
                (now, context_id),
            )

        if user_id is not None and project_id is not None:
            db.upsert_user_state(conn, user_id, project_id, context_id)
        db.upsert_global_state(conn, context_id)
        # Ensure the target context has an active task.
        state_row = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        active_task_id = state_row["active_task_id"] if state_row else None
        if not active_task_id:
            task_row = conn.execute(
                "SELECT id FROM tasks WHERE context_id = ? AND status = 'planned' "
                "AND is_deleted = 0 ORDER BY task_number LIMIT 1",
                (context_id,),
            ).fetchone()
            if not task_row:
                task_row = conn.execute(
                    "SELECT id FROM tasks WHERE context_id = ? AND is_deleted = 0 "
                    "ORDER BY task_number DESC LIMIT 1",
                    (context_id,),
                ).fetchone()
            if task_row:
                active_task_id = int(task_row["id"])
            else:
                task_id, _task_number = create_task(
                    conn,
                    context_ref=context_id,
                    title="New task",
                    description_md=None,
                    actor=actor,
                )
                active_task_id = task_id

            if active_task_id:
                conn.execute(
                    "UPDATE tasks SET status = 'started', updated_at = ? WHERE id = ?",
                    (now, active_task_id),
                )
                conn.execute(
                    "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
                    "last_event = ?, updated_at = ? WHERE context_id = ?",
                    (active_task_id, active_task_id, "Task Started", now, context_id),
                )
                active_task_number = conn.execute(
                    "SELECT task_number FROM tasks WHERE id = ?",
                    (active_task_id,),
                ).fetchone()["task_number"]
                _set_next_step_for_active_task(
                    conn, context_id, active_task_id, int(active_task_number), now
                )
                conn.execute(
                    "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (context_id, active_task_id, "Task Started", None, now, actor),
                )
        conn.execute(
            "INSERT INTO changelog (context_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?)",
            (context_id, "Context Switched", None, now, actor),
        )
        conn.commit()
        return context_id
    except Exception:
        conn.rollback()
        raise

def switch_task(
    conn,
    task_number: int,
    context_ref: str | int | None = None,
    actor: Optional[str] = None,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> int:
    """Switch the active task in a context by task number."""
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        context_id = (
            resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            if context_ref is None
            else resolve_context_id(conn, context_ref, project_id=project_id)
        )
        task_row = conn.execute(
            "SELECT id, is_deleted FROM tasks WHERE context_id = ? AND task_number = ?",
            (context_id, task_number),
        ).fetchone()
        if not task_row:
            raise ValueError(f"Task {task_number} not found in context {context_id}.")
        if task_row["is_deleted"] == 1:
            raise ValueError(f"Task {task_number} is deleted and cannot be activated.")
        target_task_id = int(task_row["id"])

        _check_goal_plan_required(conn, context_id)

        # Do not mutate other task statuses. Only set the active task to started.
        conn.execute(
            "UPDATE tasks SET status = 'started', updated_at = ? WHERE id = ?",
            (now, target_task_id),
        )
        conn.execute(
            "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
            "last_event = ?, updated_at = ? WHERE context_id = ?",
            (target_task_id, target_task_id, "Task Switched", now, context_id),
        )
        _set_next_step_for_active_task(
            conn, context_id, target_task_id, task_number, now
        )
        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, target_task_id, "Task Switched", None, now, actor),
        )

        conn.commit()
        return target_task_id
    except Exception:
        conn.rollback()
        raise

def _resolve_task_id_by_number(
    conn,
    context_id: int,
    task_number: int,
    allow_deleted: bool = False,
) -> int:
    row = conn.execute(
        "SELECT id, is_deleted FROM tasks WHERE context_id = ? AND task_number = ?",
        (context_id, task_number),
    ).fetchone()
    if not row:
        raise ValueError(f"Task {task_number} not found in context {context_id}.")
    if row["is_deleted"] == 1 and not allow_deleted:
        raise ValueError(f"Task {task_number} is deleted and cannot be modified.")
    return int(row["id"])


def _resolve_step_by_subindex(
    conn,
    context_id: int,
    sub_index: int,
) -> tuple[int, int]:
    """Resolve a step's sub_index to (task_id, task_number) for non-deleted steps."""
    row = conn.execute(
        "SELECT id, task_number FROM tasks "
        "WHERE context_id = ? AND sub_index = ? AND is_deleted = 0",
        (context_id, sub_index),
    ).fetchone()
    if not row:
        raise ValueError(f"Step {sub_index} not found in context {context_id}.")
    return int(row["id"]), int(row["task_number"])


def _renumber_steps(conn, context_id: int) -> None:
    """Renumber non-deleted steps in a context sequentially from 1.

    Uses two passes to avoid unique index conflicts:
    1. NULL all sub_index for non-deleted rows in this context
    2. Assign 1, 2, 3... ordered by current task_number
    """
    conn.execute(
        "UPDATE tasks SET sub_index = NULL "
        "WHERE context_id = ? AND is_deleted = 0",
        (context_id,),
    )
    rows = conn.execute(
        "SELECT id FROM tasks "
        "WHERE context_id = ? AND is_deleted = 0 "
        "ORDER BY task_number",
        (context_id,),
    ).fetchall()
    for i, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE tasks SET sub_index = ? WHERE id = ?",
            (i, row["id"]),
        )


def reorder_steps(conn, order: list[int], user_id=None, project_id=None) -> list[dict]:
    """Reorder steps by reassigning sub_index values.

    Args:
        order: List of current sub_index values in desired new order.
               Must contain ALL non-deleted step sub_index values exactly once.

    Returns:
        List of dicts with old_index, new_index, title for each step.
    """
    context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)

    # Get all non-deleted steps for this context.
    rows = conn.execute(
        "SELECT id, sub_index, title FROM tasks "
        "WHERE context_id = ? AND is_deleted = 0 "
        "ORDER BY sub_index",
        (context_id,),
    ).fetchall()

    existing = {int(r["sub_index"]): r for r in rows}

    # Validate: order must contain exactly the same set of sub_index values.
    order_set = set(order)
    existing_set = set(existing.keys())
    if order_set != existing_set:
        missing = existing_set - order_set
        extra = order_set - existing_set
        parts = []
        if missing:
            parts.append(f"missing: {sorted(missing)}")
        if extra:
            parts.append(f"unknown: {sorted(extra)}")
        raise ValueError(
            f"Order must contain all {len(existing)} step numbers exactly once. {'; '.join(parts)}"
        )

    if len(order) != len(order_set):
        raise ValueError("Order contains duplicate step numbers.")

    # Two-pass reassignment to avoid unique index conflicts.
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE tasks SET sub_index = NULL "
            "WHERE context_id = ? AND is_deleted = 0",
            (context_id,),
        )
        mapping = []
        for new_idx, old_idx in enumerate(order, start=1):
            row = existing[old_idx]
            conn.execute(
                "UPDATE tasks SET sub_index = ? WHERE id = ?",
                (new_idx, row["id"]),
            )
            mapping.append({
                "old_index": old_idx,
                "new_index": new_idx,
                "title": row["title"],
            })
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return mapping


VALID_NOTE_KINDS = ("goal", "plan", "note")


def _check_goal_plan_required(conn, context_id: int) -> None:
    """Raise if config requires goal+plan notes and they're missing real content."""
    from . import config
    get_config = config.get_config
    cfg = get_config()
    if not cfg.get("workflow", {}).get("require_goal_and_plan", True):
        return
    rows = conn.execute(
        "SELECT kind, note_md FROM context_notes WHERE context_id = ? AND kind IN ('goal', 'plan')",
        (context_id,),
    ).fetchall()
    kinds_present = set()
    for r in rows:
        # Migration placeholders don't count
        if not r["note_md"].startswith("(migrated"):
            kinds_present.add(r["kind"])
    missing = []
    if "goal" not in kinds_present:
        missing.append("goal")
    if "plan" not in kinds_present:
        missing.append("plan")
    if missing:
        raise ValueError(
            f"Cannot progress step: task is missing {' and '.join(missing)} notes. "
            f"Add them with plan_task_notes (kind='{missing[0]}')."
        )


def list_task_notes(
    conn,
    task_number: int | None = None,
    context_ref: str | int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    kind: str | None = None,
) -> list[dict]:
    if context_ref is None:
        context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    else:
        context_id = resolve_context_id(conn, context_ref)

    if task_number is None:
        state_row = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        if not state_row or not state_row["active_task_id"]:
            return []
        task_id = int(state_row["active_task_id"])
    else:
        task_id = _resolve_task_id_by_number(conn, context_id, task_number, allow_deleted=False)

    if kind:
        rows = conn.execute(
            "SELECT id, note_md, created_at, kind FROM task_notes WHERE task_id = ? AND kind = ? ORDER BY id",
            (task_id, kind),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, note_md, created_at, kind FROM task_notes WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    return [{"id": row["id"], "note": row["note_md"], "created_at": row["created_at"], "kind": row["kind"]} for row in rows]


def add_task_note(
    conn,
    note_md: str,
    task_number: int | None = None,
    context_ref: str | int | None = None,
    actor: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    kind: str = "note",
    note_id: int | None = None,
) -> int:
    if kind not in VALID_NOTE_KINDS:
        raise ValueError(f"Invalid note kind '{kind}'. Must be one of: {', '.join(VALID_NOTE_KINDS)}")
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        if context_ref is None:
            context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
        else:
            context_id = resolve_context_id(conn, context_ref)

        if task_number is None:
            state_row = conn.execute(
                "SELECT active_task_id FROM context_state WHERE context_id = ?",
                (context_id,),
            ).fetchone()
            if not state_row or not state_row["active_task_id"]:
                raise ValueError("No active task is set for this context.")
            task_id = int(state_row["active_task_id"])
        else:
            task_id = _resolve_task_id_by_number(conn, context_id, task_number, allow_deleted=False)

        # Upsert: if note_id provided, update existing; otherwise insert new
        if note_id is not None:
            conn.execute(
                "UPDATE task_notes SET note_md = ?, created_at = ? WHERE id = ?",
                (note_md, now, note_id),
            )
            result_id = note_id
            changelog_action = "Task Note Updated"
        else:
            cur = conn.execute(
                "INSERT INTO task_notes (task_id, note_md, created_at, kind) VALUES (?, ?, ?, ?)",
                (task_id, note_md, now, kind),
            )
            result_id = int(cur.lastrowid)
            changelog_action = "Task Note Added"

        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, task_id, changelog_action, note_md, now, actor),
        )

        conn.commit()
        return result_id
    except Exception:
        conn.rollback()
        raise


def delete_task_note(conn, note_id: int) -> None:
    """Delete a task note by ID."""
    conn.execute("BEGIN")
    try:
        row = conn.execute("SELECT task_id, note_md FROM task_notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            raise ValueError(f"Task note with id {note_id} not found.")
        # Look up context_id from the task
        task_row = conn.execute("SELECT context_id FROM tasks WHERE id = ?", (row["task_id"],)).fetchone()
        now = db.utc_now_iso()
        conn.execute("DELETE FROM task_notes WHERE id = ?", (note_id,))
        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_row["context_id"] if task_row else None, row["task_id"], "Task Note Deleted", row["note_md"][:100], now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def list_context_notes(
    conn,
    context_ref: str | int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    kind: str | None = None,
) -> list[dict]:
    if context_ref is None:
        context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    else:
        context_id = resolve_context_id(conn, context_ref)

    if kind:
        rows = conn.execute(
            "SELECT id, note_md, created_at, actor, kind FROM context_notes WHERE context_id = ? AND kind = ? ORDER BY id",
            (context_id, kind),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, note_md, created_at, actor, kind FROM context_notes WHERE context_id = ? ORDER BY id",
            (context_id,),
        ).fetchall()
    return [{"id": row["id"], "note": row["note_md"], "created_at": row["created_at"], "actor": row["actor"], "kind": row["kind"]} for row in rows]


def add_context_note(
    conn,
    note_md: str,
    context_ref: str | int | None = None,
    actor: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    kind: str = "note",
    note_id: int | None = None,
) -> int:
    if kind not in VALID_NOTE_KINDS:
        raise ValueError(f"Invalid note kind '{kind}'. Must be one of: {', '.join(VALID_NOTE_KINDS)}")
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        if context_ref is None:
            context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
        else:
            context_id = resolve_context_id(conn, context_ref)

        # Upsert logic: for goal/plan kinds, replace existing by (context_id, kind).
        # For note kind, update by ID if provided.
        existing_id = None
        if kind in ("goal", "plan"):
            row = conn.execute(
                "SELECT id FROM context_notes WHERE context_id = ? AND kind = ?",
                (context_id, kind),
            ).fetchone()
            if row:
                existing_id = row[0]
        elif note_id is not None:
            existing_id = note_id

        if existing_id is not None:
            conn.execute(
                "UPDATE context_notes SET note_md = ?, created_at = ?, actor = ? WHERE id = ?",
                (note_md, now, actor, existing_id),
            )
            result_id = existing_id
            changelog_action = "Context Note Updated"
        else:
            cur = conn.execute(
                "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) VALUES (?, ?, ?, ?, ?)",
                (context_id, note_md, now, actor, kind),
            )
            result_id = int(cur.lastrowid)
            changelog_action = "Context Note Added"

        conn.execute(
            "INSERT INTO changelog (context_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?)",
            (context_id, changelog_action, note_md, now, actor),
        )

        conn.commit()
        return result_id
    except Exception:
        conn.rollback()
        raise


def delete_context_note(conn, note_id: int) -> None:
    """Delete a context note by ID."""
    conn.execute("BEGIN")
    try:
        row = conn.execute("SELECT context_id, note_md FROM context_notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            raise ValueError(f"Context note with id {note_id} not found.")
        now = db.utc_now_iso()
        conn.execute("DELETE FROM context_notes WHERE id = ?", (note_id,))
        conn.execute(
            "INSERT INTO changelog (context_id, action, details_md, created_at) "
            "VALUES (?, ?, ?, ?)",
            (row["context_id"], "Context Note Deleted", row["note_md"][:100], now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_project(conn, project_id: int | None = None, absolute_path: str | None = None) -> dict | None:
    """Get project metadata by id or path."""
    if project_id is not None:
        row = conn.execute(
            "SELECT id, project_name, absolute_path, description_md, created_at FROM project WHERE id = ?",
            (project_id,),
        ).fetchone()
    elif absolute_path is not None:
        row = conn.execute(
            "SELECT id, project_name, absolute_path, description_md, created_at FROM project WHERE absolute_path = ?",
            (absolute_path,),
        ).fetchone()
    else:
        # Legacy fallback: get first project
        row = conn.execute(
            "SELECT id, project_name, absolute_path, description_md, created_at FROM project ORDER BY id LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return dict(row)


def set_project(conn, project_id: int | None = None, project_name: str | None = None,
                absolute_path: str | None = None, description_md: str | None = None) -> dict:
    """Create or update a project row."""
    now = db.utc_now_iso()

    if project_id is not None:
        existing = get_project(conn, project_id=project_id)
    elif absolute_path is not None:
        existing = get_project(conn, absolute_path=absolute_path)
    else:
        existing = None

    if existing is None:
        cur = conn.execute(
            "INSERT INTO project (project_name, absolute_path, description_md, created_at) "
            "VALUES (?, ?, ?, ?)",
            (project_name or "unnamed", absolute_path or "", description_md, now),
        )
        return get_project(conn, project_id=cur.lastrowid)
    else:
        updates, params = [], []
        if project_name is not None:
            updates.append("project_name = ?")
            params.append(project_name)
        if absolute_path is not None:
            updates.append("absolute_path = ?")
            params.append(absolute_path)
        if description_md is not None:
            updates.append("description_md = ?")
            params.append(description_md)
        if updates:
            params.append(existing["id"])
            conn.execute(
                f"UPDATE project SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return get_project(conn, project_id=existing["id"])


def ensure_project(conn, cwd: str) -> tuple[dict, bool]:
    """Ensure project row exists for this CWD, auto-populating if needed.

    Returns (project_dict, is_new) tuple.
    """
    existing = get_project(conn, absolute_path=cwd)
    if existing is not None:
        return existing, False
    from pathlib import Path
    name = Path(cwd).name or "unnamed"
    project = set_project(conn, project_name=name, absolute_path=cwd)
    return project, True


def delete_task(
    conn,
    task_number: int,
    context_ref: str | int | None = None,
    actor: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> int:
    """Soft-delete a task by setting is_deleted = 1."""
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        context_id = (
            resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            if context_ref is None
            else resolve_context_id(conn, context_ref, project_id=project_id)
        )
        row = conn.execute(
            "SELECT id, is_deleted FROM tasks WHERE context_id = ? AND task_number = ?",
            (context_id, task_number),
        ).fetchone()
        if not row:
            raise ValueError(f"Task {task_number} not found in context {context_id}.")
        task_id = int(row["id"])
        if row["is_deleted"] == 1:
            raise ValueError(f"Task {task_number} is already deleted.")

        conn.execute(
            "UPDATE tasks SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (now, task_id),
        )

        state_row = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        active_task_id = state_row["active_task_id"] if state_row else None

        if active_task_id == task_id:
            replacement = conn.execute(
                "SELECT id, task_number FROM tasks WHERE context_id = ? "
                "AND status != ? ORDER BY task_number LIMIT 1",
                (context_id, STATUS_DELETED),
            ).fetchone()
            if replacement:
                new_active_id = int(replacement["id"])
                new_active_number = int(replacement["task_number"])
                conn.execute(
                    "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
                    "last_event = ?, updated_at = ? WHERE context_id = ?",
                    (new_active_id, new_active_id, "Task Switched", now, context_id),
                )
                _set_next_step_for_active_task(
                    conn, context_id, new_active_id, new_active_number, now
                )
            else:
                conn.execute(
                    "UPDATE context_state SET active_task_id = NULL, last_task_id = ?, "
                    "last_event = ?, updated_at = ? WHERE context_id = ?",
                    (task_id, "Task Deleted", now, context_id),
                )
                _set_next_step_for_new_task(conn, context_id, now)
        else:
            conn.execute(
                "UPDATE context_state SET last_task_id = ?, last_event = ?, updated_at = ? "
                "WHERE context_id = ?",
                (task_id, "Task Deleted", now, context_id),
            )

        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, task_id, "Task Deleted", None, now, actor),
        )

        conn.commit()
        return task_id
    except Exception:
        conn.rollback()
        raise


def complete_task(
    conn,
    task_number: int,
    context_ref: str | int | None = None,
    actor: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> int:
    """Mark a task as complete (context-scoped task number)."""
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        context_id = (
            resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
            if context_ref is None
            else resolve_context_id(conn, context_ref, project_id=project_id)
        )
        task_row = conn.execute(
            "SELECT id, is_deleted FROM tasks WHERE context_id = ? AND task_number = ?",
            (context_id, task_number),
        ).fetchone()
        if not task_row:
            raise ValueError(f"Task {task_number} not found in context {context_id}.")

        if task_row["is_deleted"] == 1:
            raise ValueError(f"Task {task_number} is deleted and cannot be completed.")
        task_id = int(task_row["id"])

        _check_goal_plan_required(conn, context_id)

        conn.execute(
            "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (STATUS_COMPLETE, now, now, task_id),
        )

        conn.execute(
            "UPDATE context_state SET last_task_id = ?, last_event = ?, updated_at = ? "
            "WHERE context_id = ?",
            (task_id, "Task Completed", now, context_id),
        )

        conn.execute(
            "INSERT INTO changelog (context_id, task_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (context_id, task_id, "Task Completed", None, now, actor),
        )

        conn.commit()
        return task_id
    except Exception:
        conn.rollback()
        raise


def get_task_summary(
    conn,
    task_number: int | None = None,
    context_ref: str | int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    if context_ref is None:
        context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    else:
        context_id = resolve_context_id(conn, context_ref)

    if task_number is None:
        state_row = conn.execute(
            "SELECT active_task_id FROM context_state WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        if not state_row or not state_row["active_task_id"]:
            raise ValueError("No active step is set.")
        active_id = int(state_row["active_task_id"])
        row = conn.execute(
            "SELECT id, context_id, task_number, title, description_md, status, is_deleted, parent_id, "
            "sort_index, sub_index, created_at, updated_at, completed_at "
            "FROM tasks WHERE id = ?",
            (active_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, context_id, task_number, title, description_md, status, is_deleted, parent_id, "
            "sort_index, sub_index, created_at, updated_at, completed_at "
            "FROM tasks WHERE context_id = ? AND task_number = ?",
            (context_id, task_number),
        ).fetchone()
    if not row:
        raise ValueError(f"Task {task_number} not found in context {context_id}.")
    result = dict(row)

    # Include step/task notes with IDs
    task_id = row["id"]
    note_rows = conn.execute(
        "SELECT id, note_md, created_at, kind FROM task_notes WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    result["notes"] = [{"id": r["id"], "note": r["note_md"], "created_at": r["created_at"], "kind": r["kind"]} for r in note_rows]

    return result


def get_plan_show(conn, context_ref: str | int | None = None, user_id: int | None = None, project_id: int | None = None) -> dict:
    context_id = (
        resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
        if context_ref is None
        else resolve_context_id(conn, context_ref, project_id=project_id)
    )
    context_row = conn.execute(
        "SELECT id, name, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()
    if not context_row:
        raise ValueError(f"Context {context_id} not found.")

    state_row = conn.execute(
        "SELECT active_task_id, status_label, last_event FROM context_state WHERE context_id = ?",
        (context_id,),
    ).fetchone()

    tasks = conn.execute(
        "SELECT id, sub_index AS task_number, title, description_md, status, is_deleted "
        "FROM tasks WHERE context_id = ? AND is_deleted = 0 AND sub_index IS NOT NULL "
        "ORDER BY sub_index",
        (context_id,),
    ).fetchall()

    active_task_number = None
    if state_row and state_row["active_task_id"]:
        active_row = conn.execute(
            "SELECT sub_index FROM tasks WHERE id = ?",
            (state_row["active_task_id"],),
        ).fetchone()
        if active_row:
            active_task_number = active_row["sub_index"]

    # Fetch goal and plan notes for inline display
    goal_plan_rows = conn.execute(
        "SELECT id, kind, note_md FROM context_notes "
        "WHERE context_id = ? AND kind IN ('goal', 'plan') AND note_md NOT LIKE '(migrated%' "
        "ORDER BY kind, id",
        (context_id,),
    ).fetchall()
    goal_notes = [r["note_md"] for r in goal_plan_rows if r["kind"] == "goal"]
    plan_notes = [r["note_md"] for r in goal_plan_rows if r["kind"] == "plan"]

    # Fetch all context notes with IDs for agent use
    all_notes = conn.execute(
        "SELECT id, note_md, created_at, actor, kind FROM context_notes WHERE context_id = ? ORDER BY id",
        (context_id,),
    ).fetchall()
    notes_list = [{"id": r["id"], "note": r["note_md"], "created_at": r["created_at"], "actor": r["actor"], "kind": r["kind"]} for r in all_notes]

    return {
        "context_id": context_id,
        "context_name": context_row["name"],
        "context_title": context_row["description_md"] or context_row["name"],
        "status_label": state_row["status_label"] if state_row else None,
        "last_event": state_row["last_event"] if state_row else None,
        "active_task_number": active_task_number,
        "goal": goal_notes[-1] if goal_notes else None,
        "plan": plan_notes[-1] if plan_notes else None,
        "notes": notes_list,
        "tasks": [dict(row) for row in tasks],
    }


def get_plan_status(conn, context_ref: str | int | None = None, user_id: int | None = None, project_id: int | None = None) -> dict:
    context_id = (
        resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
        if context_ref is None
        else resolve_context_id(conn, context_ref, project_id=project_id)
    )
    context_row = conn.execute(
        "SELECT id, name, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()
    if not context_row:
        raise ValueError(f"Context {context_id} not found.")

    state_row = conn.execute(
        "SELECT active_task_id, status_label, last_event FROM context_state WHERE context_id = ?",
        (context_id,),
    ).fetchone()

    counts_row = conn.execute(
        "SELECT "
        "SUM(CASE WHEN status = 'planned' AND is_deleted = 0 THEN 1 ELSE 0 END) AS planned_count, "
        "SUM(CASE WHEN status = 'started' AND is_deleted = 0 THEN 1 ELSE 0 END) AS started_count, "
        "SUM(CASE WHEN status = 'complete' AND is_deleted = 0 THEN 1 ELSE 0 END) AS completed_count, "
        "SUM(CASE WHEN status = 'blocked' AND is_deleted = 0 THEN 1 ELSE 0 END) AS blocked_count, SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END) AS deleted_count "
        "FROM tasks WHERE context_id = ?",
        (context_id,),
    ).fetchone()

    active_task_number = None
    if state_row and state_row["active_task_id"]:
        active_row = conn.execute(
            "SELECT sub_index FROM tasks WHERE id = ?",
            (state_row["active_task_id"],),
        ).fetchone()
        if active_row:
            active_task_number = active_row["sub_index"]

    return {
        "context_id": context_id,
        "context_name": context_row["name"],
        "context_title": context_row["description_md"] or context_row["name"],
        "status_label": state_row["status_label"] if state_row else None,
        "last_event": state_row["last_event"] if state_row else None,
        "active_task_number": active_task_number,
        "planned_count": counts_row["planned_count"] if counts_row else 0,
        "started_count": counts_row["started_count"] if counts_row else 0,
        "completed_count": counts_row["completed_count"] if counts_row else 0,
        "blocked_count": counts_row["blocked_count"] if counts_row else 0,
        "deleted_count": counts_row["deleted_count"] if counts_row else 0,
    }


def list_contexts(conn, user_id: int | None = None, show_all_users: bool = False,
                   project_id: int | None = None) -> list[dict]:
    active_id = None
    if user_id is not None:
        active_id = db.get_active_context_id_for_user(conn, user_id, project_id=project_id)
    if active_id is None:
        active_id = db.get_active_context_id(conn)

    # Build WHERE clauses
    conditions = []
    params = []
    if user_id is not None and not show_all_users:
        conditions.append("c.user_id = ?")
        params.append(user_id)
    if project_id is not None:
        conditions.append("c.project_id = ?")
        params.append(project_id)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        "SELECT c.id, c.name, c.status, c.description_md, c.user_id, "
        "t.sub_index AS task_number, t.title "
        "FROM contexts c "
        "LEFT JOIN context_state s ON s.context_id = c.id "
        "LEFT JOIN tasks t ON t.id = s.active_task_id"
        f"{where} ORDER BY c.id",
        params,
    ).fetchall()

    # Build user display name lookup
    user_names: dict[int, str] = {}
    for u in conn.execute("SELECT id, name, display_name FROM users").fetchall():
        user_names[u["id"]] = u["display_name"] or u["name"]

    contexts = []
    for row in rows:
        uid = row["user_id"]
        entry = {
            "id": row["id"],
            "user": user_names.get(uid, "unknown") if uid else "unknown",
            "name": row["name"],
            "status": row["status"],
            "title": row["description_md"] or row["name"],
            "is_active": row["id"] == active_id,
            "active_task_number": row["task_number"],
            "active_task_title": row["title"],
        }
        contexts.append(entry)
    return contexts


def list_tasks(conn, context_ref: str | int | None = None, user_id: int | None = None, project_id: int | None = None) -> dict:
    context_id = (
        resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
        if context_ref is None
        else resolve_context_id(conn, context_ref, project_id=project_id)
    )
    context_row = conn.execute(
        "SELECT id, name, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()
    if not context_row:
        raise ValueError(f"Context {context_id} not found.")
    active_row = conn.execute(
        "SELECT t.sub_index FROM context_state s "
        "JOIN tasks t ON t.id = s.active_task_id "
        "WHERE s.context_id = ?",
        (context_id,),
    ).fetchone()
    active_task_number = active_row["sub_index"] if active_row else None
    rows = conn.execute(
        "SELECT task_number, sub_index, title, status, is_deleted FROM tasks WHERE context_id = ? "
        "AND is_deleted = 0 AND sub_index IS NOT NULL "
        "ORDER BY sub_index",
        (context_id,),
    ).fetchall()
    return {
        "context_id": context_id,
        "context_name": context_row["name"],
        "context_title": context_row["description_md"] or context_row["name"],
        "active_task_number": active_task_number,
        "tasks": [
            {
                "task_number": row["sub_index"],
                "title": row["title"],
                "status": row["status"],
                "is_active": row["sub_index"] == active_task_number,
                "is_deleted": False,
            }
            for row in rows
        ],
    }


def list_plans(conn) -> list[dict]:
    return list_contexts(conn)


def get_context_logs(conn, context_ref: str | int) -> dict:
    context_id = resolve_context_id(conn, context_ref)
    context_row = conn.execute(
        "SELECT id, name, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()
    if not context_row:
        raise ValueError(f"Context {context_id} not found.")

    rows = conn.execute(
        "SELECT id, action, details_md, created_at, actor, task_id "
        "FROM changelog WHERE context_id = ? ORDER BY id",
        (context_id,),
    ).fetchall()

    return {
        "context_id": context_id,
        "context_name": context_row["name"],
        "context_title": context_row["description_md"] or context_row["name"],
        "events": [dict(row) for row in rows],
    }


def get_task_logs(
    conn,
    task_number: int,
    context_ref: str | int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    if context_ref is None:
        context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    else:
        context_id = resolve_context_id(conn, context_ref)

    task_row = conn.execute(
        "SELECT id, task_number, title FROM tasks WHERE context_id = ? AND task_number = ?",
        (context_id, task_number),
    ).fetchone()
    if not task_row:
        raise ValueError(f"Task {task_number} not found in context {context_id}.")

    rows = conn.execute(
        "SELECT id, action, details_md, created_at, actor, task_id "
        "FROM changelog WHERE task_id = ? ORDER BY id",
        (task_row["id"],),
    ).fetchall()

    context_row = conn.execute(
        "SELECT id, name, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()

    return {
        "context_id": context_id,
        "context_name": context_row["name"] if context_row else str(context_id),
        "context_title": context_row["description_md"] or context_row["name"]
        if context_row
        else str(context_id),
        "task_id": task_row["id"],
        "task_number": task_row["task_number"],
        "task_title": task_row["title"],
        "events": [dict(row) for row in rows],
    }


def _insert_tasks(conn, context_id: int, tasks: list[TaskInput], now: str) -> list[int]:
    if not tasks:
        return []

    task_ids: list[int] = []
    top_level_counter = 0
    child_counter: dict[int, int] = {}
    row = conn.execute(
        "SELECT MAX(task_number) AS max_num FROM tasks WHERE context_id = ?",
        (context_id,),
    ).fetchone()
    max_num = row["max_num"] if row else None
    task_number_counter = int(max_num) if max_num is not None else 0
    for idx, task in enumerate(tasks):
        sort_index = task.sort_index
        sub_index = task.sub_index
        if task.parent_id is None and sort_index is None:
            top_level_counter += 1
            sort_index = top_level_counter
        if task.parent_id is not None and sub_index is None:
            current = child_counter.get(task.parent_id, 0) + 1
            child_counter[task.parent_id] = current
            sub_index = current

        task_number_counter += 1
        cur = conn.execute(
            "INSERT INTO tasks (context_id, task_number, title, description_md, status, is_deleted, parent_id, "
            "sort_index, sub_index, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, 'planned', 0, ?, ?, ?, ?, ?, NULL)",
            (
                context_id,
                task_number_counter,
                task.title,
                task.description_md,
                task.parent_id,
                sort_index,
                sub_index,
                now,
                now,
            ),
        )
        task_ids.append(int(cur.lastrowid))

    return task_ids


def adopt_context(
    conn,
    source_name: str,
    new_name: Optional[str] = None,
    reset: bool = True,
    set_active: bool = True,
    actor: Optional[str] = None,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> int:
    """Deep-copy another user's context (task) into the current user's task list.

    Copies: context row, context_state, context_notes (goal/plan/note),
    tasks (steps) with parent_id remapping, and task_notes (step notes).
    Does NOT copy changelog — adds a single "Adopted from ..." entry instead.

    Returns the new context_id.
    """
    now = db.utc_now_iso()
    conn.execute("BEGIN")
    try:
        # 1. Resolve source context
        source_id = resolve_context_id(conn, source_name, project_id=project_id)
        source_row = conn.execute(
            "SELECT id, name, description_md, user_id, project_id FROM contexts WHERE id = ?",
            (source_id,),
        ).fetchone()
        if not source_row:
            raise ValueError(f"Source context '{source_name}' not found.")

        # 2. Determine target name
        target_name = new_name or source_row["name"]

        # 3. Check name collision within the same project
        target_project = project_id or source_row["project_id"]
        if target_project is not None:
            collision = conn.execute(
                "SELECT id FROM contexts WHERE name = ? AND project_id = ?",
                (target_name, target_project),
            ).fetchone()
        else:
            collision = conn.execute(
                "SELECT id FROM contexts WHERE name = ?",
                (target_name,),
            ).fetchone()
        if collision:
            raise ValueError(
                f"A task named '{target_name}' already exists in this project. "
                f"Use new_name to specify a different name."
            )

        # 4. INSERT new context
        cur = conn.execute(
            "INSERT INTO contexts (name, status, description_md, user_id, project_id, created_at, updated_at) "
            "VALUES (?, 'active', ?, ?, ?, ?, ?)",
            (target_name, source_row["description_md"], user_id, target_project, now, now),
        )
        new_context_id = int(cur.lastrowid)

        # 5. INSERT context_state (no active task yet — will set after copying steps)
        conn.execute(
            "INSERT INTO context_state (context_id, active_task_id, last_task_id, next_step, "
            "status_label, last_event, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_context_id, None, None, None, "Created", "Task Adopted", now),
        )

        # 6. Copy context_notes (goal, plan, note)
        source_notes = conn.execute(
            "SELECT note_md, created_at, actor, kind FROM context_notes WHERE context_id = ? ORDER BY id",
            (source_id,),
        ).fetchall()
        for note in source_notes:
            conn.execute(
                "INSERT INTO context_notes (context_id, note_md, created_at, actor, kind) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_context_id, note["note_md"], note["created_at"], note["actor"], note["kind"]),
            )

        # 7. Copy tasks (steps) with parent_id remapping
        source_tasks = conn.execute(
            "SELECT id, task_number, title, description_md, status, is_deleted, parent_id, "
            "sort_index, sub_index, created_at, updated_at, completed_at "
            "FROM tasks WHERE context_id = ? ORDER BY task_number",
            (source_id,),
        ).fetchall()

        old_to_new: dict[int, int] = {}  # old task.id → new task.id
        first_task_id = None

        for task in source_tasks:
            task_status = STATUS_PLANNED if reset else task["status"]
            task_completed = None if reset else task["completed_at"]

            cur = conn.execute(
                "INSERT INTO tasks (context_id, task_number, title, description_md, status, is_deleted, "
                "parent_id, sort_index, sub_index, created_at, updated_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (
                    new_context_id,
                    task["task_number"],
                    task["title"],
                    task["description_md"],
                    task_status,
                    task["is_deleted"],
                    task["sort_index"],
                    task["sub_index"],
                    now,
                    now,
                    task_completed,
                ),
            )
            new_task_id = int(cur.lastrowid)
            old_to_new[task["id"]] = new_task_id
            if first_task_id is None and task["is_deleted"] == 0:
                first_task_id = new_task_id

        # Second pass: fix parent_id references
        for old_id, new_id in old_to_new.items():
            source_task = conn.execute(
                "SELECT parent_id FROM tasks WHERE id = ?", (old_id,),
            ).fetchone()
            if source_task and source_task["parent_id"] is not None:
                new_parent = old_to_new.get(source_task["parent_id"])
                if new_parent is not None:
                    conn.execute(
                        "UPDATE tasks SET parent_id = ? WHERE id = ?",
                        (new_parent, new_id),
                    )

        # 8. Copy task_notes (step notes)
        for old_task_id, new_task_id in old_to_new.items():
            step_notes = conn.execute(
                "SELECT note_md, created_at, kind FROM task_notes WHERE task_id = ? ORDER BY id",
                (old_task_id,),
            ).fetchall()
            for note in step_notes:
                conn.execute(
                    "INSERT INTO task_notes (task_id, note_md, created_at, kind) VALUES (?, ?, ?, ?)",
                    (new_task_id, note["note_md"], note["created_at"], note["kind"]),
                )

        # 9. Set first non-deleted step as active
        if first_task_id is not None:
            conn.execute(
                "UPDATE tasks SET status = 'started', updated_at = ? WHERE id = ?",
                (now, first_task_id),
            )
            first_task_number = conn.execute(
                "SELECT task_number FROM tasks WHERE id = ?", (first_task_id,),
            ).fetchone()["task_number"]
            conn.execute(
                "UPDATE context_state SET active_task_id = ?, last_task_id = ?, "
                "last_event = ?, updated_at = ? WHERE context_id = ?",
                (first_task_id, first_task_id, "Task Started", now, new_context_id),
            )
            _set_next_step_for_active_task(
                conn, new_context_id, first_task_id, int(first_task_number), now
            )
        else:
            _set_next_step_for_new_task(conn, new_context_id, now)

        # 10. Set active if requested
        if set_active:
            if user_id is not None and project_id is not None:
                db.upsert_user_state(conn, user_id, project_id, new_context_id)
            db.upsert_global_state(conn, new_context_id)

        # 11. Changelog entry
        source_user_display = "unknown"
        if source_row["user_id"]:
            source_user_display = db.get_user_display(conn, source_row["user_id"])
        conn.execute(
            "INSERT INTO changelog (context_id, action, details_md, created_at, actor) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                new_context_id,
                "Task Adopted",
                f"Adopted from {source_user_display}/{source_row['name']}",
                now,
                actor,
            ),
        )

        conn.commit()
        return new_context_id
    except Exception:
        conn.rollback()
        raise


# =============================================================================
# Aliases: agent→plan, context→task, task→step rename (commit f03d9b3)
# main.py expects the new names; the functions above use the old names.
#
# Mapping:  old context → new task  |  old task → new step
# =============================================================================

# Save original step-level functions before overwriting their names.
_orig_list_tasks = list_tasks      # lists steps within a task
_orig_switch_task = switch_task    # switches active step
_orig_create_task = create_task    # creates a step within a task

# Classes
StepInput = TaskInput

# ── Task-level (was context) ──
get_task_show = get_plan_show
get_task_status = get_plan_status
resolve_task_id = resolve_context_id
resolve_active_task_id = resolve_active_context_id
switch_task = switch_context
adopt_task = adopt_context


def list_tasks(conn, status_filter=None, user_id=None, show_all_users=False, project_id=None):
    """List tasks (was list_contexts), with optional status and user filter."""
    contexts = list_contexts(conn, user_id=user_id, show_all_users=show_all_users, project_id=project_id)
    if status_filter:
        contexts = [c for c in contexts if c.get("status", "active") == status_filter]
    return contexts


def create_task(conn, name, description_md=None, steps=None, set_active=False, user_id=None, project_id=None, **kw):
    """Create a task (was context). Maps steps→tasks for create_context."""
    return create_context(
        conn, name=name, description_md=description_md,
        tasks=steps, set_active=set_active, user_id=user_id, project_id=project_id, **kw
    )


def complete_context(conn, name: str, user_id: int | None = None, project_id: int | None = None) -> None:
    """Mark a context as completed. Refuses to complete the active context."""
    context_id = resolve_context_id(conn, name, project_id=project_id)
    if user_id is not None:
        active_id = db.get_active_context_id_for_user(conn, user_id, project_id=project_id)
    else:
        active_id = db.get_active_context_id(conn)
    if context_id == active_id:
        raise ValueError(
            f"Cannot complete the active context '{name}'. Switch to another context first."
        )
    now = db.utc_now_iso()
    conn.execute(
        "UPDATE contexts SET status = 'completed', updated_at = ? WHERE id = ?",
        (now, context_id),
    )


complete_task_context = complete_context
add_task_notes = add_context_note
list_task_notes_on_task = list_context_notes


# ── Step-level (was task) ──
# Step adapters resolve sub_index → task_number, then delegate to task functions.

list_steps = _orig_list_tasks


def _step_task_number(conn, step_number, user_id=None, project_id=None):
    """Resolve step_number (sub_index) to task_number for the active context."""
    context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    _task_id, task_number = _resolve_step_by_subindex(conn, context_id, step_number)
    return task_number


def switch_step(conn, step_number, context_ref=None, actor=None, user_id=None, project_id=None):
    """Switch active step by sub_index."""
    task_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    return _orig_switch_task(conn, task_number, context_ref=context_ref, actor=actor,
                             user_id=user_id, project_id=project_id)


def complete_step(conn, step_number, context_ref=None, actor=None, user_id=None, project_id=None):
    """Complete a step by sub_index."""
    task_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    return complete_task(conn, task_number, context_ref=context_ref, actor=actor,
                         user_id=user_id, project_id=project_id)


def get_step_summary(conn, step_number=None, user_id=None, project_id=None, **kw):
    """Get step summary by sub_index."""
    if step_number is not None:
        step_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    return get_task_summary(conn, task_number=step_number, user_id=user_id, project_id=project_id, **kw)


def delete_step(conn, step_number, task_ref=None, user_id=None, project_id=None):
    """Delete a step by sub_index, then NULL its sub_index and renumber remaining steps."""
    context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    task_id, task_number = _resolve_step_by_subindex(conn, context_id, step_number)
    delete_task(conn, task_number, context_ref=task_ref, user_id=user_id, project_id=project_id)
    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE tasks SET sub_index = NULL WHERE id = ?", (task_id,))
        _renumber_steps(conn, context_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return task_id


def add_step_note(conn, note_md, step_number=None, user_id=None, project_id=None, kind="note", note_id=None):
    """Add a note to a step by sub_index."""
    if step_number is not None:
        step_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    return add_task_note(conn, note_md, task_number=step_number, user_id=user_id, project_id=project_id, kind=kind, note_id=note_id)


def delete_step_note(conn, note_id: int) -> None:
    """Adapter: wraps delete_task_note."""
    return delete_task_note(conn, note_id)


def list_step_notes(conn, step_number=None, user_id=None, project_id=None, kind=None):
    """List notes on a step by sub_index."""
    if step_number is not None:
        step_number = _step_task_number(conn, step_number, user_id=user_id, project_id=project_id)
    return list_task_notes(conn, task_number=step_number, user_id=user_id, project_id=project_id, kind=kind)


def create_step(conn, context_ref, title, description_md=None,
                 user_id=None, project_id=None, **kw):
    """Create a step and return (step_id, sub_index)."""
    task_id, _task_number = _orig_create_task(
        conn, context_ref, title, description_md=description_md,
        user_id=user_id, project_id=project_id, **kw
    )
    row = conn.execute("SELECT sub_index FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return task_id, int(row["sub_index"])


# ── Report data gathering ──

def get_project_report_data(
    conn,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Gather all data needed for a project report."""
    # Project metadata
    project = None
    if project_id is not None:
        project = db.get_project_by_id(conn, project_id)

    # All tasks for this user/project
    tasks = list_tasks(conn, user_id=user_id, project_id=project_id)
    # Also include completed
    all_tasks = list_tasks(conn, status_filter=None, user_id=user_id, project_id=project_id)

    # For each task, get goal/plan notes and step counts
    task_details = []
    for t in all_tasks:
        ctx_id = t["id"]
        # Goal and plan notes
        goal_plan_rows = conn.execute(
            "SELECT kind, note_md FROM context_notes "
            "WHERE context_id = ? AND kind IN ('goal', 'plan') AND note_md NOT LIKE '(migrated%' "
            "ORDER BY kind, id",
            (ctx_id,),
        ).fetchall()
        goal = None
        plan = None
        for r in goal_plan_rows:
            if r["kind"] == "goal":
                goal = r["note_md"]
            elif r["kind"] == "plan":
                plan = r["note_md"]

        # Step counts
        counts = conn.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'complete' AND is_deleted = 0 THEN 1 ELSE 0 END) AS done, "
            "SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS total "
            "FROM tasks WHERE context_id = ?",
            (ctx_id,),
        ).fetchone()

        # Steps detail
        steps = conn.execute(
            "SELECT sub_index AS task_number, title, status, description_md, is_deleted "
            "FROM tasks WHERE context_id = ? AND is_deleted = 0 AND sub_index IS NOT NULL "
            "ORDER BY sub_index",
            (ctx_id,),
        ).fetchall()

        task_details.append({
            "id": ctx_id,
            "name": t["name"],
            "title": t.get("title", t["name"]),
            "status": t.get("status", "active"),
            "goal": goal,
            "plan": plan,
            "steps_done": counts["done"] or 0 if counts else 0,
            "steps_total": counts["total"] or 0 if counts else 0,
            "steps": [dict(s) for s in steps],
        })

    # Config
    from . import config
    cfg = config.get_config()

    return {
        "project": dict(project) if project else {},
        "tasks": task_details,
        "config": cfg,
    }


def get_task_report_data(
    conn,
    context_ref: str | int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Gather all data needed for a single task report."""
    if context_ref is None:
        context_id = resolve_active_context_id(conn, user_id=user_id, project_id=project_id)
    else:
        context_id = resolve_context_id(conn, context_ref, project_id=project_id)

    context_row = conn.execute(
        "SELECT id, name, status, description_md FROM contexts WHERE id = ?",
        (context_id,),
    ).fetchone()
    if not context_row:
        raise ValueError(f"Context {context_id} not found.")

    # Goal and plan notes
    goal_plan_rows = conn.execute(
        "SELECT kind, note_md FROM context_notes "
        "WHERE context_id = ? AND kind IN ('goal', 'plan') AND note_md NOT LIKE '(migrated%' "
        "ORDER BY kind, id",
        (context_id,),
    ).fetchall()
    goals = [r["note_md"] for r in goal_plan_rows if r["kind"] == "goal"]
    plans = [r["note_md"] for r in goal_plan_rows if r["kind"] == "plan"]

    # Task-level notes (kind=note only)
    note_rows = conn.execute(
        "SELECT note_md, created_at, actor FROM context_notes "
        "WHERE context_id = ? AND kind = 'note' ORDER BY id",
        (context_id,),
    ).fetchall()

    # Steps with their notes
    steps = conn.execute(
        "SELECT id, sub_index, title, description_md, status "
        "FROM tasks WHERE context_id = ? AND is_deleted = 0 AND sub_index IS NOT NULL "
        "ORDER BY sub_index",
        (context_id,),
    ).fetchall()

    steps_data = []
    for s in steps:
        step_notes = conn.execute(
            "SELECT note_md, created_at, kind FROM task_notes "
            "WHERE task_id = ? ORDER BY id",
            (s["id"],),
        ).fetchall()
        steps_data.append({
            "number": s["sub_index"],
            "title": s["title"],
            "status": s["status"],
            "description": s["description_md"],
            "notes": [dict(n) for n in step_notes],
        })

    # Active step
    state_row = conn.execute(
        "SELECT active_task_id FROM context_state WHERE context_id = ?",
        (context_id,),
    ).fetchone()
    active_step_num = None
    if state_row and state_row["active_task_id"]:
        active_row = conn.execute(
            "SELECT sub_index FROM tasks WHERE id = ?",
            (state_row["active_task_id"],),
        ).fetchone()
        if active_row:
            active_step_num = active_row["sub_index"]

    return {
        "context_id": context_id,
        "name": context_row["name"],
        "title": context_row["description_md"] or context_row["name"],
        "status": context_row["status"],
        "goals": goals,
        "plans": plans,
        "notes": [dict(n) for n in note_rows],
        "steps": steps_data,
        "active_step": active_step_num,
    }
