"""Tool filter for mcpp-plan feature toggles.

Returns tool names to exclude from MCP discovery
based on config toggles and web-only restrictions.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def excluded_tools() -> frozenset[str]:
    """Return tool names to exclude based on current config."""
    cfg_path = Path(__file__).resolve().parent / "config.py"
    spec = importlib.util.spec_from_file_location("_plan_config", str(cfg_path))
    if not spec or not spec.loader:
        return frozenset()
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.disabled_tools() | mod.WEB_ONLY_TOOLS
