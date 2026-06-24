"""Tests for M2-5 Config Center loader — namespace handling and YAML loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_runtime.config_center.loader import (
    _deep_merge,
    _filename_to_namespace,
    _load_all_yamls,
    _load_yaml,
    load_layered_config,
    resolve_merged_config,
)
from agent_runtime.config_center.schema import ConfigLayer


# ── YAML loading ─────────────────────────────────────────────────────────


def test_load_yaml_returns_dict_for_valid_file(tmp_path: Path) -> None:
    f = tmp_path / "test.yml"
    f.write_text("key: value\n", encoding="utf-8")
    assert _load_yaml(f) == {"key": "value"}


def test_load_yaml_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert _load_yaml(tmp_path / "nonexistent.yml") == {}


def test_load_yaml_returns_empty_for_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.yml"
    f.write_text("", encoding="utf-8")
    assert _load_yaml(f) == {}


# ── Deep merge ───────────────────────────────────────────────────────────


def test_deep_merge_override_wins() -> None:
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested_dicts() -> None:
    base = {"x": {"a": 1, "b": 2}}
    override = {"x": {"b": 99, "c": 3}}
    assert _deep_merge(base, override) == {"x": {"a": 1, "b": 99, "c": 3}}


def test_deep_merge_empty_base() -> None:
    assert _deep_merge({}, {"a": 1}) == {"a": 1}


# ── Namespace mapping ────────────────────────────────────────────────────


def test_filename_to_namespace_mapped_file() -> None:
    assert _filename_to_namespace("routing_policy.yml") == "routing_policy"


def test_filename_to_namespace_excluded_file() -> None:
    # config_center.yml is excluded from global layer
    assert _filename_to_namespace("config_center.yml") is None


def test_filename_to_namespace_unmapped_file() -> None:
    # Unmapped files use their stem as namespace
    assert _filename_to_namespace("some_new_policy.yml") == "some_new_policy"


# ── Namespaced YAML loading (double-wrap prevention) ─────────────────────


def test_loader_does_not_double_wrap_already_namespaced_yaml(tmp_path: Path) -> None:
    """A file whose sole top-level key matches its filename stem should be unwrapped."""
    (tmp_path / "budget_policy.yml").write_text(
        "budget_policy:\n  default_currency: USD\n  max_task_cost_usd: 0.20\n",
        encoding="utf-8",
    )
    merged = _load_all_yamls(tmp_path)
    bp = merged.get("budget_policy", {})
    # Should NOT be nested: budget_policy.budget_policy.default_currency
    assert "default_currency" in bp, f"Expected direct keys, got: {list(bp.keys())}"
    assert "budget_policy" not in bp
    assert bp["default_currency"] == "USD"
    assert bp["max_task_cost_usd"] == 0.20


def test_loader_wraps_plain_yaml_under_file_stem(tmp_path: Path) -> None:
    """A file whose top-level keys do NOT match its stem stays wrapped."""
    (tmp_path / "routing_policy.yml").write_text(
        "default_budget: balanced\nrisk_auto_upgrade:\n  R2: balanced\n",
        encoding="utf-8",
    )
    merged = _load_all_yamls(tmp_path)
    rp = merged.get("routing_policy", {})
    assert "default_budget" in rp
    assert rp["default_budget"] == "balanced"


def test_budget_policy_keys_resolve_without_double_namespace() -> None:
    """Integration: verify budget_policy fields resolve cleanly from real config dir."""
    # Use the real AgentLab root
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    merged = resolve_merged_config(root)
    bp = merged.get("budget_policy", {})
    assert isinstance(bp, dict)
    assert "default_currency" in bp, f"budget_policy keys: {list(bp.keys())}"
    assert "max_task_cost_usd" in bp
    assert "budget_policy" not in bp, "double-wrapped: budget_policy.budget_policy found"


def test_routing_policy_default_budget_resolves() -> None:
    """Integration: routing_policy.default_budget resolves from real config."""
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    merged = resolve_merged_config(root)
    rp = merged.get("routing_policy", {})
    assert isinstance(rp, dict)
    assert "default_budget" in rp, f"routing_policy keys: {list(rp.keys())}"
    assert rp["default_budget"] in ("frugal", "balanced", "max_quality")


def test_execution_policy_nested_keys_resolve() -> None:
    """Integration: execution_policy nested keys resolve correctly."""
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    merged = resolve_merged_config(root)
    ep = merged.get("execution_policy", {})
    assert isinstance(ep, dict)
    # Has budget_mode_policy (nested)
    assert "budget_mode_policy" in ep
    # Has execution_policy subsection
    assert "execution_policy" in ep
    # Check nested key resolution
    bmp = ep.get("budget_mode_policy", {})
    assert isinstance(bmp, dict)
    assert "default_budget_mode" in bmp


# ── Layered config ───────────────────────────────────────────────────────


def test_layered_config_returns_all_layers() -> None:
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    layers = load_layered_config(root)
    for layer in ConfigLayer:
        assert layer in layers, f"Missing layer: {layer}"
    # GLOBAL_DEFAULTS should have many keys
    gd = layers[ConfigLayer.GLOBAL_DEFAULTS]
    assert len(gd) > 5, f"Expected >5 global namespaces, got {len(gd)}"


def test_resolve_merged_config_includes_budget_policy() -> None:
    from pathlib import Path as P

    root = P(__file__).resolve().parents[1]
    merged = resolve_merged_config(root)
    assert "budget_policy" in merged
    assert merged["budget_policy"]["max_task_cost_usd"] == 0.20
