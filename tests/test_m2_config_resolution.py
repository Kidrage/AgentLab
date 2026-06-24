"""M2-5 Config Center — layer resolution tests.

Tests project override > env, secret redaction, profile application,
and cross-layer key resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.config_center.diff import diff_configs, project_diff, ConfigDiff, DiffEntry
from agent_runtime.config_center.loader import _deep_merge, resolve_merged_config
from agent_runtime.config_center.profile import apply_profile, load_profiles, get_active_profile
from agent_runtime.config_center.resolver import resolve_key, resolve_all_keys
from agent_runtime.config_center.schema import ConfigLayer, ConfigValue
from agent_runtime.config_center.secrets_redaction import (
    REDACTED_PLACEHOLDER,
    is_secret_key,
    redact_config,
    redact_config_value,
)

ROOT = Path(__file__).resolve().parents[1]


# ── Resolution tests ─────────────────────────────────────────────────────


def test_resolve_key_returns_config_value() -> None:
    cv = resolve_key(ROOT, "routing_policy.default_budget")
    assert cv is not None, "Expected routing_policy.default_budget to exist"
    assert isinstance(cv, ConfigValue)
    assert cv.key == "routing_policy.default_budget"
    assert cv.value is not None


def test_resolve_key_nonexistent_returns_none() -> None:
    cv = resolve_key(ROOT, "nonexistent.ghost.key")
    assert cv is None


def test_resolve_key_tracks_source_layer() -> None:
    cv = resolve_key(ROOT, "routing_policy.default_budget")
    assert cv is not None
    # default_budget comes from routing_policy.yml → GLOBAL_DEFAULTS layer
    assert cv.layer in ConfigLayer


def test_resolve_all_keys_returns_many_keys() -> None:
    resolved = resolve_all_keys(ROOT)
    assert len(resolved) > 20, f"Expected >20 keys, got {len(resolved)}"
    for cv in resolved.values():
        assert isinstance(cv, ConfigValue)
        assert cv.layer in ConfigLayer


def test_resolve_all_keys_with_explicit_list() -> None:
    keys = ["routing_policy.default_budget", "routing_policy.schema_version"]
    resolved = resolve_all_keys(ROOT, keys=keys)
    assert len(resolved) <= len(keys)
    for k in keys:
        if k in resolved:
            assert resolved[k].key == k


# ── Deep merge / override tests ──────────────────────────────────────────


def test_project_override_has_higher_priority_than_global() -> None:
    """Simulate: global sets a key, project override sets the same key.
    The project override should win.
    """
    base = _deep_merge({"routing": {"mode": "fast"}}, {"routing": {"mode": "strict"}})
    assert base["routing"]["mode"] == "strict"


def test_runtime_override_beats_all() -> None:
    """Runtime temporary layer (12) beats everything below."""
    layers = {
        ConfigLayer.GLOBAL_DEFAULTS: {"k": 1},
        ConfigLayer.RUNTIME_TEMPORARY: {"k": 999},
    }
    merged: dict = {}
    for layer in ConfigLayer:
        data = layers.get(layer, {})
        if data:
            merged = _deep_merge(merged, data)
    assert merged["k"] == 999


def test_skill_override_beats_project() -> None:
    """Skill override (9) beats project override (7)."""
    layers = {
        ConfigLayer.PROJECT_OVERRIDE: {"k": 7},
        ConfigLayer.SKILL_OVERRIDE: {"k": 9},
    }
    merged: dict = {}
    for layer in ConfigLayer:
        data = layers.get(layer, {})
        if data:
            merged = _deep_merge(merged, data)
    assert merged["k"] == 9


# ── Secret redaction tests ───────────────────────────────────────────────


def test_is_secret_key_detects_api_key() -> None:
    assert is_secret_key("api_key")
    assert is_secret_key("OPENAI_API_KEY")
    assert is_secret_key("secret_token")


def test_is_secret_key_rejects_normal_keys() -> None:
    assert not is_secret_key("default_mode")
    assert not is_secret_key("max_concurrent")
    assert not is_secret_key("schema_version")


def test_redact_config_masks_secret_values() -> None:
    config = {
        "open_api_key": "sk-1234567890abcdef",
        "default_mode": "fast",
        "nested": {"secret": "mysecret"},
    }
    redacted = redact_config(config)
    assert redacted["open_api_key"] == REDACTED_PLACEHOLDER
    assert redacted["default_mode"] == "fast"
    assert redacted["nested"]["secret"] == REDACTED_PLACEHOLDER


def test_redact_config_value_returns_placeholder() -> None:
    cv = ConfigValue(key="api_key", value="real-key", layer=ConfigLayer.GLOBAL_DEFAULTS)
    result = redact_config_value(cv, cv.key)
    assert result == REDACTED_PLACEHOLDER


def test_redact_config_value_returns_real_for_non_secret() -> None:
    cv = ConfigValue(key="mode", value="fast", layer=ConfigLayer.GLOBAL_DEFAULTS)
    result = redact_config_value(cv, cv.key)
    assert result == "fast"


# ── Profile tests ────────────────────────────────────────────────────────


def test_load_profiles_returns_dict() -> None:
    profiles = load_profiles(ROOT)
    assert isinstance(profiles, dict)
    # config_profiles.yml defines dev, prod, frugal, max_quality
    assert len(profiles) >= 4, f"Expected >=4 profiles, got {len(profiles)}"
    for name in ("dev", "prod", "frugal", "max_quality"):
        assert name in profiles, f"Profile '{name}' should exist"


def test_apply_profile_overrides_base() -> None:
    base = {"routing_policy": {"default_mode": "brain_allocated"}}
    profile = {"routing_policy": {"default_mode": "full_cli"}}
    result = apply_profile(base, profile)
    assert result["routing_policy"]["default_mode"] == "full_cli"


def test_dev_profile_makes_permissive() -> None:
    profiles = load_profiles(ROOT)
    dev = profiles["dev"]
    assert "routing_policy" in dev
    assert dev["routing_policy"]["default_mode"] == "full_cli"
    assert dev["routing_policy"]["allow_automatic_fallback"] is True


# ── Diff tests ───────────────────────────────────────────────────────────


def test_diff_configs_detects_changes() -> None:
    base = {
        "a": ConfigValue(key="a", value=1, layer=ConfigLayer.GLOBAL_DEFAULTS),
        "b": ConfigValue(key="b", value=2, layer=ConfigLayer.GLOBAL_DEFAULTS),
    }
    override = {
        "a": ConfigValue(key="a", value=1, layer=ConfigLayer.GLOBAL_DEFAULTS),  # unchanged
        "b": ConfigValue(key="b", value=99, layer=ConfigLayer.PROJECT_OVERRIDE),  # changed
        "c": ConfigValue(key="c", value=3, layer=ConfigLayer.PROJECT_OVERRIDE),  # added
    }
    diff = diff_configs(base, override)
    assert len(diff.changed) == 2  # b changed, c added
    kinds = {e.diff_kind for e in diff.changed}
    assert kinds == {"changed", "added"}


def test_diff_configs_no_changes() -> None:
    base = {"a": ConfigValue(key="a", value=1, layer=ConfigLayer.GLOBAL_DEFAULTS)}
    diff = diff_configs(base, base)
    assert len(diff.changed) == 0


def test_diff_entry_unchanged_has_no_diff() -> None:
    entry = DiffEntry(key="x", base_value=1, override_value=1, diff_kind="unchanged")
    assert not entry.has_diff


def test_diff_entry_changed_has_diff() -> None:
    entry = DiffEntry(key="x", base_value=1, override_value=2, diff_kind="changed")
    assert entry.has_diff
