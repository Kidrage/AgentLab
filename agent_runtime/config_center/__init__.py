"""M2-5 Config Center — transparent, layered, validated configuration."""

from agent_runtime.config_center.schema import ConfigLayer, ConfigKeySchema, ConfigSchema, ConfigValue
from agent_runtime.config_center.loader import load_layered_config, resolve_merged_config, _deep_merge
from agent_runtime.config_center.validator import load_schema, validate_config, validate_config_dry
from agent_runtime.config_center.resolver import resolve_key, resolve_all_keys
from agent_runtime.config_center.diff import ConfigDiff, DiffEntry, diff_configs, project_diff
from agent_runtime.config_center.profile import load_profiles, apply_profile, get_active_profile
from agent_runtime.config_center.secrets_redaction import redact_config, redact_config_value, is_secret_key, REDACTED_PLACEHOLDER
from agent_runtime.config_center.renderer import (
    render_config_list,
    render_config_get,
    render_diff,
    render_validation,
    render_profiles,
)

__all__ = [
    # Schema
    "ConfigLayer",
    "ConfigKeySchema",
    "ConfigSchema",
    "ConfigValue",
    # Loader
    "load_layered_config",
    "resolve_merged_config",
    "_deep_merge",
    # Validator
    "load_schema",
    "validate_config",
    "validate_config_dry",
    # Resolver
    "resolve_key",
    "resolve_all_keys",
    # Diff
    "ConfigDiff",
    "DiffEntry",
    "diff_configs",
    "project_diff",
    # Profile
    "load_profiles",
    "apply_profile",
    "get_active_profile",
    # Secrets
    "redact_config",
    "redact_config_value",
    "is_secret_key",
    "REDACTED_PLACEHOLDER",
    # Renderer
    "render_config_list",
    "render_config_get",
    "render_diff",
    "render_validation",
    "render_profiles",
]
