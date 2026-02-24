"""Optional tool filter for mcpp framework discovery.

Returns tool names that should be excluded from MCP tool listings
based on config.yaml feature toggles.
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
    return mod.disabled_tools()
