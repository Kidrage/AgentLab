from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skills.registry import (
    ExternalSkill,
    add_or_update_skill,
    assert_skill_dispatchable,
    default_registry,
    import_inventory_records,
    load_skill_registry,
    write_skill_registry,
)


def test_skill_registry_loads_and_saves(tmp_path: Path) -> None:
    registry = default_registry()
    add_or_update_skill(registry, ExternalSkill(
        skill_id="ecc.planner",
        source="ecc",
        source_type="external_agent_pack",
        display_name="ECC Planner",
        capabilities=["planning"],
    ))
    write_skill_registry(tmp_path, registry)
    loaded = load_skill_registry(tmp_path)
    assert loaded["external_skills"][0]["skill_id"] == "ecc.planner"
    assert loaded["external_skills"][0]["enabled"] is False


def test_skill_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    registry = default_registry()
    registry["external_skills"] = [
        {"skill_id": "ecc.planner", "source": "ecc"},
        {"skill_id": "ecc.planner", "source": "ecc"},
    ]
    with pytest.raises(ValueError):
        write_skill_registry(tmp_path, registry)


def test_imported_external_skills_default_disabled() -> None:
    registry = default_registry()
    imported = import_inventory_records(registry, {"source": "ecc", "agents": [{"id": "ecc.planner", "name": "planner", "capabilities": ["planning"]}]})
    assert imported[0]["enabled"] is False
    with pytest.raises(PermissionError):
        assert_skill_dispatchable(registry, "ecc.planner")


def test_unknown_license_requires_review() -> None:
    registry = default_registry()
    skill = add_or_update_skill(registry, ExternalSkill(
        skill_id="ecc.security-reviewer",
        source="ecc",
        source_type="external_agent_pack",
        display_name="ECC Security Reviewer",
    ))
    assert skill["license"]["name"] == "unknown"
    assert skill["license"]["license_review_required"] is True
