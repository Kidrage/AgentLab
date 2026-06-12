"""Validation helpers for external skill workflow configuration.

Validators are intentionally side-effect free: they return human-readable
warnings/errors and do not execute external tools or mutate inputs.
"""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_external_skill_registry(registry: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    skills = registry.get("external_skills", []) if isinstance(registry, dict) else []
    if not isinstance(skills, list):
        return ["error: external_skills must be a list"]

    seen: set[str] = set()
    for idx, skill in enumerate(skills):
        if not isinstance(skill, dict):
            messages.append(f"error: external_skills[{idx}] must be a mapping")
            continue
        skill_id = str(skill.get("skill_id") or "").strip()
        if not skill_id:
            messages.append(f"error: external_skills[{idx}] missing skill_id")
            continue
        if skill_id in seen:
            messages.append(f"error: duplicate skill_id: {skill_id}")
        seen.add(skill_id)

        source = str(skill.get("source") or "")
        integration_mode = str(skill.get("integration_mode") or "")
        is_imported_external = source and source != "agentlab_internal"
        if is_imported_external and integration_mode == "inventory_only" and skill.get("enabled") is not False:
            messages.append(f"error: imported external skill must default enabled=false: {skill_id}")

        license_info = skill.get("license") or {}
        if isinstance(license_info, dict) and str(license_info.get("name") or "unknown").lower() == "unknown":
            if license_info.get("license_review_required") is not True:
                messages.append(f"warning: unknown license requires license_review_required=true: {skill_id}")
    return messages


def validate_ecc_integration_config(config: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    ecc = config.get("ecc", config) if isinstance(config, dict) else {}
    if not isinstance(ecc, dict):
        return ["error: ecc config must be a mapping"]
    if ecc.get("enabled") is not False:
        messages.append("warning: ecc.enabled should remain false for inventory-only workflow")
    if ecc.get("mode") != "inventory_only":
        messages.append("error: ecc.mode must be inventory_only")
    import_policy = ecc.get("import_policy") or {}
    for key in ("allow_commands", "allow_hooks", "allow_mcp_servers"):
        if import_policy.get(key) is not False:
            messages.append(f"error: ecc.import_policy.{key} must be false")
    if import_policy.get("default_enabled") is not False:
        messages.append("error: ecc.import_policy.default_enabled must be false")
    return messages


def validate_skill_incubation_policy(policy: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    cfg = policy.get("skill_incubation", policy) if isinstance(policy, dict) else {}
    if not isinstance(cfg, dict):
        return ["error: skill_incubation policy must be a mapping"]
    budget = cfg.get("budget") or {}
    for key in (
        "max_incubation_cost_usd_per_task",
        "max_incubation_tokens_per_task",
        "max_candidates_per_task",
    ):
        if key not in budget or not _is_number(budget.get(key)):
            messages.append(f"error: skill_incubation.budget.{key} must be numeric")
    forbidden = set(cfg.get("forbidden_outputs") or [])
    for required in ("copied_external_source_code", "secrets", "private_tokens"):
        if required not in forbidden:
            messages.append(f"error: skill_incubation.forbidden_outputs missing {required}")
    return messages