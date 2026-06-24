"""Tests for config profile validation, schema compliance, and typo prevention."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
import yaml

from agent_runtime.config_center.loader import _load_yaml
from agent_runtime.config_center.validator import validate_config_dry, load_schema, validate_profile_keys


ROOT = Path(__file__).resolve().parents[1]


def test_config_profiles_use_current_schema_keys() -> None:
    """Assert no active profile override uses routing_policy.default_mode or model_profiles.default_budget_mode."""
    profiles_path = ROOT / "config" / "config_profiles.yml"
    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles", {})
    
    for name, profile in profiles.items():
        # Check routing_policy
        rp = profile.get("routing_policy", {})
        assert "default_mode" not in rp, f"Profile '{name}' uses stale 'routing_policy.default_mode'"
        
        # Check model_profiles
        assert "model_profiles" not in profile, f"Profile '{name}' uses stale namespace 'model_profiles'"


def test_config_profile_dev_validates() -> None:
    """dev profile overlay validation passes."""
    errors = validate_config_dry(ROOT, profile_override="dev")
    assert errors == [], f"dev profile errors: {errors}"


def test_config_profile_prod_validates() -> None:
    """prod profile overlay validation passes."""
    errors = validate_config_dry(ROOT, profile_override="prod")
    assert errors == [], f"prod profile errors: {errors}"


def test_config_profile_frugal_validates() -> None:
    """frugal profile overlay validation passes and spelling is correct."""
    profiles_path = ROOT / "config" / "config_profiles.yml"
    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles", {})
    assert "frugal" in profiles
    assert "furgal" not in profiles
    
    errors = validate_config_dry(ROOT, profile_override="frugal")
    assert errors == [], f"frugal profile errors: {errors}"


def test_config_profile_max_quality_validates() -> None:
    """max_quality profile overlay validation passes."""
    errors = validate_config_dry(ROOT, profile_override="max_quality")
    assert errors == [], f"max_quality profile errors: {errors}"


def test_legacy_default_mode_is_not_used_in_committed_profiles() -> None:
    """Ensure committed profile overlays do not use routing_policy.default_mode."""
    profiles_path = ROOT / "config" / "config_profiles.yml"
    data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    profiles = data.get("profiles", {})
    for name, p in profiles.items():
        rp = p.get("routing_policy", {})
        assert "default_mode" not in rp, f"stale routing_policy.default_mode in committed profile {name}"


def test_legacy_furgal_not_used_in_committed_profiles() -> None:
    """Ensure no committed profile uses typo 'furgal'."""
    profiles_path = ROOT / "config" / "config_profiles.yml"
    content = profiles_path.read_text(encoding="utf-8")
    assert "furgal" not in content.lower(), "'furgal' spelling typo found in committed config_profiles.yml"


def test_profile_overlay_unknown_key_fails_or_warns() -> None:
    """A fixture overlay with an unknown key should not silently pass."""
    schema = load_schema(ROOT / "config" / "config_center.yml")
    bad_profile = {
        "routing_policy": {
            "default_budget": "balanced",
            "unknown_key_xyz": "value"
        },
        "nonexistent_namespace": {
            "some_key": 123
        }
    }
    errors = validate_profile_keys(bad_profile, schema.keys)
    assert len(errors) > 0, "Expected unknown keys to fail validation, but they passed."
    
    # Check that the specific unknown key paths are flagged in the errors
    err_str = "".join(errors)
    assert "routing_policy.unknown_key_xyz" in err_str
    assert "nonexistent_namespace.some_key" in err_str
