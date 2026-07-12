"""Provider reachability smoke reports for AgentLab acceptance evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _safe_preview(value: str, *, keep: int = 6) -> str | None:
    if not value:
        return None
    return f"{value[:keep]}..." if len(value) > keep else "***"


def build_provider_smoke_report(
    root: Path,
    *,
    provider: str = "deepseek",
    model_override: str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    """Build a non-private provider smoke report without rendering secrets."""
    root = root.resolve()
    from config_loader import load_agentlab_configs
    from llm_provider import generate_text, resolve_env_value
    from schemas import LLMSettings

    configs = load_agentlab_configs(root)
    model_providers = configs.get("model_providers", {}) if isinstance(configs, dict) else {}
    providers = model_providers.get("providers", {}) if isinstance(model_providers, dict) else {}
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    base_url = resolve_env_value(cfg.get("base_url"), "") if cfg else ""
    default_model = resolve_env_value(cfg.get("default_model"), "") if cfg else ""
    model = model_override or default_model
    api_key = resolve_env_value(cfg.get("api_key"), "") if cfg else ""

    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "agentlab_provider_smoke",
        "provider": provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "live": live,
        "provider_configured": bool(cfg),
        "provider_type": cfg.get("type") if cfg else None,
        "base_url_configured": bool(base_url),
        "base_url_preview": _safe_preview(base_url),
        "model_configured": bool(model),
        "model": model or None,
        "default_model": default_model or None,
        "model_override": model_override,
        "api_key_configured": bool(api_key),
        "api_key_value_rendered": False,
        "prompt_class": "non_private_provider_reachability_smoke",
    }
    if not cfg:
        report.update({"status": "blocked", "reason": "provider_not_found"})
        return report
    if not (base_url and model and api_key):
        report.update({"status": "blocked", "reason": "provider_config_incomplete"})
        return report
    if not live:
        report.update({"status": "configured", "reason": "dry_run_only"})
        return report

    settings = LLMSettings(
        provider=provider,
        provider_type=cfg.get("type", "openai_compatible"),
        model=model,
        base_url=base_url,
        api_key_configured=True,
        max_output_tokens=32,
    )
    messages = [{"role": "user", "content": "Reply exactly: AGENTLAB_PROVIDER_SMOKE_OK"}]
    try:
        result = generate_text(settings, model_providers, messages, agent_name="ProviderSmoke")
    except Exception as exc:
        report.update(
            {
                "status": "blocked",
                "reason": "provider_call_exception",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return report

    content = (getattr(result, "content", "") or "").strip()
    result_status = getattr(result, "status", "unknown")
    raw_usage = getattr(result, "raw_usage", {}) or {}
    report.update(
        {
            "result_status": result_status,
            "content_present": bool(content),
            "response_preview": content[:100] if content else "",
            "input_tokens": getattr(result, "input_tokens", None),
            "output_tokens": getattr(result, "output_tokens", None),
            "total_tokens": getattr(result, "total_tokens", None),
            "finish_reason": raw_usage.get("finish_reason"),
            "raw_usage_keys": sorted(str(key) for key in raw_usage.keys()),
        }
    )
    result_error = getattr(result, "error", None)
    if result_error:
        report["error"] = result_error
    if result_status == "completed" and "AGENTLAB_PROVIDER_SMOKE_OK" in content:
        report.update({"status": "pass"})
    elif result_status == "completed":
        report.update({"status": "warn", "reason": "provider_connected_but_unexpected_content"})
    else:
        report.update({"status": "blocked", "reason": "provider_call_not_completed"})
    return report


def write_provider_smoke_report(
    root: Path,
    out: Path,
    *,
    provider: str = "deepseek",
    model_override: str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    report = build_provider_smoke_report(root, provider=provider, model_override=model_override, live=live)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return report
