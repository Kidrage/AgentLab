"""Model profile resolution and configuration checks for AgentLab.

This module is the single bridge between three layers:

- agent_registry.yml: agent-to-profile routing
- model_catalog.yml: model facts and catalog provider names
- model_providers.yml: runtime API provider keys

Catalog providers such as ``dashscope_cn`` are factual/marketplace labels. They
are not runtime provider keys. Runtime calls must resolve to provider keys such
as ``qwen``, ``qwen3``, or ``qwen-coder``.
"""

from __future__ import annotations

import os
from typing import Any


SKIP_PROFILE_VALUES = {"", "skip", "skip_unless_required", "template_only", "null", "None"}

LEGACY_PROFILE_ALIASES = {
    "brain_coordinator": "deepseek_v4_pro",
    "brain_coordinator_l1": "qwen3_6_plus_dashscope",
    "brain_coordinator_maxq": "deepseek_v4_pro",
    "brain_coordinator_frugal": "deepseek_v4_flash",
    "brain_coordinator_qwen": "qwen3_7_max_dashscope",
    "perception_reposcout": "qwen3_6_plus_dashscope",
    "perception_reposcout_l3": "qwen3_7_max_dashscope",
    "perception_reposcout_maxq": "qwen3_7_max_dashscope",
    "perception_reposcout_frugal": "qwen3_6_flash_dashscope",
    "perception_interface": "qwen3_6_plus_dashscope",
    "perception_interface_l3": "qwen3_7_max_dashscope",
    "perception_interface_maxq": "qwen3_7_max_dashscope",
    "perception_interface_frugal": "qwen3_6_flash_dashscope",
    "perception_research": "qwen3_6_flash_dashscope",
    "perception_research_l3": "qwen3_6_plus_dashscope",
    "perception_research_maxq": "qwen3_6_plus_dashscope",
    "execution_coder_api": "qwen3_coder_next_dashscope",
    "execution_coder_maxq": "qwen3_coder_plus_dashscope",
    "execution_external_ide": "external_ide_ai",
    "execution_coder_local": "qwen_local",
    "execution_prompt_engineer": "qwen3_6_plus_dashscope",
    "execution_prompt_engineer_l3": "qwen3_7_max_dashscope",
    "execution_prompt_engineer_maxq": "qwen3_7_max_dashscope",
    "execution_prompt_engineer_frugal": "qwen3_6_flash_dashscope",
    "audit_tester": "qwen3_6_flash_dashscope",
    "audit_tester_l3": "qwen3_6_plus_dashscope",
    "audit_tester_maxq": "qwen3_7_max_dashscope",
    "audit_tester_frugal": "qwen3_6_flash_dashscope",
    "audit_verifier": "qwen3_6_flash_dashscope",
    "audit_verifier_l3": "qwen3_6_plus_dashscope",
    "audit_verifier_maxq": "qwen3_7_max_dashscope",
    "archive_archivist": "qwen3_6_flash_dashscope",
    "archive_archivist_l3": "qwen3_6_plus_dashscope",
    "archive_archivist_maxq": "qwen3_6_plus_dashscope",
    "archive_archivist_plus": "qwen3_6_plus_dashscope",
    "archive_archivist_frugal": "qwen3_6_flash_dashscope",
}

SPECIAL_PROFILE_CONFIGS = {
    "external_ide_ai": {
        "provider": "external_ide_ai",
        "model": "External AI",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 0,
        "tier": "T3",
        "source": "special",
    },
    "qwen_local": {
        "provider": "qwen-local",
        "model": "env:AGENTLAB_LOCAL_CODER_MODEL:qwen3.6-35b-a3b",
        "temperature": 0.1,
        "top_p": 0.95,
        "max_output_tokens": 4096,
        "tier": "T3",
        "source": "special",
    },
}


def resolve_env_value(value: Any, fallback: str = "") -> str:
    """Resolve ``env:NAME`` and ``env:NAME:default`` values."""
    if value is None:
        return fallback
    if isinstance(value, str) and value.startswith("env:"):
        spec = value.split(":", 1)[1]
        if ":" in spec:
            name, default = spec.split(":", 1)
            return os.getenv(name, default or fallback)
        return os.getenv(spec, fallback)
    return str(value)


def normalize_profile_ref(profile_name: Any) -> str:
    """Normalize a profile reference to a string key."""
    if profile_name is None:
        return ""
    return str(profile_name)


def is_skip_profile(profile_name: Any) -> bool:
    """Return true when a route value means the agent should be skipped."""
    return normalize_profile_ref(profile_name) in SKIP_PROFILE_VALUES


def catalog_key_for_profile(profile_name: str, model_catalog: dict[str, Any]) -> str:
    """Return the model_catalog key for either a new or legacy profile name."""
    models = model_catalog.get("models", {}) or {}
    if profile_name in models or profile_name in SPECIAL_PROFILE_CONFIGS:
        return profile_name
    return LEGACY_PROFILE_ALIASES.get(profile_name, profile_name)


def runtime_provider_for_catalog_model(model_entry: dict[str, Any], *, agent_name: str = "") -> str:
    """Map a catalog provider/model into a runtime provider key."""
    catalog_provider = str(model_entry.get("provider", ""))
    model_id = str(model_entry.get("model_id", ""))

    if model_entry.get("runtime_provider"):
        return str(model_entry["runtime_provider"])
    if catalog_provider == "deepseek_official":
        return "deepseek-coder" if agent_name == "Coder" else "deepseek"
    if catalog_provider in {"dashscope_cn", "dashscope_intl"}:
        if model_id.startswith("qwen3-coder"):
            return "qwen-coder"
        if "flash" in model_id:
            return "qwen-flash"
        if model_id.startswith("qwen3.7") or model_id.startswith("qwen-max") or model_id.startswith("qwen3-max"):
            return "qwen3"
        return "qwen"
    return catalog_provider


def resolve_profile_config(
    profile_name: str,
    *,
    model_profiles: dict[str, Any] | None = None,
    model_catalog: dict[str, Any] | None = None,
    agent_name: str = "",
) -> dict[str, Any]:
    """Resolve a profile name into runtime provider/model settings.

    Legacy ``model_profiles.yml`` entries still win when present. Otherwise the
    resolver accepts either model_catalog keys or legacy aliases.
    """
    profile_name = normalize_profile_ref(profile_name)
    if is_skip_profile(profile_name):
        return {"skip": True, "profile": profile_name, "source": "skip"}

    legacy_profiles = (model_profiles or {}).get("profiles", {}) or {}
    legacy_profile = legacy_profiles.get(profile_name)
    if legacy_profile:
        return {**legacy_profile, "profile": profile_name, "source": "legacy_model_profiles"}

    catalog = model_catalog or {}
    catalog_key = catalog_key_for_profile(profile_name, catalog)
    if catalog_key in SPECIAL_PROFILE_CONFIGS:
        config = SPECIAL_PROFILE_CONFIGS[catalog_key]
        return {**config, "profile": profile_name, "catalog_key": catalog_key}

    model_entry = (catalog.get("models", {}) or {}).get(catalog_key)
    if not model_entry:
        return {"profile": profile_name, "catalog_key": catalog_key, "unresolved": True}

    runtime_provider = runtime_provider_for_catalog_model(model_entry, agent_name=agent_name)
    max_output = int(model_entry.get("max_output") or 4096)
    temperature = 0.1 if agent_name in {"Coder", "RepoScout", "InterfaceMapper", "TesterAuditor", "Verifier", "Archivist"} else 0.2
    return {
        "profile": profile_name,
        "catalog_key": catalog_key,
        "catalog_provider": model_entry.get("provider", ""),
        "provider": runtime_provider,
        "model": model_entry.get("model_id", ""),
        "temperature": temperature,
        "top_p": 0.95,
        "max_output_tokens": min(max_output, 8192),
        "context_window": model_entry.get("context_window"),
        "tier": _tier_for_agent(agent_name),
        "source": "model_catalog",
    }


def validate_model_configuration(configs: dict[str, Any]) -> dict[str, Any]:
    """Check provider/model wiring without calling external APIs."""
    providers = (configs.get("model_providers", {}).get("providers", {}) or {})
    model_catalog = configs.get("model_catalog", {}) or {}
    legacy_profiles = configs.get("model_profiles", {}) or {}
    agents = configs.get("agent_registry", {}).get("agents", {}) or {}
    issues: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    for agent_name, cfg in agents.items():
        refs = _profile_refs_for_agent(cfg)
        for origin, ref in refs:
            if is_skip_profile(ref):
                continue
            profile = resolve_profile_config(
                ref,
                model_profiles=legacy_profiles,
                model_catalog=model_catalog,
                agent_name=agent_name,
            )
            provider = profile.get("provider", "")
            resolved.append(
                {
                    "agent": agent_name,
                    "origin": origin,
                    "profile": ref,
                    "provider": provider,
                    "model": profile.get("model", ""),
                    "source": profile.get("source", ""),
                }
            )
            if profile.get("unresolved"):
                issues.append({"severity": "error", "agent": agent_name, "profile": ref, "issue": "unresolved_profile"})
                continue
            if provider not in providers:
                issues.append({"severity": "error", "agent": agent_name, "profile": ref, "provider": provider, "issue": "missing_runtime_provider"})
                continue
            if provider == "openrouter":
                issues.append({"severity": "error", "agent": agent_name, "profile": ref, "provider": provider, "issue": "openrouter_not_allowed"})

    for name, cfg in providers.items():
        cfg_text = str(cfg)
        if "openrouter" in cfg_text.lower():
            issues.append({"severity": "error", "provider": name, "issue": "openrouter_reference_in_provider_config"})
        key = resolve_env_value(cfg.get("api_key"), "")
        if cfg.get("type") == "openai_compatible" and not key and name not in {"openai", "qwen-local"}:
            issues.append({"severity": "warning", "provider": name, "issue": "missing_api_key"})
        if name.startswith("qwen") and "dashscope" not in resolve_env_value(cfg.get("base_url"), "") and name != "qwen-local":
            issues.append({"severity": "error", "provider": name, "issue": "qwen_provider_not_dashscope"})

    default_coder = (
        configs.get("execution_policy", {})
        .get("execution_policy", {})
        .get("default_api_coder", {})
    )
    default_provider = default_coder.get("provider")
    if default_provider and default_provider not in providers:
        issues.append({"severity": "error", "provider": default_provider, "issue": "default_api_coder_provider_not_runtime_provider"})

    return {
        "status": "pass" if not any(i["severity"] == "error" for i in issues) else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "resolved_profiles": resolved,
    }


def _profile_refs_for_agent(agent_config: dict[str, Any]) -> list[tuple[str, str]]:
    refs = []
    if agent_config.get("model_profile"):
        refs.append(("model_profile", str(agent_config["model_profile"])))
    for mode, mapping in (agent_config.get("profile_mapping", {}) or {}).items():
        if isinstance(mapping, dict):
            for size, ref in mapping.items():
                if ref is not None:
                    refs.append((f"profile_mapping.{mode}.{size}", str(ref)))
    return refs


def _tier_for_agent(agent_name: str) -> str:
    return {
        "Supervisor": "T1",
        "RepoScout": "T2",
        "Researcher": "T2",
        "InterfaceMapper": "T2",
        "Coder": "T3",
        "PromptEngineer": "T3",
        "TesterAuditor": "T4",
        "Verifier": "T4",
        "Archivist": "T5",
    }.get(agent_name, "")
