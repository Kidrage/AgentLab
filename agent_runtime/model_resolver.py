"""Model profile resolution and configuration checks for AgentLab.

This module is the single bridge between four current authority layers:

- agent_model_profiles.yml: role backend/model selection
- agent_registry.yml: role identity and permissions
- model_catalog.yml: model facts and catalog provider names
- model_providers.yml: runtime API provider keys

Catalog providers such as ``dashscope_cn`` are factual/marketplace labels. They
are not runtime provider keys. Runtime calls must resolve to provider keys such
as ``qwen``, ``qwen3``, or ``qwen-coder``.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from agent_runtime.role_keys import canonical_role_name, normalize_role_key
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from role_keys import canonical_role_name, normalize_role_key


SKIP_PROFILE_VALUES = {"", "skip", "skip_unless_required", "template_only", "null", "None"}

SPECIAL_PROFILE_CONFIGS = {
    "external_ide_ai": {
        "provider": "external_ide_ai",
        "model": "External AI",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_output_tokens": 0,
        "tier": "special",
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
    """Return an explicit catalog/special key without legacy aliasing."""
    models = model_catalog.get("models", {}) or {}
    if profile_name in models or profile_name in SPECIAL_PROFILE_CONFIGS:
        return profile_name
    return profile_name


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
    profile_name: str = "",
    *,
    model_catalog: dict[str, Any] | None = None,
    agent_name: str = "",
    agent_model_profiles: dict[str, Any] | None = None,
    mode: str | None = None,
    budget_mode: str | None = None,
) -> dict[str, Any]:
    """Resolve one role through the canonical mode/tier backend matrix."""
    profile_name = normalize_profile_ref(profile_name)
    agent_model_profiles = agent_model_profiles or {}
    catalog = model_catalog or {}

    try:
        from agent_runtime.cli_executor import budget_mode_to_tier
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from cli_executor import budget_mode_to_tier

    resolved_mode = str(
        mode
        or os.getenv("AGENTLAB_MODE")
        or agent_model_profiles.get("default_mode")
        or "full_cli"
    ).strip().lower()
    configured_default_tier = str(
        (agent_model_profiles.get("tier_policy", {}) or {}).get(
            "default_tier", "performance"
        )
    )
    resolved_tier = budget_mode_to_tier(
        budget_mode
        or os.getenv("AGENTLAB_BUDGET_MODE")
        or configured_default_tier
    )
    role_key = normalize_role_key(agent_name)
    modes = agent_model_profiles.get("modes", {}) or {}
    mode_cfg = modes.get(resolved_mode, {}) or {}
    tiers = mode_cfg.get("tiers", {}) or {}
    tier_cfg = tiers.get(resolved_tier, {}) or {}
    role_cfg = tier_cfg.get(role_key)
    canonical_profile = f"{resolved_mode}.{resolved_tier}.{role_key}"

    if isinstance(role_cfg, str) and role_cfg in {"skip", "skip_unless_required"}:
        return {
            "skip": True,
            "profile": canonical_profile,
            "role_key": role_key,
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
            "source": "agent_model_profiles_v4",
        }

    catalog_key = ""
    if isinstance(role_cfg, dict):
        catalog_key = str(role_cfg.get("default") or "")
        if role_cfg.get("executor_type") == "special":
            catalog_key = str(role_cfg.get("provider") or catalog_key)
    elif not agent_name and profile_name:
        # Explicit catalog lookup remains available for small utility callers;
        # normal role execution never reaches this compatibility branch.
        catalog_key = catalog_key_for_profile(profile_name, catalog)
        canonical_profile = profile_name
        role_cfg = {}
    else:
        return {
            "profile": canonical_profile,
            "role_key": role_key,
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
            "unresolved": True,
            "issue": "missing_canonical_role_profile",
            "source": "agent_model_profiles_v4",
        }

    if catalog_key in SPECIAL_PROFILE_CONFIGS:
        return {
            **SPECIAL_PROFILE_CONFIGS[catalog_key],
            **dict(role_cfg),
            "profile": canonical_profile,
            "catalog_key": catalog_key,
            "role_key": role_key,
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
        }

    model_entry = (catalog.get("models", {}) or {}).get(catalog_key)
    if not model_entry:
        return {
            "profile": canonical_profile,
            "catalog_key": catalog_key,
            "role_key": role_key,
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
            "unresolved": True,
            "issue": "missing_catalog_model",
            "source": "agent_model_profiles_v4",
        }

    runtime_provider = runtime_provider_for_catalog_model(model_entry, agent_name=agent_name)
    max_output = int(model_entry.get("max_output") or 4096)
    temperature = 0.1 if agent_name in {"Coder", "ArtifactProducer", "RepoScout", "InterfaceMapper", "TesterAuditor", "Verifier", "Archivist"} else 0.2
    return {
        **dict(role_cfg),
        "profile": canonical_profile,
        "catalog_key": catalog_key,
        "catalog_provider": model_entry.get("provider", ""),
        "provider": runtime_provider,
        "model": model_entry.get("model_id", ""),
        "temperature": temperature,
        "top_p": 0.95,
        "max_output_tokens": min(max_output, 8192),
        "context_window": model_entry.get("context_window"),
        "tier": resolved_tier,
        "role_key": role_key,
        "resolved_mode": resolved_mode,
        "resolved_tier": resolved_tier,
        "source": "agent_model_profiles_v4",
    }


def validate_model_configuration(configs: dict[str, Any]) -> dict[str, Any]:
    """Check provider/model wiring without calling external APIs."""
    providers = (configs.get("model_providers", {}).get("providers", {}) or {})
    model_catalog = configs.get("model_catalog", {}) or {}
    agent_model_profiles = configs.get("agent_model_profiles", {}) or {}
    agents = configs.get("agent_registry", {}).get("agents", {}) or {}
    issues: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    for mode_name, mode_cfg in (agent_model_profiles.get("modes", {}) or {}).items():
        for tier_name, tier_cfg in (mode_cfg.get("tiers", {}) or {}).items():
            for role_key, role_cfg in tier_cfg.items():
                if isinstance(role_cfg, str) and is_skip_profile(role_cfg):
                    continue
                agent_name = canonical_role_name(str(role_key))
                origin = f"modes.{mode_name}.tiers.{tier_name}.{role_key}"
                if agent_name not in agents:
                    issues.append(
                        {
                            "severity": "error",
                            "agent": agent_name,
                            "origin": origin,
                            "issue": "missing_registry_agent",
                        }
                    )
                    continue
                if not isinstance(role_cfg, dict):
                    issues.append(
                        {
                            "severity": "error",
                            "agent": agent_name,
                            "origin": origin,
                            "issue": "invalid_role_profile",
                        }
                    )
                    continue
                profile = resolve_profile_config(
                    model_catalog=model_catalog,
                    agent_name=agent_name,
                    agent_model_profiles=agent_model_profiles,
                    mode=mode_name,
                    budget_mode=tier_name,
                )
                provider = profile.get("provider", "")
                resolved.append(
                    {
                        "agent": agent_name,
                        "origin": origin,
                        "profile": profile.get("profile", ""),
                        "provider": provider,
                        "model": profile.get("model", ""),
                        "source": profile.get("source", ""),
                    }
                )
                if profile.get("unresolved"):
                    issues.append(
                        {
                            "severity": "error",
                            "agent": agent_name,
                            "origin": origin,
                            "profile": profile.get("profile", ""),
                            "issue": profile.get("issue", "unresolved_profile"),
                        }
                    )
                    continue
                if provider not in providers:
                    issues.append(
                        {
                            "severity": "error",
                            "agent": agent_name,
                            "origin": origin,
                            "provider": provider,
                            "issue": "missing_runtime_provider",
                        }
                    )
                    continue
                if provider == "openrouter":
                    issues.append(
                        {
                            "severity": "error",
                            "agent": agent_name,
                            "origin": origin,
                            "provider": provider,
                            "issue": "openrouter_not_allowed",
                        }
                    )

    for name, cfg in providers.items():
        cfg_text = str(cfg)
        if "openrouter" in cfg_text.lower():
            issues.append({"severity": "error", "provider": name, "issue": "openrouter_reference_in_provider_config"})
        key = resolve_env_value(cfg.get("api_key"), "")
        if cfg.get("type") == "openai_compatible" and not key and name not in {"openai", "qwen-local"}:
            issues.append({"severity": "warning", "provider": name, "issue": "missing_api_key"})
        if name.startswith("qwen") and "dashscope" not in resolve_env_value(cfg.get("base_url"), "") and name != "qwen-local":
            issues.append({"severity": "error", "provider": name, "issue": "qwen_provider_not_dashscope"})

    return {
        "status": "pass" if not any(i["severity"] == "error" for i in issues) else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "resolved_profiles": resolved,
    }
