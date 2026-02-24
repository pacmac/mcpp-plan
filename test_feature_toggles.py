#!/usr/bin/env python3
"""Tests for feature toggle behavior (enable_steps, enable_versioning).

Two levels:
- Unit tests: config module logic (defaults, disabled_tools, toolfilter)
- Integration tests: full execute() calls with real DB, verifying JSON results
  and display text contain no step/versioning leaks when disabled.

Usage:
    python test_feature_toggles.py
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

MODULE_DIR = Path(__file__).resolve().parent

# Import as package to handle relative imports
pkg_dir = MODULE_DIR.parent
pkg_name = MODULE_DIR.name
if str(pkg_dir) not in sys.path:
    sys.path.insert(0, str(pkg_dir))

config_mod = importlib.import_module(f"{pkg_name}.config")

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def _mock_config(**overrides):
    """Return a config dict with workflow overrides applied to defaults."""
    cfg = {"workflow": dict(config_mod.DEFAULTS["workflow"])}
    cfg["workflow"].update(overrides)
    return cfg


def _patch_config_for_mcpptool(**overrides):
    """Patch get_config on the module that mcpptool._get_config_mod() returns."""
    target = sys.modules.get("mcpp_plan.config", config_mod)
    return patch.object(target, "get_config", return_value=_mock_config(**overrides))


# ── Helpers ──

_mcpptool_cache = None


def _load_mcpptool():
    global _mcpptool_cache
    if _mcpptool_cache is not None:
        return _mcpptool_cache
    spec = importlib.util.spec_from_file_location(
        "mcpp_tools.mcpp_plan", str(MODULE_DIR / "mcpptool.py"),
        submodule_search_locations=[str(MODULE_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mcpptool_cache = mod
    return mod


def _call(tool: str, args: dict | None = None):
    """Call an MCP tool via execute() with the test workspace."""
    mcpptool = _load_mcpptool()
    return mcpptool.execute(tool, args or {}, {"workspace_dir": str(MODULE_DIR)})


_STEP_LEAK_KEYS = {"tasks", "active_task_number", "active_task_title",
                   "planned_count", "started_count", "completed_count",
                   "blocked_count", "deleted_count",
                   "steps", "active_step", "steps_done", "steps_total"}


def _check_no_step_keys(data: dict, label: str):
    """Check a result dict has no step-related keys."""
    found = _STEP_LEAK_KEYS & set(data.keys())
    report(f"{label}: no step keys in result", len(found) == 0,
           f"leaked: {found}" if found else "")


def _check_no_step_text(text: str, label: str):
    """Check display text has no step-related content."""
    step_words = ["Step ", "step ", "planned", "started", "complete"]
    # "complete" in task status context means step completion, not task status
    found = [w for w in step_words if w in text]
    report(f"{label}: no step text in display", len(found) == 0,
           f"found: {found}" if found else "")


# ══════════════════════════════════════════════════════════
# UNIT TESTS
# ══════════════════════════════════════════════════════════

# ── 1. Defaults ──

def test_defaults_all_enabled():
    """With default config, all features are enabled."""
    cfg = config_mod.DEFAULTS
    wf = cfg["workflow"]
    report("enable_steps defaults to True", wf["enable_steps"] is True)
    report("enable_versioning defaults to True", wf["enable_versioning"] is True)


def test_defaults_no_disabled_tools():
    """With default config, no tools are disabled."""
    with patch.object(config_mod, "get_config", return_value=_mock_config()):
        result = config_mod.disabled_tools()
        report("no tools disabled by default", len(result) == 0, f"got {len(result)}")


# ── 2. is_feature_enabled ──

def test_is_feature_enabled():
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_steps=True)):
        report("is_feature_enabled('steps') = True", config_mod.is_feature_enabled("steps") is True)
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_steps=False)):
        report("is_feature_enabled('steps') = False", config_mod.is_feature_enabled("steps") is False)
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_versioning=True)):
        report("is_feature_enabled('versioning') = True", config_mod.is_feature_enabled("versioning") is True)
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_versioning=False)):
        report("is_feature_enabled('versioning') = False", config_mod.is_feature_enabled("versioning") is False)


# ── 3. disabled_tools ──

def test_disabled_tools_steps_off():
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_steps=False)):
        result = config_mod.disabled_tools()
        missing = config_mod.STEP_TOOLS - result
        extra = config_mod.VERSIONING_TOOLS & result
        report("steps off: all step tools disabled", len(missing) == 0, f"missing: {missing}")
        report("steps off: versioning tools unaffected", len(extra) == 0, f"extra: {extra}")


def test_disabled_tools_versioning_off():
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_versioning=False)):
        result = config_mod.disabled_tools()
        missing = config_mod.VERSIONING_TOOLS - result
        extra = config_mod.STEP_TOOLS & result
        report("versioning off: all versioning tools disabled", len(missing) == 0, f"missing: {missing}")
        report("versioning off: step tools unaffected", len(extra) == 0, f"extra: {extra}")


def test_disabled_tools_both_off():
    with patch.object(config_mod, "get_config", return_value=_mock_config(enable_steps=False, enable_versioning=False)):
        result = config_mod.disabled_tools()
        expected = config_mod.STEP_TOOLS | config_mod.VERSIONING_TOOLS
        report("both off: all toggled tools disabled", result == expected, f"got {len(result)}, expected {len(expected)}")


# ── 4. toolfilter.py ──

def test_toolfilter():
    spec = importlib.util.spec_from_file_location("_tf", str(MODULE_DIR / "toolfilter.py"))
    if not spec or not spec.loader:
        report("toolfilter.py loads", False, "cannot load")
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report("toolfilter.py loads", True)
    result = mod.excluded_tools()
    report("toolfilter: no exclusions by default", len(result) == 0, f"got {len(result)}")


# ── 5. Tool set completeness ──

def test_tool_sets():
    bad = [t for t in config_mod.STEP_TOOLS if not t.startswith("plan_step_")]
    report("all STEP_TOOLS start with plan_step_", len(bad) == 0, f"bad: {bad}")
    expected_v = {"plan_checkpoint", "plan_commit", "plan_push", "plan_restore", "plan_log", "plan_status", "plan_diff"}
    report("VERSIONING_TOOLS matches expected", config_mod.VERSIONING_TOOLS == expected_v,
           f"diff: {config_mod.VERSIONING_TOOLS ^ expected_v}")


# ══════════════════════════════════════════════════════════
# INTEGRATION TESTS — real execute() with patched config
# ══════════════════════════════════════════════════════════

_ts = str(int(time.time()))[-6:]
_TASK = f"test-toggle-{_ts}"
_cleanup_tasks: list[str] = []


def _setup_test_task():
    """Create a test task with steps for integration testing."""
    r = _call("plan_task_new", {"name": _TASK, "title": "Toggle Test Task",
                                 "steps": ["Alpha", "Beta", "Gamma"]})
    assert r["success"], f"setup failed: {r}"
    _cleanup_tasks.append(_TASK)
    # Add goal and plan notes so operations don't fail on require_goal_and_plan
    _call("plan_task_notes_set", {"text": "Test goal", "kind": "goal"})
    _call("plan_task_notes_set", {"text": "Test plan", "kind": "plan"})


def _cleanup_test_tasks():
    """Complete test tasks to clean up."""
    # Switch to a different task first, then complete the test ones
    _call("plan_task_new", {"name": f"test-cleanup-{_ts}", "title": "cleanup"})
    for name in _cleanup_tasks:
        try:
            _call("plan_task_complete", {"name": name})
        except Exception:
            pass
    try:
        _call("plan_task_complete", {"name": f"test-cleanup-{_ts}"})
    except Exception:
        pass


# ── 6. execute() blocks disabled tools ──

def test_execute_blocks_step_tools():
    """Calling step tools when steps disabled returns clear error."""
    with _patch_config_for_mcpptool(enable_steps=False):
        for tool in ["plan_step_list", "plan_step_show", "plan_step_new",
                      "plan_step_done", "plan_step_switch", "plan_step_delete",
                      "plan_step_notes_set", "plan_step_notes_get", "plan_step_notes_delete",
                      "plan_step_reorder"]:
            r = _call(tool, {"number": 1, "title": "x", "text": "x", "order": [1]})
            report(f"{tool} blocked", r.get("success") is False, r.get("error", ""))
            ok = "enable_steps" in r.get("error", "")
            report(f"{tool} error mentions config", ok, r.get("error", ""))


def test_execute_blocks_versioning_tools():
    """Calling versioning tools when versioning disabled returns clear error."""
    with _patch_config_for_mcpptool(enable_versioning=False):
        for tool in ["plan_checkpoint", "plan_commit", "plan_push",
                      "plan_restore", "plan_log", "plan_status", "plan_diff"]:
            r = _call(tool, {"message": "x", "sha": "x"})
            report(f"{tool} blocked", r.get("success") is False, r.get("error", ""))
            ok = "enable_versioning" in r.get("error", "")
            report(f"{tool} error mentions config", ok, r.get("error", ""))


# ── 7. plan_task_new result with steps disabled ──

def test_task_new_no_step_leak():
    """plan_task_new result has no step info when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_new", {"name": f"test-noleak-{_ts}", "title": "No Leak",
                                     "steps": ["Should", "Be", "Hidden"]})
        _cleanup_tasks.append(f"test-noleak-{_ts}")
        report("task_new succeeds", r.get("success") is True)
        result = r.get("result", {})
        _check_no_step_keys(result, "task_new")
        display = r.get("display", "")
        report("task_new display: no step lines", "Should" not in display and "Hidden" not in display, display)


# ── 8. plan_task_show with steps disabled ──

def test_task_show_no_step_leak():
    """plan_task_show result has no step data when steps disabled."""
    # First ensure we're on a task with steps (created in setup)
    _call("plan_task_switch", {"name": _TASK})
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_show", {})
        report("task_show succeeds", r.get("success") is True)
        result = r.get("result", {})
        _check_no_step_keys(result, "task_show")
        display = r.get("display", "")
        report("task_show display: no step lines", "Alpha" not in display and "Beta" not in display, display)


# ── 9. plan_task_status with steps disabled ──

def test_task_status_no_step_leak():
    """plan_task_status omits step counts when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_status", {})
        report("task_status succeeds", r.get("success") is True)
        result = r.get("result", {})
        _check_no_step_keys(result, "task_status")
        display = r.get("display", "")
        report("task_status display: no 'Step' text", "Step" not in display, display)


# ── 10. plan_task_switch with steps disabled ──

def test_task_switch_no_step_leak():
    """plan_task_switch result has no step info when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_switch", {"name": _TASK})
        report("task_switch succeeds", r.get("success") is True)
        result = r.get("result", {})
        _check_no_step_keys(result, "task_switch")
        display = r.get("display", "")
        report("task_switch display: no 'Step' text", "Step" not in display, display)


# ── 11. plan_task_list with steps disabled ──

def test_task_list_no_step_leak():
    """plan_task_list entries have no step references when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_list", {})
        report("task_list succeeds", r.get("success") is True)
        tasks = r.get("result", {}).get("tasks", [])
        report("task_list has tasks", len(tasks) > 0, f"got {len(tasks)}")
        for t in tasks:
            leaked = _STEP_LEAK_KEYS & set(t.keys())
            if leaked:
                report(f"task_list entry [{t.get('name')}]: no step keys", False, f"leaked: {leaked}")
                break
        else:
            report("task_list entries: no step keys", True)


# ── 12. plan_task_report with steps disabled ──

def test_task_report_no_step_leak():
    """plan_task_report omits step section when steps disabled."""
    _call("plan_task_switch", {"name": _TASK})
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_report", {"name": _TASK})
        report("task_report succeeds", r.get("success") is True)
        content = r.get("result", {}).get("content", "")
        report("task_report: no '## Steps' section", "## Steps" not in content, "")
        report("task_report: no step names", "Alpha" not in content and "Beta" not in content, "")
        # Clean up report file
        fpath = r.get("result", {}).get("file")
        if fpath:
            Path(fpath).unlink(missing_ok=True)


# ── 13. plan_project_report with steps disabled ──

def test_project_report_no_step_leak():
    """plan_project_report omits step progress and step lists when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_project_report", {})
        report("project_report succeeds", r.get("success") is True)
        content = r.get("result", {}).get("content", "")
        # Table should not have Progress column
        report("project_report: no Progress column", "Progress" not in content, "")
        # Should not have step checkbox lines
        report("project_report: no step checkboxes", "[>]" not in content and "[ ]" not in content, "")
        fpath = r.get("result", {}).get("file")
        if fpath:
            Path(fpath).unlink(missing_ok=True)


# ── 14. Existing task with steps → toggle off → show ──

def test_existing_steps_hidden_after_toggle():
    """Steps created when enabled are hidden when toggle is turned off."""
    # Task was created with steps enabled (setup). Now show with disabled.
    _call("plan_task_switch", {"name": _TASK})
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_show", {})
        result = r.get("result", {})
        _check_no_step_keys(result, "existing task after toggle off")
        display = r.get("display", "")
        report("existing task: no step lines in display", "Alpha" not in display, display)


# ── 15. Non-step task tools still work when steps disabled ──

def test_task_tools_work_with_steps_disabled():
    """Core task tools (new, show, status, list, notes) still work when steps disabled."""
    with _patch_config_for_mcpptool(enable_steps=False):
        r = _call("plan_task_status", {})
        report("task_status works", r.get("success") is True)
        r = _call("plan_task_show", {})
        report("task_show works", r.get("success") is True)
        r = _call("plan_task_list", {})
        report("task_list works", r.get("success") is True)
        r = _call("plan_task_notes_get", {})
        report("task_notes_get works", r.get("success") is True)


# ── 16. Display formatters with mock data ──

def test_fmt_task_show_steps_enabled():
    mcpptool = _load_mcpptool()
    data = {
        "context_name": "test", "context_title": "Test Task",
        "active_task_number": 1,
        "tasks": [
            {"task_number": 1, "title": "Step One", "status": "started", "is_deleted": 0},
            {"task_number": 2, "title": "Step Two", "status": "planned", "is_deleted": 0},
        ],
    }
    with _patch_config_for_mcpptool(enable_steps=True):
        result = mcpptool._fmt_task_show(data)
        report("fmt_task_show enabled: includes steps", "Step One" in result and "Step Two" in result)


def test_fmt_task_show_steps_disabled():
    mcpptool = _load_mcpptool()
    data = {
        "context_name": "test", "context_title": "Test Task",
        "active_task_number": 1,
        "tasks": [
            {"task_number": 1, "title": "Step One", "status": "started", "is_deleted": 0},
        ],
    }
    with _patch_config_for_mcpptool(enable_steps=False):
        result = mcpptool._fmt_task_show(data)
        report("fmt_task_show disabled: omits steps", "Step One" not in result)


def test_fmt_task_status_steps_enabled():
    mcpptool = _load_mcpptool()
    data = {"context_name": "test", "context_title": "T", "active_task_number": 2,
            "completed_count": 1, "planned_count": 1, "started_count": 1}
    with _patch_config_for_mcpptool(enable_steps=True):
        result = mcpptool._fmt_task_status(data)
        report("fmt_task_status enabled: has step info", "Step 2 active" in result)


def test_fmt_task_status_steps_disabled():
    mcpptool = _load_mcpptool()
    data = {"context_name": "test", "context_title": "T", "active_task_number": 2,
            "completed_count": 1, "planned_count": 1, "started_count": 1}
    with _patch_config_for_mcpptool(enable_steps=False):
        result = mcpptool._fmt_task_status(data)
        report("fmt_task_status disabled: no step info", "Step" not in result)
        report("fmt_task_status disabled: still shows name", "test" in result)


# ══════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n=== Feature Toggle Tests ===\n")

    print("-- Unit: Defaults --")
    test_defaults_all_enabled()
    test_defaults_no_disabled_tools()

    print("\n-- Unit: is_feature_enabled --")
    test_is_feature_enabled()

    print("\n-- Unit: disabled_tools --")
    test_disabled_tools_steps_off()
    test_disabled_tools_versioning_off()
    test_disabled_tools_both_off()

    print("\n-- Unit: toolfilter.py --")
    test_toolfilter()

    print("\n-- Unit: Tool sets --")
    test_tool_sets()

    print("\n-- Unit: Display formatters --")
    test_fmt_task_show_steps_enabled()
    test_fmt_task_show_steps_disabled()
    test_fmt_task_status_steps_enabled()
    test_fmt_task_status_steps_disabled()

    print("\n-- Integration: Setup --")
    _setup_test_task()
    report("test task created", True)

    print("\n-- Integration: execute() blocks disabled tools --")
    test_execute_blocks_step_tools()
    test_execute_blocks_versioning_tools()

    print("\n-- Integration: No step leaks in results --")
    test_task_new_no_step_leak()
    test_task_show_no_step_leak()
    test_task_status_no_step_leak()
    test_task_switch_no_step_leak()
    test_task_list_no_step_leak()

    print("\n-- Integration: No step leaks in reports --")
    test_task_report_no_step_leak()
    test_project_report_no_step_leak()

    print("\n-- Integration: Existing steps hidden after toggle --")
    test_existing_steps_hidden_after_toggle()

    print("\n-- Integration: Task tools work with steps off --")
    test_task_tools_work_with_steps_disabled()

    print("\n-- Cleanup --")
    _cleanup_test_tasks()

    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*50}\n")
    sys.exit(1 if failed else 0)
