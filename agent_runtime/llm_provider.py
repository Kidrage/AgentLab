"""LLM provider adapters for AgentLab CLI.

The first implementation targets OpenAI-compatible chat completion APIs, which
covers DeepSeek-style endpoints and OpenAI. Imports and network calls happen only
when `generate_text` is called.
"""

from __future__ import annotations

import os
import time
from typing import Any

from schemas import LLMCallResult, LLMSettings


def resolve_env_value(value: Any, fallback: str = "") -> str:
    """Resolve `env:NAME` config values without exposing secrets."""
    if value is None:
        return fallback
    if isinstance(value, str) and value.startswith("env:"):
        spec = value.split(":", 1)[1]
        if ":" in spec:
            name, default = spec.split(":", 1)
            return os.getenv(name, default or fallback)
        return os.getenv(spec, fallback)
    return str(value)


def resolve_llm_settings(
    agent_name: str,
    agent_registry: dict,
    model_providers: dict,
    model_profiles: dict,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LLMSettings:
    """Resolve provider/model settings for one agent."""
    agent_config = agent_registry.get(agent_name, {})
    profile_name = agent_config.get("model_profile", "")
    profile_defaults = model_profiles.get("defaults", {})
    profiles = model_profiles.get("profiles", {})
    profile = {**profile_defaults, **profiles.get(profile_name, {})}

    provider_name = provider_override or resolve_env_value(
        profile.get("provider"),
        resolve_env_value(model_providers.get("defaults", {}).get("provider"), "deepseek"),
    )
    providers = model_providers.get("providers", {})
    provider_config = providers.get(provider_name, {})

    default_model = resolve_env_value(provider_config.get("default_model"), "")
    model_name = model_override or resolve_env_value(profile.get("model"), default_model)
    if not model_name:
        model_name = default_model

    api_key = resolve_env_value(provider_config.get("api_key"), "")
    base_url = resolve_env_value(provider_config.get("base_url"), "")

    return LLMSettings(
        provider=provider_name,
        provider_type=provider_config.get("type", "openai_compatible"),
        model=model_name,
        base_url=base_url or None,
        api_key_configured=bool(api_key),
        temperature=float(profile.get("temperature", 0.2)),
        top_p=float(profile.get("top_p", 1.0)),
        max_output_tokens=int(profile.get("max_output_tokens", 2000)),
        profile_name=profile_name,
    )


def _provider_secret(model_providers: dict, provider_name: str) -> str:
    provider_config = model_providers.get("providers", {}).get(provider_name, {})
    return resolve_env_value(provider_config.get("api_key"), "")


def generate_text(
    settings: LLMSettings,
    model_providers: dict,
    messages: list[dict[str, str]],
) -> LLMCallResult:
    """Call a provider or produce a Codex Plus handoff."""
    if settings.provider_type == "manual_codex":
        return _codex_handoff(settings, messages, "Provider is configured as manual Codex Plus.")

    if settings.provider_type != "openai_compatible":
        raise ValueError(f"Unsupported provider type: {settings.provider_type}")

    api_key = _provider_secret(model_providers, settings.provider)
    if not api_key:
        return _fallback_or_raise(settings, model_providers, messages, "missing_api_key", "Missing API key.")

    from openai import OpenAI

    client_kwargs: dict[str, str] = {"api_key": api_key}
    if settings.base_url:
        client_kwargs["base_url"] = settings.base_url
    client = OpenAI(**client_kwargs)

    # 自动重试：大脑层 DeepSeek 默认重试 3 次，仅全部失败后才要求用户决策
    max_retries = 3
    retry_delays = [1.0, 2.0, 3.0]  # 指数退避
    last_error = ""
    last_reason = ""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=settings.temperature,
                top_p=settings.top_p,
                max_tokens=settings.max_output_tokens,
            )
            # 成功 — 跳出重试循环
            break
        except Exception as exc:
            last_reason = _classify_provider_error(exc)
            last_error = str(exc)
            # 仅对临时性错误（超时、网络）重试；配额/认证错误立即退出
            if last_reason == "provider_error" and attempt < max_retries - 1:
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                time.sleep(delay)
                continue
            # 最后一次尝试或非临时错误
            return _fallback_or_raise(settings, model_providers, messages, last_reason, last_error)

    # 如果重试成功，`response` 已在上面的 try 中赋值

    content = response.choices[0].message.content or ""
    usage = response.usage.model_dump() if response.usage else {}

    return LLMCallResult(
        provider=settings.provider,
        model=settings.model,
        content=content,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        raw_usage=usage,
    )


def _classify_provider_error(exc: Exception) -> str:
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code in {402, 429}:
        return "quota_exceeded"
    if "quota" in text or "balance" in text or "credit" in text or "insufficient" in text:
        return "quota_exceeded"
    if "rate limit" in text or "too many requests" in text:
        return "rate_limited"
    return "provider_error"


def _fallback_or_raise(
    settings: LLMSettings,
    model_providers: dict,
    messages: list[dict[str, str]],
    reason: str,
    error: str,
) -> LLMCallResult:
    provider_config = model_providers.get("providers", {}).get(settings.provider, {})
    fallback_provider = provider_config.get("fallback_provider") or model_providers.get("defaults", {}).get("fallback_provider")
    fallback_provider = resolve_env_value(fallback_provider, "")
    allowed = provider_config.get("fallback_on", [])
    requires_approval = bool(provider_config.get("requires_user_approval_before_fallback", False))
    unavailable_action = provider_config.get("unavailable_action", "")
    if fallback_provider == "codex_plus_manual" and (reason in allowed or not allowed) and not requires_approval:
        fallback_settings = LLMSettings(
            provider="codex_plus_manual",
            provider_type="manual_codex",
            model="Codex Plus",
            profile_name=settings.profile_name,
        )
        return _codex_handoff(
            fallback_settings,
            messages,
            f"{settings.provider} unavailable: {reason}. {error}",
            settings.provider,
        )
    if unavailable_action == "ask_user" or requires_approval:
        return LLMCallResult(
            provider=settings.provider,
            model=settings.model,
            content=f"""# User Decision Required

Status: blocked_user_decision
Reason: {settings.provider} unavailable for required brain work.

Failure class: {reason}

Error:
{error}

AgentLab policy requires DeepSeek to perform the brain/planning/review layer.
Codex must not silently take over this brain stage. Ask the user whether to:

1. Pause and retry after DeepSeek is available.
2. Explicitly change policy for this task and allow Codex manual simulation.
""",
            status="blocked_user_decision",
            error=f"{reason}. {error}",
            raw_usage={"blocked": True, "reason": reason},
        )
    raise RuntimeError(f"{settings.provider} failed without fallback: {reason}. {error}")


def _codex_handoff(
    settings: LLMSettings,
    messages: list[dict[str, str]],
    reason: str,
    fallback_from: str | None = None,
) -> LLMCallResult:
    system = messages[0].get("content", "") if messages else ""
    user = messages[1].get("content", "") if len(messages) > 1 else ""
    content = f"""# Codex Plus Handoff

Status: fallback_handoff
Reason: {reason}

AgentLab cannot execute this stage through a normal API provider. Use this
handoff in the current Codex Plus session, then write the requested report back
into the active task folder.

## System Context

{system}

## User Task Context

{user}
"""
    return LLMCallResult(
        provider=settings.provider,
        model=settings.model,
        content=content,
        status="fallback_handoff",
        fallback_from=fallback_from,
        error=reason,
        raw_usage={"fallback": True, "fallback_from": fallback_from or settings.provider},
    )
