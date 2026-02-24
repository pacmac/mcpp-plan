"""Integration tests for feature toggles (enable_steps, enable_versioning).

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
    report("enable_versioning defaults to True", wf["enable_versioning"] is True)


def test_disabled_tools_steps_off():
    _write_config(enable_steps=False)
    cfg = _load_config()
    result = cfg.disabled_tools()
    report("steps off: all step tools disabled", cfg.STEP_TOOLS.issubset(result))
    report("steps off: no versioning tools", len(cfg.VERSIONING_TOOLS & result) == 0)


def test_disabled_tools_versioning_off():
    _write_config(enable_versioning=False)
    cfg = _load_config()
    result = cfg.disabled_tools()
    report("versioning off: all versioning tools disabled", cfg.VERSIONING_TOOLS.issubset(result))
    report("versioning off: no step tools", len(cfg.STEP_TOOLS & result) == 0)


def test_disabled_tools_both_off():
    _write_config(enable_steps=False, enable_versioning=False)
    cfg = _load_config()
    result = cfg.disabled_tools()
    expected = cfg.STEP_TOOLS | cfg.VERSIONING_TOOLS
    report("both off: all toggled tools disabled", result == expected)


def test_disabled_tools_defaults():
    _write_config()
    cfg = _load_config()
    result = cfg.disabled_tools()
    report("defaults: no tools disabled", len(result) == 0)


def test_tool_sets():
    cfg = _load_config()
    bad = [t for t in cfg.STEP_TOOLS if not t.startswith("plan_step_")]
    report("STEP_TOOLS all start with plan_step_", len(bad) == 0, f"bad: {bad}")
    report("STEP_TOOLS has 10 tools", len(cfg.STEP_TOOLS) == 10, f"got {len(cfg.STEP_TOOLS)}")
    report("VERSIONING_TOOLS has 7 tools", len(cfg.VERSIONING_TOOLS) == 7, f"got {len(cfg.VERSIONING_TOOLS)}")


# ══════════════════════════════════════════════════════════
# UNIT TESTS — toolfilter.py
# ══════════════════════════════════════════════════════════

def test_toolfilter_defaults():
    _write_config()
    spec = importlib.util.spec_from_file_location("_tf", str(MODULE_DIR / "toolfilter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    report("toolfilter: no exclusions by default", len(mod.excluded_tools()) == 0)


def test_toolfilter_steps_off():
    _write_config(enable_steps=False)
    spec = importlib.util.spec_from_file_location("_tf2", str(MODULE_DIR / "toolfilter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cfg = _load_config()
    excluded = mod.excluded_tools()
    report("toolfilter: excludes step tools", cfg.STEP_TOOLS.issubset(excluded))


def test_toolfilter_both_off():
    _write_config(enable_steps=False, enable_versioning=False)
    spec = importlib.util.spec_from_file_location("_tf3", str(MODULE_DIR / "toolfilter.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cfg = _load_config()
    excluded = mod.excluded_tools()
    report("toolfilter: excludes all toggled tools", (cfg.STEP_TOOLS | cfg.VERSIONING_TOOLS).issubset(excluded))


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


def test_rx_versioning_tools_blocked():
    _write_config(enable_versioning=False)
    cfg = _load_config()
    for tool in sorted(cfg.VERSIONING_TOOLS):
        r = _call(tool, {"message": "x", "sha": "x"})
        ok = not r.get("success") and "disabled" in r.get("error", "")
        report(f"RX blocks {tool}", ok, r.get("error", "")[:60])


def test_rx_task_tools_not_blocked():
    _write_config(enable_steps=False, enable_versioning=False)
    r = _call("plan_task_list")
    report("task_list not blocked", r.get("success") is True, r.get("error", ""))
    r = _call("plan_task_status")
    report("task_status not blocked", r.get("success") is True, r.get("error", ""))


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

        print("\n-- Unit: disabled_tools --")
        test_disabled_tools_steps_off()
        test_disabled_tools_versioning_off()
        test_disabled_tools_both_off()
        test_disabled_tools_defaults()

        print("\n-- Unit: toolfilter.py --")
        test_toolfilter_defaults()
        test_toolfilter_steps_off()
        test_toolfilter_both_off()

        print("\n-- Integration: RX filter --")
        test_rx_step_tools_blocked()
        test_rx_versioning_tools_blocked()
        test_rx_task_tools_not_blocked()

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
