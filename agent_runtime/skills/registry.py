"""External Skill Registry.

The registry is intentionally metadata-only. It can import and manage external
skill descriptions, but it never executes external harnesses, hooks, commands,
or MCP servers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_yaml, safe_read_yaml
from state_store import utc_now

try:  # Support both package and direct agent_runtime path imports in tests.
    from skills.risk import default_risk, license_requires_review, normalize_source
except ImportError:  # pragma: no cover
    from .risk import default_risk, license_requires_review, normalize_source


REGISTRY_REL_PATH = Path("config/external_skill_registry.yml")


@dataclass
class ExternalSkill:
    skill_id: str
    source: str
    source_type: str
    display_name: str
    integration_mode: str = "inventory_only"
    enabled: bool = False
    capabilities: list[str] = field(default_factory=list)
    suitable_task_types: list[str] = field(default_factory=list)
    risk: dict[str, Any] = field(default_factory=default_risk)
    license: dict[str, Any] = field(default_factory=lambda: {
        "name": "unknown",
        "source_url": None,
        "compatible_for_internal_distillation": "review_required",
    })
    cost: dict[str, Any] = field(default_factory=lambda: {
        "billing_mode": "external_harness",
        "token_visibility": "unknown",
        "expected_cost_tier": "unknown",
    })
    fallback: dict[str, Any] = field(default_factory=lambda: {
        "internal_skill": None,
        "api_model_fallback": "qwen3.6-plus",
    })
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "skill_id": self.skill_id,
            "source": normalize_source(self.source),
            "source_type": self.source_type,
            "display_name": self.display_name,
            "integration_mode": self.integration_mode,
            "enabled": bool(self.enabled),
            "capabilities": list(self.capabilities),
            "suitable_task_types": list(self.suitable_task_types),
            "risk": dict(self.risk or {}),
            "license": dict(self.license or {}),
            "cost": dict(self.cost or {}),
            "fallback": dict(self.fallback or {}),
            "notes": list(self.notes),
        }
        if license_requires_review(data["license"]):
            data["license"]["license_review_required"] = True
        return data


def default_registry() -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": 1,
        "external_skills": [],
        "metadata": {
            "owner": "AgentLab",
            "created_at": now,
            "updated_at": now,
            "notes": "External skills are disabled by default and inventory-only unless explicitly enabled by policy.",
        },
    }


def registry_path(agentlab_root: Path) -> Path:
    return agentlab_root / REGISTRY_REL_PATH


def load_skill_registry(agentlab_root: Path, path: Path | None = None) -> dict[str, Any]:
    data = safe_read_yaml(path or registry_path(agentlab_root), default={}) or {}
    if not isinstance(data, dict) or not data:
        data = default_registry()
    data.setdefault("schema_version", 1)
    data.setdefault("external_skills", [])
    data.setdefault("metadata", {})
    return data


def write_skill_registry(agentlab_root: Path, registry: dict[str, Any], path: Path | None = None) -> Path:
    validate_unique_skill_ids(registry)
    registry.setdefault("metadata", {})["updated_at"] = utc_now()
    out = path or registry_path(agentlab_root)
    atomic_write_yaml(out, registry)
    return out


def validate_unique_skill_ids(registry: dict[str, Any]) -> None:
    seen: set[str] = set()
    for skill in registry.get("external_skills", []) or []:
        skill_id = str(skill.get("skill_id") or "").strip()
        if not skill_id:
            raise ValueError("External skill missing skill_id.")
        if skill_id in seen:
            raise ValueError(f"Duplicate external skill_id: {skill_id}")
        seen.add(skill_id)


def get_skill(registry: dict[str, Any], skill_id: str) -> dict[str, Any] | None:
    for skill in registry.get("external_skills", []) or []:
        if skill.get("skill_id") == skill_id:
            return skill
    return None


def add_or_update_skill(
    registry: dict[str, Any],
    skill: ExternalSkill | dict[str, Any],
    *,
    overwrite: bool = True,
) -> dict[str, Any]:
    item = skill.to_dict() if isinstance(skill, ExternalSkill) else dict(skill)
    item["source"] = normalize_source(item.get("source", "custom_local"))
    item.setdefault("integration_mode", "inventory_only")
    item.setdefault("enabled", False)
    item.setdefault("risk", default_risk())
    item.setdefault("license", {"name": "unknown", "source_url": None, "compatible_for_internal_distillation": "review_required"})
    if license_requires_review(item.get("license")):
        item.setdefault("license", {})["license_review_required"] = True
    skill_id = item.get("skill_id")
    if not skill_id:
        raise ValueError("External skill missing skill_id.")
    skills = registry.setdefault("external_skills", [])
    for idx, existing in enumerate(skills):
        if existing.get("skill_id") == skill_id:
            if not overwrite:
                raise ValueError(f"Duplicate external skill_id: {skill_id}")
            skills[idx] = item
            return item
    skills.append(item)
    validate_unique_skill_ids(registry)
    return item


def disable_skill(registry: dict[str, Any], skill_id: str, reason: str | None = None) -> dict[str, Any]:
    skill = get_skill(registry, skill_id)
    if not skill:
        raise KeyError(f"Unknown external skill: {skill_id}")
    skill["enabled"] = False
    if reason:
        skill.setdefault("notes", []).append(f"Disabled: {reason}")
    return skill


def assert_skill_dispatchable(registry: dict[str, Any], skill_id: str) -> dict[str, Any]:
    skill = get_skill(registry, skill_id)
    if not skill:
        raise KeyError(f"Unknown external skill: {skill_id}")
    if not skill.get("enabled", False):
        raise PermissionError(f"External skill is disabled and cannot be dispatched: {skill_id}")
    return skill


def skill_from_inventory_record(record: dict[str, Any], *, source: str = "ecc") -> ExternalSkill:
    name = str(record.get("name") or record.get("id") or "external-skill")
    skill_id = str(record.get("id") or f"{source}.{name}")
    return ExternalSkill(
        skill_id=skill_id,
        source=source,
        source_type="external_agent_pack",
        display_name=f"{source.upper()} {name.replace('-', ' ').title()}",
        integration_mode="inventory_only",
        enabled=False,
        capabilities=list(record.get("capabilities") or []),
        suitable_task_types=list(record.get("suitable_task_types") or []),
        risk=default_risk(str(record.get("risk_level") or "medium")),
        notes=[f"Imported from {source.upper()} inventory."],
    )


def import_inventory_records(
    registry: dict[str, Any],
    inventory: dict[str, Any],
    *,
    overwrite: bool = True,
    max_imported: int | None = None,
) -> list[dict[str, Any]]:
    imported: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for key in ("agents", "skills"):
        records.extend([r for r in inventory.get(key, []) or [] if isinstance(r, dict)])
    for record in records[: max_imported or len(records)]:
        imported.append(add_or_update_skill(registry, skill_from_inventory_record(record, source=inventory.get("source", "ecc")), overwrite=overwrite))
    return imported
