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
from pathlib import Path
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


def resolve_dynamic_api_model(role_key: str, model_catalog: dict | None, agent_model_profiles: dict | None) -> str | None:
    """Dynamically assign models based on reasoning/context capability and local API key availability."""
    import os
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    has_dashscope = bool(os.getenv("DASHSCOPE_API_KEY"))

    # If no keys are set, fallback to static defaults
    if not has_deepseek and not has_dashscope:
        return None

    if role_key in {"supervisor", "verifier", "tester_auditor"}:
        if has_deepseek:
            return "deepseek_v4_pro"
        elif has_dashscope:
            return "qwen3_7_max_dashscope"
    elif role_key == "coder":
        if has_dashscope:
            return "qwen3_coder_plus_dashscope"
        elif has_deepseek:
            return "deepseek_v4_pro"
    elif role_key in {"reposcout", "interface_mapper", "prompt_engineer"}:
        if has_dashscope:
            return "qwen3_7_max_dashscope"
        elif has_deepseek:
            return "deepseek_v4_pro"
    elif role_key in {"researcher", "archivist"}:
        if has_deepseek:
            return "deepseek_v4_flash"
        elif has_dashscope:
            return "qwen3_6_plus_dashscope"

    return None


def resolve_profile_config(
    profile_name: str,
    *,
    model_profiles: dict[str, Any] | None = None,
    model_catalog: dict[str, Any] | None = None,
    agent_name: str = "",
    agent_model_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a profile name into runtime provider/model settings.

    Legacy ``model_profiles.yml`` entries still win when present. Otherwise the
    resolver accepts either model_catalog keys or legacy aliases.
    """
    profile_name = normalize_profile_ref(profile_name)
    if is_skip_profile(profile_name):
        return {"skip": True, "profile": profile_name, "source": "skip"}

    # 1. Load agent_model_profiles.yml if not provided
    if agent_model_profiles is None:
        import yaml
        try:
            agentlab_root = Path(__file__).resolve().parent.parent
            profiles_path = agentlab_root / "config" / "agent_model_profiles.yml"
            if profiles_path.exists():
                agent_model_profiles = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
        except Exception:
            agent_model_profiles = {}

    # 2. Get active mode and tier
    import os
    try:
        from agent_runtime.cli_executor import budget_mode_to_tier
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from cli_executor import budget_mode_to_tier

    budget_mode = os.getenv("AGENTLAB_BUDGET_MODE", "balanced").lower()
    if profile_name.lower().replace("-", "_") in {"frugal", "balanced", "max_quality", "low_cost", "direct_api_only", "hybrid_agent_executor"}:
        budget_mode = profile_name

    tier = budget_mode_to_tier(budget_mode)
    mode = os.getenv("AGENTLAB_MODE", agent_model_profiles.get("default_mode", "full_cli")).lower()

    # 3. Resolve role key from the unified catalog. VisualReviewer remains a
    # route-specific Reviewer alias rather than a standalone canonical role.
    from agent_runtime.self_evolution.role_catalog import RoleCatalog, role_key as fallback_role_key

    agentlab_root = Path(__file__).resolve().parent.parent
    if agent_name.lower().replace("_", "").replace(" ", "") == "visualreviewer":
        role_key = "visual_reviewer"
    else:
        role_definition = RoleCatalog.load(agentlab_root).get(agent_name)
        role_key = role_definition.key if role_definition else fallback_role_key(agent_name)

    # Compile the dynamic registry selection into a catalog key before reading
    # the retained schema-v4 matrix.  The matrix remains an emergency fallback
    # for installations that have not yet installed the normalized registry.
    try:
        from agent_runtime.runtime_registry import (
            dynamic_runtime_enabled,
            resolve_dynamic_profile,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from runtime_registry import dynamic_runtime_enabled, resolve_dynamic_profile
    dynamic_profile = resolve_dynamic_profile(
        agent_model_profiles,
        agent_role=role_key,
        resolved_mode=mode,
        resolved_tier=tier,
    )
    if dynamic_profile is None and dynamic_runtime_enabled(agent_model_profiles, mode):
        raise RuntimeError(
            "dynamic runtime routing failed closed; legacy full_cli matrix "
            f"was not consulted for role={role_key}, tier={tier}"
        )

    # 4. Lookup config in modes and tiers
    modes = agent_model_profiles.get("modes", {}) or {}
    mode_cfg = modes.get(mode, {}) or {}
    tiers = mode_cfg.get("tiers", {}) or {}
    tier_cfg = tiers.get(tier, {}) or {}
    role_cfg = tier_cfg.get(role_key, {}) or {}

    if isinstance(role_cfg, str) and role_cfg in {"skip", "skip_unless_required"}:
        return {"skip": True, "profile": profile_name, "source": "mode_tier_skip"}

    catalog_key = dynamic_profile.get("default") if dynamic_profile else None
    if isinstance(role_cfg, dict):
        if mode == "full_api" and tier == "full":
            catalog_key = resolve_dynamic_api_model(role_key, model_catalog, agent_model_profiles)
        if not catalog_key:
            catalog_key = role_cfg.get("default")
            if role_cfg.get("executor_type") == "special" and role_cfg.get("provider") == "external_ide_ai":
                catalog_key = "external_ide_ai"

    # Fallback to legacy lookup
    if not catalog_key:
        catalog = model_catalog or {}
        catalog_key = catalog_key_for_profile(profile_name, catalog)

    if catalog_key in SPECIAL_PROFILE_CONFIGS:
        config = SPECIAL_PROFILE_CONFIGS[catalog_key]
        return {**config, "profile": profile_name, "catalog_key": catalog_key}

    catalog = model_catalog or {}
    model_entry = (catalog.get("models", {}) or {}).get(catalog_key)
    if not model_entry:
        catalog_key = LEGACY_PROFILE_ALIASES.get(catalog_key, catalog_key)
        model_entry = (catalog.get("models", {}) or {}).get(catalog_key)

    if not model_entry:
        return {"profile": profile_name, "catalog_key": catalog_key, "unresolved": True}

    runtime_provider = runtime_provider_for_catalog_model(model_entry, agent_name=agent_name)
    max_output = int(model_entry.get("max_output") or 4096)
    temperature = 0.1 if agent_name in {"Coder", "ArtifactProducer", "RepoScout", "InterfaceMapper", "TesterAuditor", "Verifier", "Archivist"} else 0.2
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
        "source": "runtime_registry" if dynamic_profile else "model_catalog_via_mode_tier",
        **({
            "runtime_route_id": dynamic_profile.get("runtime_route_id"),
            "runtime_identity": dynamic_profile.get("runtime_identity"),
            "route_decision": dynamic_profile.get("route_decision"),
        } if dynamic_profile else {}),
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
        "ArtifactProducer": "T3",
        "PromptEngineer": "T3",
        "TesterAuditor": "T4",
        "Verifier": "T4",
        "Archivist": "T5",
    }.get(agent_name, "")
