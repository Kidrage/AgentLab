"""LLM provider adapters for AgentLab CLI.

The first implementation targets OpenAI-compatible chat completion APIs, which
covers DeepSeek-style endpoints and OpenAI. Imports and network calls happen only
when `generate_text` is called.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from incident_manager import record_incident
from model_resolver import resolve_env_value, resolve_profile_config
from progress_tracker import mark_agent_completed, mark_agent_paused, mark_agent_started
from provider_guard import build_fallback_decision, classify_provider_error, is_retryable, write_user_decision_file
from schemas import LLMCallResult, LLMSettings


def resolve_llm_settings(
    agent_name: str,
    model_providers: dict,
    agent_model_profiles: dict,
    model_catalog: dict | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LLMSettings:
    """Resolve provider/model settings for one agent."""
    profile = resolve_profile_config(
        model_catalog=model_catalog or {},
        agent_name=agent_name,
        agent_model_profiles=agent_model_profiles,
    )

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
        profile_name=str(profile.get("profile", "")),
    )


def _provider_secret(model_providers: dict, provider_name: str) -> str:
    provider_config = model_providers.get("providers", {}).get(provider_name, {})
    return resolve_env_value(provider_config.get("api_key"), "")


def _consume_streaming_chat_completion(stream: Any) -> Any:
    content_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            try:
                usage = chunk.usage.model_dump()
            except Exception:
                usage = {}
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        finish_reason = getattr(choices[0], "finish_reason", None) or finish_reason
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue
        piece = getattr(delta, "content", None)
        if piece:
            content_parts.append(piece)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="".join(content_parts)), finish_reason=finish_reason)],
        usage=SimpleNamespace(model_dump=lambda: usage) if usage else None,
    )


def build_fallback_provider_chain(
    model_providers: dict,
    provider_name: str,
    *,
    max_depth: int = 4,
) -> list[dict]:
    """Build a loop-safe fallback chain from model_providers.yml.

    The runtime config stores fallback links on each provider, but callers do
    not always pass an explicit fallback list. This helper turns the configured
    `fallback_provider` chain into concrete provider descriptors so provider
    guard decisions can actually retry a recoverable stage.
    """
    providers = model_providers.get("providers", {}) or {}
    chain: list[dict] = []
    visited = {provider_name}
    current = provider_name

    for _ in range(max_depth):
        current_config = providers.get(current, {}) or {}
        fallback_name = resolve_env_value(current_config.get("fallback_provider"), "")
        if not fallback_name:
            fallback_name = resolve_env_value(model_providers.get("defaults", {}).get("fallback_provider"), "")
        if not fallback_name or fallback_name in visited or fallback_name not in providers:
            break

        fallback_config = providers[fallback_name]
        chain.append(
            {
                "key": fallback_name,
                "model": resolve_env_value(fallback_config.get("default_model"), ""),
                "base_url": resolve_env_value(fallback_config.get("base_url"), "") or None,
                "provider_type": fallback_config.get("type", "openai_compatible"),
                "note": f"configured fallback for {current}",
            }
        )
        visited.add(fallback_name)
        current = fallback_name
    return chain


def generate_text(
    settings: LLMSettings,
    model_providers: dict,
    messages: list[dict[str, str]],
    *,
    agent_name: str = "",
    run_dir: str = "",
    project: str = "",
    task_id: str = "",
    role: str = "",
    risk_level: str = "R1",
    fallback_providers: list[dict] | None = None,
    route: list[str] | None = None,
) -> LLMCallResult:
    """Call a provider or produce a declared external-worker handoff.

    When agent_name/run_dir/project/task_id are provided, the call is
    tracked via progress_tracker and failures are handled by provider_guard.
    """
    if settings.provider_type == "external_ide_ai":
        return _external_ide_handoff(settings, messages, "Provider is configured as External IDE AI. AgentLab brain handles planning; external AI executes.")

    if settings.provider_type != "openai_compatible":
        raise ValueError(f"Unsupported provider type: {settings.provider_type}")

    if fallback_providers is None:
        fallback_providers = build_fallback_provider_chain(model_providers, settings.provider)

    api_key = _provider_secret(model_providers, settings.provider)
    if not api_key:
        return _fallback_or_raise(settings, model_providers, messages, "missing_api_key", "Missing API key.")

    from openai import OpenAI

    client_kwargs: dict[str, str] = {"api_key": api_key}
    if settings.base_url:
        client_kwargs["base_url"] = settings.base_url
    request_timeout = float(os.getenv("AGENTLAB_LLM_TIMEOUT_SECONDS", "120"))
    client = OpenAI(timeout=request_timeout, **client_kwargs)

    max_retries = 3
    retry_delays = [1.0, 2.0, 3.0]
    last_error = ""
    last_reason = ""

    # --- progress tracking: mark agent started ---
    run_d = Path(run_dir) if run_dir else None
    if run_d and agent_name:
        mark_agent_started(run_d, agent_name, settings.provider, settings.model)

    request_payload: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_output_tokens,
    }
    if settings.provider == "deepseek" and agent_name in {"Writer", "ArtifactProducer", "Scribe", "ProviderSmoke"}:
        request_payload["extra_body"] = {"thinking": {"type": "disabled"}}
        request_payload["stream"] = True

    provider_config = (model_providers.get("providers") or {}).get(
        settings.provider,
        {},
    )
    explicitly_silent_failure_classes = {
        str(item) for item in provider_config.get("fallback_on") or []
    }
    provider_silent_fallback_allowed = (
        provider_config.get("unavailable_action") == "fallback_silent"
        and provider_config.get("requires_user_approval_before_fallback") is False
    )
    # Role identity alone never authorizes a provider-surface change. A provider
    # must explicitly opt into silent fallback for this exact failure class.
    role_may_use_silent_fallback = role in (
        "repo_reader",
        "researcher",
        "archivist",
    )
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**request_payload)
            if request_payload.get("stream"):
                response = _consume_streaming_chat_completion(response)
            break
        except Exception as exc:
            last_reason = classify_provider_error(exc)
            last_error = str(exc)
            role_auto_fallback_allowed = (
                role_may_use_silent_fallback
                and provider_silent_fallback_allowed
                and last_reason in explicitly_silent_failure_classes
            )
            retry_same_provider = last_reason == "provider_error" or (
                is_retryable(last_reason) and not role_auto_fallback_allowed
            )
            if retry_same_provider and attempt < max_retries - 1:
                time.sleep(retry_delays[min(attempt, len(retry_delays) - 1)])
                continue
            # --- Provider guard: record incident + build fallback decision ---
            if run_d and agent_name:
                call_id = ""
                try:
                    record_incident(
                        run_d, project, task_id, agent_name,
                        settings.provider, settings.model,
                        last_reason, last_error, call_id,
                    )
                except Exception:
                    pass  # best-effort

                # Build fallback decision
                decision = build_fallback_decision(
                    agent_name=agent_name,
                    provider_key=settings.provider,
                    error_class=last_reason,
                    error_message=last_error,
                    role_auto_fallback_allowed=role_auto_fallback_allowed,
                    risk_level=risk_level,
                    fallback_providers=fallback_providers,
                )

                if decision["action"] == "switch_provider":
                    # Auto-fallback: retry immediately with the next provider.
                    if fallback_providers and decision["to_provider"]:
                        fb = fallback_providers[0]
                        new_settings = LLMSettings(
                            provider=fb.get("key", ""),
                            provider_type=fb.get("provider_type", "openai_compatible"),
                            model=fb.get("model", settings.model),
                            base_url=fb.get("base_url"),
                            api_key_configured=bool(_provider_secret(model_providers, fb.get("key", ""))),
                            temperature=settings.temperature,
                            top_p=settings.top_p,
                            max_output_tokens=settings.max_output_tokens,
                            profile_name=settings.profile_name,
                        )
                        fallback_result = generate_text(
                            new_settings,
                            model_providers,
                            messages,
                            agent_name=agent_name,
                            run_dir=run_dir,
                            project=project,
                            task_id=task_id,
                            role=role,
                            risk_level=risk_level,
                            fallback_providers=fallback_providers[1:],
                            route=route,
                        )
                        fallback_result.fallback_from = settings.provider
                        fallback_result.raw_usage = {
                            **(fallback_result.raw_usage or {}),
                            "auto_fallback": True,
                            "fallback_from": settings.provider,
                            "fallback_to": fb.get("key", ""),
                            "fallback_reason": last_reason,
                        }
                        return fallback_result
                elif decision["action"] == "pause_for_user":
                    mark_agent_paused(run_d, agent_name, f"{last_reason} on {settings.provider}")
                    write_user_decision_file(
                        run_d, project, task_id, agent_name, role,
                        settings.provider, last_reason, last_error,
                        completed_agents=[], pending_agents=route or [],
                        fallback_providers=fallback_providers,
                    )
                    return LLMCallResult(
                        provider=settings.provider,
                        model=settings.model,
                        content=decision["message"],
                        status="blocked_user_decision",
                        error=last_error,
                        raw_usage={"blocked": True, "reason": last_reason},
                    )
                elif decision["action"] == "replan_required":
                    return LLMCallResult(
                        provider=settings.provider,
                        model=settings.model,
                        content=decision["message"],
                        status="blocked_user_decision",
                        error=last_error,
                        raw_usage={"replan_required": True, "reason": last_reason},
                    )

            return _fallback_or_raise(settings, model_providers, messages, last_reason, last_error)

    choice = response.choices[0]
    content = choice.message.content or ""
    usage = response.usage.model_dump() if response.usage else {}
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason:
        usage.setdefault("finish_reason", finish_reason)
    if usage:
        usage.setdefault("usage_source", "api_usage")
        usage.setdefault("exact_usage_available", True)
    if request_payload.get("stream"):
        usage.setdefault("streaming", True)

    report_names = {
        "Supervisor": "01_supervisor_plan.md",
        "RepoScout": "02_reposcout_report.md",
        "Researcher": "03_research_notes.md",
        "InterfaceMapper": "04_interface_map.md",
        "PromptEngineer": "05_coder_prompt.md",
        "Coder": "06_implementation_report.md",
        "TesterAuditor": "08_audit_report.md",
        "Verifier": "verification_report.md",
        "Archivist": "09_archive_update.md",
    }

    # --- progress tracking: mark agent completed ---
    if run_d and agent_name:
        try:
            mark_agent_completed(
                run_d, agent_name, f"runs/{task_id}/{report_names.get(agent_name, agent_name.lower() + '_report.md')}",
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
        except Exception:
            pass  # best-effort

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
    return classify_provider_error(exc)  # delegate to provider_guard


def _fallback_or_raise(
    settings: LLMSettings,
    model_providers: dict,
    messages: list[dict[str, str]],
    reason: str,
    error: str,
) -> LLMCallResult:
    provider_config = model_providers.get("providers", {}).get(settings.provider, {})
    requires_approval = bool(provider_config.get("requires_user_approval_before_fallback", False))
    unavailable_action = provider_config.get("unavailable_action", "")
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

AgentLab policy does not permit an undeclared worker or model to take over this
role. Ask the user whether to:

1. Pause and retry after the configured provider is available.
2. Approve a declared capacity route or explicit task policy change.
""",
            status="blocked_user_decision",
            error=f"{reason}. {error}",
            raw_usage={"blocked": True, "reason": reason},
        )
    raise RuntimeError(f"{settings.provider} failed without fallback: {reason}. {error}")


def _external_ide_handoff(
    settings: LLMSettings,
    messages: list[dict[str, str]],
    reason: str,
) -> LLMCallResult:
    """Generate a bounded Coder handoff for an explicitly selected IDE worker."""
    system = messages[0].get("content", "") if messages else ""
    user = messages[1].get("content", "") if len(messages) > 1 else ""

    content = f"""# AgentLab External IDE AI Handoff

## Your Role: Thin Executor
You are an external AI (IDE assistant) receiving a pre-planned task from AgentLab.
AgentLab owns planning, scoping, routing, and architectural decisions. Your only
job is to execute the assigned Coder contract.

### What You DO:
- Read the context below and execute exactly what's specified
- Edit files listed in the Supervisor-approved scope
- Write the implementation_report.md back to the task run folder
- Log your actions via `agentlab.sh log-event`

### What You DO NOT Do:
- Do NOT plan, scope, or reroute the task (already done by Supervisor)
- Do NOT analyze the codebase architecture (already done by RepoScout/InterfaceMapper)
- Do NOT evaluate whether the approach is correct (Supervisor approved it)
- Do NOT add features outside the specified scope

### Why This Saves You Tokens:
All reasoning/planning/scoping work is already complete. You receive a flat
execution-only context, eliminating the need to read and analyze the full
project. Protocol version: 1.1.

---

## System Context (AgentLab Configuration)

{system}

---

## User Task Context (What To Execute)

{user}

---

## Execution Protocol

1. Read the sections above to understand the task scope.
2. Execute the Coder phase (edit files, run commands).
3. Write implementation_report.md to the task run folder.
4. Log events:
   ```bash
   ./agentlab.sh log-event --project <Project> --task-id <task> --agent Coder \
     --summary "brief summary" --files-changed "file1.ts,file2.js" --commands-run "cmd1,cmd2"
   ```
5. After your execution is complete, AgentLab will continue the configured route.
6. Do not execute any later role yourself.
"""
    return LLMCallResult(
        provider=settings.provider,
        model=settings.model,
        content=content,
        status="fallback_handoff",
        error=reason,
        raw_usage={"external_ide_ai": True, "context_length": len(system) + len(user)},
    )
