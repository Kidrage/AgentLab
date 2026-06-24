"""M2-5 Config Center — core unit tests.

Tests schema compliance, key types, required-key presence, layer ordering,
and the validator/loader/resolver contracts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.config_center.loader import (
    _deep_merge,
    _load_yaml,
    load_layered_config,
    resolve_merged_config,
)
from agent_runtime.config_center.schema import (
    ConfigKeySchema,
    ConfigLayer,
    ConfigSchema,
    ConfigValue,
)
from agent_runtime.config_center.validator import (
    load_schema,
    validate_config,
)

ROOT = Path(__file__).resolve().parents[1]


# ── Schema tests ────────────────────────────────────────────────────────


def test_config_layer_order_is_correct() -> None:
    """Layer 12 (runtime) > layer 1 (global), etc."""
    layers = list(ConfigLayer)
    assert layers[0] == ConfigLayer.GLOBAL_DEFAULTS
    assert layers[-1] == ConfigLayer.RUNTIME_TEMPORARY
    assert len(layers) == 12
    # Verify ascending priority
    for i in range(len(layers) - 1):
        assert layers[i].value < layers[i + 1].value


def test_config_value_tracks_source_and_overrides() -> None:
    cv = ConfigValue(
        key="test.key",
        value="hello",
        layer=ConfigLayer.PROJECT_OVERRIDE,
        overridden_from=[ConfigLayer.GLOBAL_DEFAULTS, ConfigLayer.ENVIRONMENT_PROFILE],
    )
    assert cv.is_overridden
    assert cv.source_label == "project_override"
    assert len(cv.overridden_from) == 2


def test_config_value_not_overridden_when_first_layer() -> None:
    cv = ConfigValue(key="x", value=1, layer=ConfigLayer.GLOBAL_DEFAULTS)
    assert not cv.is_overridden
    assert cv.source_label == "global_defaults"


def test_schema_loaded_from_config_center_yml() -> None:
    schema = load_schema(ROOT / "config" / "config_center.yml")
    assert len(schema.keys) > 0, "config_center.yml should define at least one key"
    for k, v in schema.keys.items():
        assert isinstance(k, str)
        assert isinstance(v, ConfigKeySchema)
        assert v.type_ in ("str", "int", "float", "bool", "list", "dict")


def test_schema_key_validation_type_mismatch() -> None:
    schema = ConfigSchema()
    schema.keys["x"] = ConfigKeySchema(key="x", type_="int")
    errors = schema.keys["x"].validate_value("not-an-int")
    assert any("expected int" in e for e in errors)


def test_schema_key_validation_allowed_values() -> None:
    schema = ConfigSchema()
    schema.keys["mode"] = ConfigKeySchema(
        key="mode", type_="str", allowed_values=["a", "b"]
    )
    assert schema.keys["mode"].validate_value("c")
    assert not schema.keys["mode"].validate_value("a")


def test_schema_key_validation_required_missing() -> None:
    schema = ConfigSchema()
    schema.keys["x"] = ConfigKeySchema(key="x", type_="str", required=True)
    errors = schema.keys["x"].validate_value(None)
    assert any("required" in e for e in errors)


# ── Loader tests ─────────────────────────────────────────────────────────


def test_deep_merge_dict_recursion() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99, "z": 4}}
    result = _deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 99, "z": 4}, "b": 3}


def test_deep_merge_override_wins() -> None:
    assert _deep_merge({"k": 1}, {"k": 2}) == {"k": 2}


def test_deep_merge_list_is_copied_not_merged() -> None:
    result = _deep_merge({"k": [1, 2]}, {"k": [3]})
    assert result == {"k": [3]}


def test_yaml_load_missing_file_returns_empty() -> None:
    data = _load_yaml(Path("/nonexistent/path.yml"))
    assert data == {}


def test_layered_config_loads_all_12_layers() -> None:
    layers = load_layered_config(ROOT)
    assert len(layers) == 12
    # Global layer should have namespace-keyed data
    global_data = layers[ConfigLayer.GLOBAL_DEFAULTS]
    assert isinstance(global_data, dict)
    assert len(global_data) > 0, "global defaults should contain namespaced configs"


def test_layered_config_loads_with_project() -> None:
    layers = load_layered_config(ROOT, project_name="AgentLab")
    assert layers[ConfigLayer.PROJECT_OVERRIDE] is not None


def test_merged_config_is_dict() -> None:
    merged = resolve_merged_config(ROOT)
    assert isinstance(merged, dict)
    assert len(merged) > 0


def test_merged_config_contains_namespaced_keys() -> None:
    merged = resolve_merged_config(ROOT)
    # routing_policy should be namespaced from routing_policy.yml
    assert "routing_policy" in merged, f"Expected 'routing_policy' in merged keys: {sorted(merged.keys())[:20]}"


# ── Validator tests ──────────────────────────────────────────────────────


def test_validate_empty_config_against_schema() -> None:
    schema = ConfigSchema()
    schema.keys["must.exist"] = ConfigKeySchema(key="must.exist", type_="str", required=True)
    errors = validate_config({}, schema)
    assert any("must.exist" in e for e in errors)


def test_validate_valid_config_passes() -> None:
    schema = ConfigSchema()
    schema.keys["a.b"] = ConfigKeySchema(key="a.b", type_="str", required=True)
    errors = validate_config({"a": {"b": "ok"}}, schema)
    assert not errors


def test_validate_non_required_missing_is_ok() -> None:
    schema = ConfigSchema()
    schema.keys["opt.key"] = ConfigKeySchema(key="opt.key", type_="str", required=False)
    errors = validate_config({}, schema)
    assert not errors


def test_config_center_schema_loads_keys() -> None:
    """Smoke test: the real config_center.yml schema can be loaded."""
    schema = load_schema(ROOT / "config" / "config_center.yml")
    assert len(schema.keys) >= 5, f"Expected >=5 keys, got {len(schema.keys)}"


def test_secret_keys_are_marked_in_schema() -> None:
    schema = load_schema(ROOT / "config" / "config_center.yml")
    secret_keys = [k for k, v in schema.keys.items() if v.secret]
    assert len(secret_keys) >= 1, "Expected at least one secret key in schema"
    for sk in secret_keys:
        assert "api_key" in sk.lower() or "secret" in sk.lower() or "token" in sk.lower()
