"""Global configuration for mcpp-plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_MODULE_DIR = Path(__file__).resolve().parent

DEFAULTS: dict[str, Any] = {
    "workflow": {
        "require_goal_and_plan": True,
    },
}


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """Merge overrides into defaults recursively. Only known keys are kept."""
    result = {}
    for key, default_val in defaults.items():
        if key in overrides:
            override_val = overrides[key]
            if isinstance(default_val, dict) and isinstance(override_val, dict):
                result[key] = _deep_merge(default_val, override_val)
            else:
                result[key] = override_val
        else:
            result[key] = default_val if not isinstance(default_val, dict) else dict(default_val)
    return result


def config_path() -> Path:
    """Return the path to config.yaml (same directory as plan.db)."""
    return _MODULE_DIR / "config.yaml"


def get_config() -> dict[str, Any]:
    """Load config.yaml and merge with defaults. Missing file or keys use defaults."""
    path = config_path()
    if path.exists():
        try:
            with open(path) as f:
                user_cfg = yaml.safe_load(f)
            if isinstance(user_cfg, dict):
                return _deep_merge(DEFAULTS, user_cfg)
        except (yaml.YAMLError, OSError):
            pass  # malformed or unreadable — fall back to defaults
    return _deep_merge(DEFAULTS, {})


def set_config(section: str, key: str, value: Any) -> dict[str, Any]:
    """Set a config key within a section. Returns the updated config."""
    path = config_path()
    file_cfg: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                file_cfg = loaded
        except (yaml.YAMLError, OSError):
            pass
    if section not in file_cfg or not isinstance(file_cfg.get(section), dict):
        file_cfg[section] = {}
    file_cfg[section][key] = value
    with open(path, "w") as f:
        yaml.safe_dump(file_cfg, f, default_flow_style=False)
    return get_config()
