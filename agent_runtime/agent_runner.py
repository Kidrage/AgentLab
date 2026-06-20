"""Single-agent execution helpers for the AgentLab CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

from cli_executor import CliAgentNotAvailable, resolve_cli_profile, run_cli_agent
from config_loader import load_agentlab_configs
from llm_provider import generate_text, resolve_env_value, resolve_llm_settings
from policies import assert_path_allowed
from schemas import LLMSettings, WorkflowPlan


DEFAULT_REPORT_BY_AGENT = {
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

LEGACY_REPORT_BY_AGENT = {
    "Supervisor": "supervisor_plan.md",
    "RepoScout": "reposcout_report.md",
    "Researcher": "research_notes.md",
    "InterfaceMapper": "interface_map.md",
    "PromptEngineer": "coder_prompt.md",
    "Coder": "implementation_report.md",
    "TesterAuditor": "audit_report.md",
    "Archivist": "archive_update.md",
}


def report_path_for_agent(plan: WorkflowPlan, agent_name: str, output: Path | None = None) -> Path:
    run_dir = Path(plan.run_dir)
    if output:
        return output if output.is_absolute() else run_dir / output
    report_path = run_dir / DEFAULT_REPORT_BY_AGENT.get(agent_name, f"{agent_name.lower()}_report.md")
    if report_path.exists():
        return report_path
    legacy_name = LEGACY_REPORT_BY_AGENT.get(agent_name)
    if legacy_name:
        legacy_path = run_dir / legacy_name
        if legacy_path.exists():
            return legacy_path
    return report_path


def is_placeholder_report(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return "TBD" in text or "Placeholder" in text


def load_text_if_exists(path: Path) -> str:
    if not path.exists():
        return f"[missing: {path}]"
    return path.read_text(encoding="utf-8")


def compose_agent_messages(agentlab_root: Path, plan: WorkflowPlan, agent_name: str, output_path: Path) -> list[dict[str, str]]:
    configs = load_agentlab_configs(agentlab_root)
    registry = configs.get("agent_registry", {}).get("agents", {})
    agent_config = registry.get(agent_name, {})
    template_path = assert_path_allowed(agentlab_root / agent_config.get("template_path", ""), agentlab_root)
    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)

    context_files = [
        agentlab_root / "AGENTS.md",
        agentlab_root / "config" / "harness_policy.yml",
        project_root / "project_config.yml",
        project_root / "agent_docs" / "00_CONTEXT_PACK.md",
        project_root / "agent_docs" / "01_REPO_MAP.md",
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
        run_dir / DEFAULT_REPORT_BY_AGENT.get("RepoScout", "02_reposcout_report.md"),
        run_dir / DEFAULT_REPORT_BY_AGENT.get("InterfaceMapper", "04_interface_map.md"),
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Coder", "06_implementation_report.md"),
        run_dir / DEFAULT_REPORT_BY_AGENT.get("TesterAuditor", "08_audit_report.md"),
        run_dir / "verification_report.md",
    ]

    context_sections = []
    for path in context_files:
        if path.exists():
            context_sections.append(f"## {path.name}\n\n{load_text_if_exists(path)}")

    system = f"""
You are the AgentLab {agent_name} agent.

Follow this role template exactly:

{load_text_if_exists(template_path)}

Agent registry settings:

{yaml.safe_dump(agent_config, sort_keys=False)}

Hard execution rules:
- Write a report only; do not claim source files were changed unless they actually were.
- Do not invent command results.
- If information is missing, state what is missing and what should happen next.
- Keep the report concise, auditable, and scoped to this task.
"""

    if agent_name == "Archivist":
        system += """

Archivist durable-memory write rules:
- If this task should update project memory, include AGENTLAB_EDIT blocks after the report.
- Target only paths under agent_docs/ and only files listed in config/memory_policy.yml project_memory.
- Do not claim project memory was updated unless the structured edits are present.
- If you cannot produce safe agent_docs edits, explain the blocker instead of writing a completed archive.
"""

    user = f"""
Prepare the AgentLab report for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path}
- execution_backend: {plan.execution_backend}

Workflow plan summary:

{yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False)}

Available task context:

{chr(10).join(context_sections)}
"""
    return [
        {"role": "system", "content": system.strip()},
        {"role": "user", "content": user.strip()},
    ]


def resolve_agent_settings(
    agentlab_root: Path,
    agent_name: str,
    provider_override: str | None = None,
    model_override: str | None = None,
    profile_config: dict | None = None,
) -> tuple[LLMSettings, dict]:
    configs = load_agentlab_configs(agentlab_root)
    if profile_config:
        providers = configs.get("model_providers", {}).get("providers", {})
        provider_name = provider_override or resolve_env_value(
            profile_config.get("provider"),
            resolve_env_value(configs.get("model_providers", {}).get("defaults", {}).get("provider"), "deepseek"),
        )
        provider_config = providers.get(provider_name, {})
        default_model = resolve_env_value(provider_config.get("default_model"), "")
        model_name = model_override or resolve_env_value(profile_config.get("model"), default_model)
        settings = LLMSettings(
            provider=provider_name,
            provider_type=provider_config.get("type", "openai_compatible"),
            model=model_name or default_model,
            base_url=resolve_env_value(provider_config.get("base_url"), "") or None,
            api_key_configured=bool(resolve_env_value(provider_config.get("api_key"), "")),
            temperature=float(profile_config.get("temperature", 0.2)),
            top_p=float(profile_config.get("top_p", 1.0)),
            max_output_tokens=int(profile_config.get("max_output_tokens", 2000)),
            profile_name=str(profile_config.get("profile", "")),
        )
        return settings, configs
    settings = resolve_llm_settings(
        agent_name=agent_name,
        agent_registry=configs.get("agent_registry", {}).get("agents", {}),
        model_providers=configs.get("model_providers", {}),
        model_profiles=configs.get("model_profiles", {}),
        model_catalog=configs.get("model_catalog", {}),
        provider_override=provider_override,
        model_override=model_override,
    )
    return settings, configs


def run_agent_model(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
    provider_override: str | None = None,
    model_override: str | None = None,
    apply_patches: bool = True,
):
    from operational_uploader import maybe_run_operational_agent

    operational_result = maybe_run_operational_agent(plan, agent_name)
    if operational_result is not None:
        return operational_result

    # ── CLI Agent dispatch (executor_type: cli_agent) ─────────────────────────
    # Attempt to route this agent call through a local CLI agent (e.g. hermes,
    # claude_code) as defined in config/agent_model_profiles.yml.  If the
    # binary is not installed, we fall through to the direct API path below.
    configs_for_cli = load_agentlab_configs(agentlab_root)
    agent_model_profiles = configs_for_cli.get("agent_model_profiles", {})
    budget_mode = getattr(plan, "budget_mode", "balanced") or "balanced"
    agent_role_key = agent_name.lower().replace(" ", "_")
    # Map AgentLab canonical names to profile role keys
    _role_key_map = {
        "supervisor": "supervisor",
        "reposcout": "reposcout",
        "researcher": "researcher",
        "interfacemapper": "interface_mapper",
        "coder": "coder",
        "promptengineer": "execution_prompt_engineer",
        "testerauditor": "tester_auditor",
        "verifier": "verifier",
        "archivist": "archivist",
    }
    agent_role_key = _role_key_map.get(agent_name.lower(), agent_name.lower())
    cli_role_profile = resolve_cli_profile(agent_model_profiles, budget_mode, agent_role_key)
    if cli_role_profile is not None:
        cli_result = run_cli_agent(plan, agent_name, cli_role_profile)
        if not isinstance(cli_result, CliAgentNotAvailable):
            # CLI agent ran (success or failure) — return without touching API.
            return cli_result
        # Binary absent: fall through to direct API path below.
    # ─────────────────────────────────────────────────────────────────────────

    settings, configs = resolve_agent_settings(
        agentlab_root,
        agent_name,
        provider_override,
        model_override,
        profile_config=(plan.model_profiles or {}).get(agent_name),
    )

    # ── Budget enforcement: block before model call if agent exceeds stop threshold ──
    from brain_governor import evaluate_token_status
    token_statuses = evaluate_token_status(plan, agentlab_root)
    agent_tokens = token_statuses.get(agent_name, {})
    if agent_tokens.get("state") == "ask_user":
        from schemas import LLMCallResult
        budget = agent_tokens.get("budget", 0)
        used = agent_tokens.get("used", 0)
        stop_at = agent_tokens.get("stop_at", 0)
        return LLMCallResult(
            provider=settings.provider,
            model=settings.model,
            content=f"# {agent_name} 已超过 token 预算 stop 阈值\n\n"
                    f"- 已使用: {used} tokens\n"
                    f"- 预算: {budget} tokens\n"
                    f"- Stop 阈值: {stop_at} tokens\n\n"
                    f"调用已被硬阻断以避免无限制消耗预算。"
                    f"请用户重配预算或确认继续后再运行。\n",
            status="blocked_user_decision",
            error=f"{agent_name} 已超过 token 预算 stop 阈值 (used={used}, budget={budget}, stop_at={stop_at})",
        )

    messages = compose_agent_messages(agentlab_root, plan, agent_name, output_path)
    result = generate_text(
        settings,
        configs.get("model_providers", {}),
        messages,
        agent_name=agent_name,
        run_dir=str(plan.run_dir),
        project=plan.project,
        task_id=plan.task_id,
        role=_role_for_agent(agent_name),
        route=getattr(plan.route, "agents", []),
    )

    # Apply file edits only when policy explicitly allows direct mutation.
    if _patch_application_enabled(configs, agent_name, apply_patches) and result.status == "completed" and result.content:
        from patch_applicator import apply_all_patches, strip_edit_blocks_from_report

        project_root = Path(plan.project_root)
        allowed_files = _extract_allowed_files(plan)

        patch_results = apply_all_patches(
            llm_output=result.content,
            project_root=project_root,
            allowed_files=allowed_files,
        )

        if patch_results:
            applied = [r for r in patch_results if r.success]
            failed = [r for r in patch_results if not r.success]

            patch_summary_parts = []
            if applied:
                changed = [f"{r.path} (L{r.line_start}-{r.line_end})" for r in applied]
                patch_summary_parts.append(f"Applied {len(applied)} edit(s) to: {', '.join(changed)}")
            if failed:
                errs = [f"{r.path}: {r.error}" for r in failed]
                patch_summary_parts.append(f"Failed {len(failed)} edit(s): {'; '.join(errs)}")

            patch_summary = "\n".join(patch_summary_parts)

            # Append patch application summary to the report
            stripped_report = strip_edit_blocks_from_report(result.content)
            result.content = stripped_report + f"\n\n## Patch Application Results\n\n{patch_summary}\n"

            # Store patch results on the result for CLI reporting
            result.raw_usage = {**result.raw_usage, "patch_applied": len(applied), "patch_failed": len(failed),
                               "patch_details": [r.__dict__ for r in patch_results]}

    if agent_name == "Archivist" and result.status == "completed" and result.content:
        from memory_writer import apply_archivist_memory_edits, format_memory_write_section
        from patch_applicator import strip_edit_blocks_from_report

        memory_summary = apply_archivist_memory_edits(
            agentlab_root=agentlab_root,
            project_root=Path(plan.project_root),
            llm_output=result.content,
        )
        result.content = (
            strip_edit_blocks_from_report(result.content)
            + "\n\n"
            + format_memory_write_section(memory_summary)
        )
        result.raw_usage = {
            **(result.raw_usage or {}),
            "memory_edit_blocks": memory_summary.edit_blocks_found,
            "memory_edits_applied": memory_summary.applied,
            "memory_edits_failed": memory_summary.failed,
            "memory_edit_details": [r.__dict__ for r in memory_summary.results],
        }
        if not memory_summary.ok:
            result.status = "blocked_user_decision"
            result.error = memory_summary.error or "Archivist memory updates were not applied."

    return result


def _extract_allowed_files(plan: WorkflowPlan) -> set[str] | None:
    """Extract Supervisor-approved file paths from the plan, if available."""
    included = plan.included_agents or {}
    coder_config = included.get("Coder", {}) or plan.included_agents.get("Coder", {})
    if not coder_config:
        return None
    allowed = coder_config.get("allowed_files") or coder_config.get("editable_files")
    if allowed and isinstance(allowed, list):
        return {str(f) for f in allowed}
    return None


def _role_for_agent(agent_name: str) -> str:
    return {
        "RepoScout": "repo_reader",
        "Researcher": "researcher",
        "Archivist": "archivist",
    }.get(agent_name, agent_name.lower())


def _patch_application_enabled(configs: dict, agent_name: str, requested: bool) -> bool:
    if not requested or agent_name != "Coder":
        return False
    execution_policy = configs.get("execution_policy", {})
    tier_policy = execution_policy.get("execution_policy", {})
    coder_policy = execution_policy.get("coder_policy", {})
    if coder_policy.get("automatic_patch_application") is True:
        return True
    return tier_policy.get("patch_application_policy") == "apply_directly"
