"""Integration tests for feature toggles (enable_steps) and web-only tools.

Uses real config.yaml writes — mocks get stomped by _load_pkg().

Usage:
    python test_feature_toggles.py
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import time
from pathlib import Path

import yaml

MODULE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = MODULE_DIR / "config.yaml"
CONFIG_BACKUP = MODULE_DIR / "config.yaml.test_bak"

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


def _save_config():
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_BACKUP)


def _restore_config():
    if CONFIG_BACKUP.exists():
        shutil.move(str(CONFIG_BACKUP), str(CONFIG_PATH))
    elif CONFIG_PATH.exists():
        CONFIG_PATH.unlink()


def _write_config(**workflow_overrides):
    cfg = {"workflow": workflow_overrides}
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, default_flow_style=False))


def _write_full_config(data: dict):
    CONFIG_PATH.write_text(yaml.safe_dump(data, default_flow_style=False))


def _load_config():
    """Load config.py via importlib (no package dependency)."""
    spec = importlib.util.spec_from_file_location("_cfg", str(MODULE_DIR / "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _call(tool: str, args: dict | None = None):
    """Call an MCP tool via execute() with fresh module state."""
    for k in [k for k in sys.modules if k.startswith("mcpp_plan") or k == "_plan_config_rx"]:
        del sys.modules[k]
    spec = importlib.util.spec_from_file_location(
        "mcpptool", str(MODULE_DIR / "mcpptool.py"),
        submodule_search_locations=[str(MODULE_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.execute(tool, args or {}, {"workspace_dir": str(MODULE_DIR)})


_STEP_LEAK_KEYS = {"active_task_number", "active_task_title",
                   "planned_count", "started_count", "completed_count",
                   "blocked_count", "deleted_count"}

_ts = str(int(time.time()))[-6:]
_TASK = f"test-toggle-{_ts}"


# ══════════════════════════════════════════════════════════
# UNIT TESTS — config module
# ══════════════════════════════════════════════════════════

def test_defaults():
    cfg = _load_config()
    wf = cfg.DEFAULTS["workflow"]
    report("enable_steps defaults to True", wf["enable_steps"] is True)
    web = cfg.DEFAULTS["web"]
    report("web.key defaults to empty string", web["key"] == "")


def test_disabled_tools_steps_off():
    _write_config(enable_steps=False)
    cfg = _load_config()
    result = cfg.disabled_tools()
    report("steps off: all step tools disabled", cfg.STEP_TOOLS.issubset(result))


def test_disabled_tools_defaults():
    _write_config()
    cfg = _load_config()
    result = cfg.disabled_tools()
    report("defaults: no tools disabled", result == frozenset())


def test_tool_sets():
    cfg = _load_config()
    bad = [t for t in cfg.STEP_TOOLS if not t.startswith("plan_step_")]
    report("STEP_TOOLS all start with plan_step_", len(bad) == 0, f"bad: {bad}")
    report("STEP_TOOLS has 10 tools", len(cfg.STEP_TOOLS) == 10, f"got {len(cfg.STEP_TOOLS)}")
    report("WEB_ONLY_TOOLS has 1 tool", len(cfg.WEB_ONLY_TOOLS) == 1, f"got {len(cfg.WEB_ONLY_TOOLS)}")


def test_web_key():
    _write_full_config({"web": {"key": "test-secret-123"}})
    cfg = _load_config()
    report("check_web_key: correct key accepted", cfg.check_web_key("test-secret-123") is True)
    report("check_web_key: wrong key rejected", cfg.check_web_key("wrong") is False)
    report("check_web_key: None rejected", cfg.check_web_key(None) is False)
    report("check_web_key: empty rejected", cfg.check_web_key("") is False)


def test_web_key_unconfigured():
    _write_config()  # no web.key set
    cfg = _load_config()
    report("check_web_key: rejected when unconfigured", cfg.check_web_key("anything") is False)


# ══════════════════════════════════════════════════════════
# UNIT TESTS — toolfilter.py
# ══════════════════════════════════════════════════════════

def test_toolfilter_defaults():
    _write_config()
    spec = importlib.util.spec_from_file_location("_tf", str(MODULE_DIR / "toolfilter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cfg = _load_config()
    excluded = mod.excluded_tools()
    report("toolfilter: web-only tools excluded by default", cfg.WEB_ONLY_TOOLS.issubset(excluded))
    report("toolfilter: plan_project_select excluded", "plan_project_select" in excluded)


def test_toolfilter_steps_off():
    _write_config(enable_steps=False)
    spec = importlib.util.spec_from_file_location("_tf2", str(MODULE_DIR / "toolfilter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cfg = _load_config()
    excluded = mod.excluded_tools()
    report("toolfilter: excludes step tools", cfg.STEP_TOOLS.issubset(excluded))
    report("toolfilter: still excludes web-only tools", cfg.WEB_ONLY_TOOLS.issubset(excluded))


# ══════════════════════════════════════════════════════════
# INTEGRATION — RX filter
# ══════════════════════════════════════════════════════════

def test_rx_step_tools_blocked():
    _write_config(enable_steps=False)
    cfg = _load_config()
    for tool in sorted(cfg.STEP_TOOLS):
        r = _call(tool, {"number": 1, "title": "x", "text": "x", "order": [1]})
        ok = not r.get("success") and "disabled" in r.get("error", "")
        report(f"RX blocks {tool}", ok, r.get("error", "")[:60])


def test_rx_task_tools_not_blocked():
    _write_config(enable_steps=False)
    r = _call("plan_task_list")
    report("task_list not blocked", r.get("success") is True, r.get("error", ""))
    r = _call("plan_task_status")
    report("task_status not blocked", r.get("success") is True, r.get("error", ""))


# ══════════════════════════════════════════════════════════
# INTEGRATION — project tools
# ══════════════════════════════════════════════════════════

def test_project_list():
    _write_config()
    r = _call("plan_project_list")
    report("project_list succeeds", r.get("success") is True, r.get("error", ""))
    projects = r.get("result", {}).get("projects", [])
    report("project_list returns projects", len(projects) > 0, f"got {len(projects)}")


def test_project_select_no_key():
    _write_full_config({"web": {"key": "secret123"}})
    r = _call("plan_project_select", {"project_id": 1})
    report("project_select: rejected without key", not r.get("success"))
    report("project_select: error mentions key", "key" in r.get("error", "").lower())


def test_project_select_wrong_key():
    _write_full_config({"web": {"key": "secret123"}})
    r = _call("plan_project_select", {"project_id": 1, "key": "wrong"})
    report("project_select: rejected with wrong key", not r.get("success"))


def test_project_select_valid():
    _write_full_config({"web": {"key": "secret123"}})
    # First get a valid project ID
    r = _call("plan_project_list")
    projects = r.get("result", {}).get("projects", [])
    if not projects:
        report("project_select: skipped (no projects)", True)
        return
    pid = projects[0]["id"]
    r = _call("plan_project_select", {"project_id": pid, "key": "secret123"})
    report("project_select: accepted with correct key", r.get("success") is True, r.get("error", ""))

    # Clear the override so it doesn't affect other tests
    r = _call("plan_project_select", {"project_id": 0, "key": "secret123"})
    report("project_select: clear override (project_id=0)", r.get("success") is True, r.get("error", ""))


def test_project_set_key_gate():
    _write_full_config({"web": {"key": "secret123"}})
    r = _call("plan_project_set", {"name": "should-fail"})
    report("project_set: rejected without key when web.key set", not r.get("success"))
    report("project_set: error mentions key", "key" in r.get("error", "").lower())


def test_project_set_no_gate_when_unconfigured():
    _write_config()  # no web.key
    r = _call("plan_project_set", {"name": "mcpp-plan"})
    report("project_set: allowed when web.key not configured", r.get("success") is True, r.get("error", ""))


# ══════════════════════════════════════════════════════════
# INTEGRATION — TX filter
# ══════════════════════════════════════════════════════════

def _setup_test_task():
    _write_config()  # enable all for setup
    r = _call("plan_task_new", {"name": _TASK, "title": "Toggle Test",
                                "steps": ["Alpha", "Beta", "Gamma"]})
    assert r["success"], f"setup failed: {r}"
    _call("plan_task_notes_set", {"text": "Test goal", "kind": "goal"})
    _call("plan_task_notes_set", {"text": "Test plan", "kind": "plan"})


def test_tx_task_show():
    _write_config(enable_steps=False)
    _call("plan_task_switch", {"name": _TASK})
    r = _call("plan_task_show")
    report("task_show succeeds", r.get("success") is True, r.get("error", ""))
    result = r.get("result", {})
    leaked = _STEP_LEAK_KEYS & set(result.keys())
    report("task_show: no step keys", len(leaked) == 0, f"leaked: {leaked}")
    report("task_show: no 'tasks' key", "tasks" not in result)
    display = r.get("display", "")
    report("task_show display: no step checkboxes",
           not re.search(r"\[[ x>]\]\s+\d+\.", display), display[:80])
    report("task_show display: no step names", "Alpha" not in display and "Beta" not in display)


def test_tx_task_status():
    _write_config(enable_steps=False)
    r = _call("plan_task_status")
    report("task_status succeeds", r.get("success") is True)
    result = r.get("result", {})
    leaked = _STEP_LEAK_KEYS & set(result.keys())
    report("task_status: no step keys", len(leaked) == 0, f"leaked: {leaked}")
    display = r.get("display", "")
    report("task_status display: no 'Step'", "Step " not in display, display[:80])
    report("task_status display: no 'complete'", "complete" not in display.lower(), display[:80])


def test_tx_task_switch():
    _write_config(enable_steps=False)
    r = _call("plan_task_switch", {"name": _TASK})
    report("task_switch succeeds", r.get("success") is True)
    result = r.get("result", {})
    leaked = _STEP_LEAK_KEYS & set(result.keys())
    report("task_switch: no step keys", len(leaked) == 0, f"leaked: {leaked}")
    display = r.get("display", "")
    report("task_switch display: no 'Step'", "Step " not in display, display[:80])


def test_tx_task_list():
    _write_config(enable_steps=False)
    r = _call("plan_task_list")
    report("task_list succeeds", r.get("success") is True)
    tasks = r.get("result", {}).get("tasks", [])
    report("task_list has tasks", len(tasks) > 0)
    for t in tasks:
        leaked = {"active_task_number", "active_task_title"} & set(t.keys())
        if leaked:
            report(f"task_list entry [{t.get('name')}]: no step keys", False, f"leaked: {leaked}")
            return
    report("task_list entries: no step keys", True)


def test_tx_task_new_hides_default_step():
    _write_config(enable_steps=False)
    name = f"test-noleak-{_ts}"
    r = _call("plan_task_new", {"name": name, "title": "No Leak"})
    report("task_new succeeds", r.get("success") is True, r.get("error", ""))
    result = r.get("result", {})
    report("task_new: no 'tasks' key", "tasks" not in result)
    leaked = _STEP_LEAK_KEYS & set(result.keys())
    report("task_new: no step keys", len(leaked) == 0, f"leaked: {leaked}")
    display = r.get("display", "")
    report("task_new display: no step lines",
           not re.search(r"\[[ x>]\]\s+\d+\.", display), display[:80])


def test_tx_steps_enabled_preserves():
    _write_config(enable_steps=True)
    r = _call("plan_task_status")
    result = r.get("result", {})
    report("enabled: active_task_number present", "active_task_number" in result)


# ══════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    _save_config()
    try:
        print("\n=== Feature Toggle Tests ===\n")

        print("-- Unit: Config defaults --")
        test_defaults()
        test_tool_sets()

        print("\n-- Unit: Web key --")
        test_web_key()
        test_web_key_unconfigured()

        print("\n-- Unit: disabled_tools --")
        test_disabled_tools_steps_off()
        test_disabled_tools_defaults()

        print("\n-- Unit: toolfilter.py --")
        test_toolfilter_defaults()
        test_toolfilter_steps_off()

        print("\n-- Integration: RX filter --")
        test_rx_step_tools_blocked()
        test_rx_task_tools_not_blocked()

        print("\n-- Integration: Project tools --")
        test_project_list()
        test_project_select_no_key()
        test_project_select_wrong_key()
        test_project_select_valid()
        test_project_set_key_gate()
        test_project_set_no_gate_when_unconfigured()

        print("\n-- Integration: Setup test task --")
        _setup_test_task()
        report("test task created", True)

        print("\n-- Integration: TX filter --")
        test_tx_task_show()
        test_tx_task_status()
        test_tx_task_switch()
        test_tx_task_list()
        test_tx_task_new_hides_default_step()
        test_tx_steps_enabled_preserves()

        print(f"\n{'='*50}")
        print(f"  {passed} passed, {failed} failed")
        print(f"{'='*50}\n")
    finally:
        _restore_config()

    sys.exit(1 if failed else 0)
