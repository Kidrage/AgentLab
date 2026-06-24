"""Tests for M2-5 Config Center validator — schema loading and validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_runtime.config_center.schema import ConfigKeySchema, ConfigSchema
from agent_runtime.config_center.validator import (
    load_schema,
    validate_config,
    validate_config_dry,
)


# ── Schema loading ───────────────────────────────────────────────────────


def test_load_schema_from_yaml(tmp_path: Path) -> None:
    f = tmp_path / "schema.yml"
    f.write_text(
        """keys:
  routing_policy.default_budget:
    type: str
    required: true
    ui_group: routing
    description: Default budget mode
    allowed_values: [frugal, balanced, max_quality]
  model_providers.deepseek_api_key:
    type: str
    required: false
    ui_group: credentials
    secret: true
""",
        encoding="utf-8",
    )
    schema = load_schema(f)
    assert len(schema.keys) == 2
    rk = schema.keys["routing_policy.default_budget"]
    assert rk.required is True
    assert rk.allowed_values == ["frugal", "balanced", "max_quality"]

    sk = schema.keys["model_providers.deepseek_api_key"]
    assert sk.secret is True


def test_load_schema_missing_file_returns_empty() -> None:
    schema = load_schema(Path("/nonexistent/schema.yml"))
    assert len(schema.keys) == 0


# ── ConfigKeySchema validation ───────────────────────────────────────────


def test_key_schema_required_missing_is_error() -> None:
    ks = ConfigKeySchema(key="x.y", required=True, type_="str")
    errors = ks.validate_value(None)
    assert len(errors) == 1
    assert "required" in errors[0]


def test_key_schema_type_mismatch_is_error() -> None:
    ks = ConfigKeySchema(key="x.y", type_="int")
    errors = ks.validate_value("not_an_int")
    assert len(errors) == 1
    assert "expected int" in errors[0]


def test_key_schema_allowed_values_rejected() -> None:
    ks = ConfigKeySchema(key="x.y", type_="str", allowed_values=["a", "b"])
    errors = ks.validate_value("c")
    assert len(errors) == 1
    assert "not in allowed" in errors[0]


def test_key_schema_valid_value_no_errors() -> None:
    ks = ConfigKeySchema(key="x.y", type_="str", allowed_values=["frugal", "balanced"])
    assert ks.validate_value("frugal") == []


# ── validate_config ──────────────────────────────────────────────────────


def test_validate_config_all_required_keys_present() -> None:
    schema = ConfigSchema()
    schema.keys["a.required_key"] = ConfigKeySchema(
        key="a.required_key", required=True, type_="str"
    )
    config = {"a": {"required_key": "hello"}}
    errors = validate_config(config, schema)
    assert errors == []


def test_validate_config_missing_required_key() -> None:
    schema = ConfigSchema()
    schema.keys["a.missing"] = ConfigKeySchema(key="a.missing", required=True)
    errors = validate_config({"a": {}}, schema)
    assert len(errors) == 1
    assert "missing" in errors[0]


# ── validate_config_dry ──────────────────────────────────────────────────


def test_validate_config_dry_passes_on_default_config() -> None:
    """Integration: default config should validate cleanly."""
    root = Path(__file__).resolve().parents[1]
    errors = validate_config_dry(root)
    assert errors == [], f"Validation errors: {errors}"


def test_validate_config_dry_with_project_none() -> None:
    """Integration: validate without project should work."""
    root = Path(__file__).resolve().parents[1]
    errors = validate_config_dry(root, project_name=None)
    assert errors == []
