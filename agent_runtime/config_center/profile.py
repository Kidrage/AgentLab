"""Named config profiles for M2-5 Config Center.

Manages named configuration profiles (dev, prod, frugal, max_quality)
and applies them as overrides on top of base config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.config_center.loader import _deep_merge, _load_yaml


def load_profiles(agentlab_root: Path) -> dict[str, dict[str, Any]]:
    """Load named config profiles from config/config_profiles.yml.

    Returns {profile_name: {key: value, ...}}.
    """
    path = agentlab_root / "config" / "config_profiles.yml"
    data = _load_yaml(path)
    profiles = data.get("profiles", {})
    if isinstance(profiles, dict):
        return {k: v for k, v in profiles.items() if isinstance(v, dict)}
    return {}


def apply_profile(
    base_config: dict[str, Any],
    profile_overrides: dict[str, Any],
) -> dict[str, Any]:
    """Apply a named profile's overrides on top of base config."""
    return _deep_merge(base_config, profile_overrides)


def get_active_profile(agentlab_root: Path) -> str | None:
    """Return the currently active profile name, if any."""
    path = agentlab_root / "config" / "config_center.yml"
    data = _load_yaml(path)
    return data.get("active_profile") if isinstance(data, dict) else None
