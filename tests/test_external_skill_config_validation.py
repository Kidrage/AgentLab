from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from atomic_io import atomic_write_yaml, safe_read_yaml
from skills.config_validation import (
    validate_ecc_integration_config,
    validate_external_skill_registry,
    validate_skill_incubation_policy,
)


def test_config_yaml_safe_read_yaml_reads_configs() -> None:
    assert isinstance(safe_read_yaml(ROOT / "config" / "external_skill_registry.yml", default={}), dict)
    assert isinstance(safe_read_yaml(ROOT / "config" / "ecc_integration.yml", default={}), dict)
    assert isinstance(safe_read_yaml(ROOT / "config" / "skill_incubation_policy.yml", default={}), dict)


def test_registry_yaml_round_trip(tmp_path: Path) -> None:
    registry = safe_read_yaml(ROOT / "config" / "external_skill_registry.yml", default={})
    path = tmp_path / "registry.yml"
    atomic_write_yaml(path, registry)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["external_skills"][0]["skill_id"] == registry["external_skills"][0]["skill_id"]
    assert loaded["external_skills"][0]["license"]["license_review_required"] is True


def test_config_validator_detects_duplicate_skill_id() -> None:
    messages = validate_external_skill_registry({"external_skills": [{"skill_id": "ecc.planner"}, {"skill_id": "ecc.planner"}]})
    assert any("duplicate skill_id" in message for message in messages)


def test_incubation_policy_budget_type_error_detected() -> None:
    messages = validate_skill_incubation_policy({"skill_incubation": {"budget": {"max_incubation_cost_usd_per_task": "cheap"}, "forbidden_outputs": ["copied_external_source_code", "secrets", "private_tokens"]}})
    assert any("budget.max_incubation_cost_usd_per_task" in message for message in messages)


def test_unknown_license_missing_review_flag_warns() -> None:
    messages = validate_external_skill_registry({"external_skills": [{"skill_id": "ecc.planner", "source": "ecc", "integration_mode": "inventory_only", "enabled": False, "license": {"name": "unknown"}}]})
    assert any("unknown license requires" in message for message in messages)


def test_ecc_and_incubation_validators_cover_forbidden_outputs() -> None:
    assert validate_ecc_integration_config({"ecc": {"enabled": False, "mode": "inventory_only", "import_policy": {"default_enabled": False, "allow_commands": False, "allow_hooks": False, "allow_mcp_servers": False}}}) == []
    messages = validate_skill_incubation_policy({"skill_incubation": {"budget": {"max_incubation_cost_usd_per_task": 1, "max_incubation_tokens_per_task": 10, "max_candidates_per_task": 1}, "forbidden_outputs": []}})
    assert any("copied_external_source_code" in message for message in messages)