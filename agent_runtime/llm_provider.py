"""LLM provider adapters for AgentLab CLI.

The first implementation targets OpenAI-compatible chat completion APIs, which
covers DeepSeek-style endpoints and OpenAI. Imports and network calls happen only
when `generate_text` is called.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from incident_manager import record_incident
from model_resolver import resolve_env_value, resolve_profile_config
from progress_tracker import mark_agent_completed, mark_agent_paused, mark_agent_started
from provider_guard import build_fallback_decision, classify_provider_error, write_user_decision_file
from schemas import LLMCallResult, LLMSettings


def resolve_llm_settings(
    agent_name: str,
    agent_registry: dict,
    model_providers: dict,
    model_profiles: dict,
    model_catalog: dict | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LLMSettings:
    """Resolve provider/model settings for one agent."""
    agent_config = agent_registry.get(agent_name, {})
    profile_name = agent_config.get("model_profile", "")
    profile_defaults = model_profiles.get("defaults", {})
    profile = {
        **profile_defaults,
        **resolve_profile_config(
            profile_name,
            model_profiles=model_profiles,
            model_catalog=model_catalog or {},
            agent_name=agent_name,
        ),
    }

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
    """Call a provider or produce a Codex Plus handoff.

    When agent_name/run_dir/project/task_id are provided, the call is
    tracked via progress_tracker and failures are handled by provider_guard.
    """
    if settings.provider_type == "manual_codex":
        return _codex_handoff(settings, messages, "Provider is configured as manual Codex Plus.")

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

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=settings.temperature,
                top_p=settings.top_p,
                max_tokens=settings.max_output_tokens,
            )
            break
        except Exception as exc:
            last_reason = classify_provider_error(exc)
            last_error = str(exc)
            if last_reason == "provider_error" and attempt < max_retries - 1:
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
                    role_auto_fallback_allowed=role in ("repo_reader", "researcher", "archivist"),
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

    content = response.choices[0].message.content or ""
    usage = response.usage.model_dump() if response.usage else {}

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


def _external_ide_handoff(
    settings: LLMSettings,
    messages: list[dict[str, str]],
    reason: str,
) -> LLMCallResult:
    """Generate a handoff prompt for external IDE AI (Codex, Claude, etc.) to execute the Coder phase.
    
    The key value: external AI receives a complete, structured prompt with all context baked in.
    External AI does NOT need to plan, analyze architecture, or determine scope — AgentLab brain
    (DeepSeek) has already done all of that. External AI only needs to execute what's specified.
    """
    system = messages[0].get("content", "") if messages else ""
    user = messages[1].get("content", "") if len(messages) > 1 else ""

    content = f"""# AgentLab External IDE AI Handoff

## Your Role: Thin Executor
You are an external AI (IDE assistant) receiving a pre-planned task from AgentLab.
AgentLab's brain (DeepSeek) has already done ALL planning, scoping, routing, research,
and architectural decisions. Your ONLY job is to execute the Coder phase.

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
5. After your execution is complete, AgentLab will continue with TesterAuditor → Verifier → Archivist.
6. Do NOT continue with TesterAuditor yourself — AgentLab will handle that.
"""
    return LLMCallResult(
        provider=settings.provider,
        model=settings.model,
        content=content,
        status="fallback_handoff",
        error=reason,
        raw_usage={"external_ide_ai": True, "context_length": len(system) + len(user)},
    )


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
