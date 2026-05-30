"""Single-agent execution helpers for the AgentLab CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

from config_loader import load_agentlab_configs
from llm_provider import generate_text, resolve_llm_settings
from policies import assert_path_allowed
from schemas import LLMSettings, WorkflowPlan


DEFAULT_REPORT_BY_AGENT = {
    "Supervisor": "supervisor_plan.md",
    "RepoScout": "reposcout_report.md",
    "Researcher": "research_notes.md",
    "InterfaceMapper": "interface_map.md",
    "Coder": "implementation_report.md",
    "CodexPromptGenerator": "codex_prompt.md",
    "TesterAuditor": "audit_report.md",
    "Verifier": "verification_report.md",
    "Archivist": "archive_update.md",
}


def report_path_for_agent(plan: WorkflowPlan, agent_name: str, output: Path | None = None) -> Path:
    run_dir = Path(plan.run_dir)
    if output:
        return output if output.is_absolute() else run_dir / output
    return run_dir / DEFAULT_REPORT_BY_AGENT.get(agent_name, f"{agent_name.lower()}_report.md")


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
        project_root / "project_config.yml",
        project_root / "agent_docs" / "00_CONTEXT_PACK.md",
        project_root / "agent_docs" / "01_REPO_MAP.md",
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / "supervisor_plan.md",
        run_dir / "reposcout_report.md",
        run_dir / "implementation_report.md",
        run_dir / "validation_report.md",
        run_dir / "audit_report.md",
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
) -> tuple[LLMSettings, dict]:
    configs = load_agentlab_configs(agentlab_root)
    settings = resolve_llm_settings(
        agent_name=agent_name,
        agent_registry=configs.get("agent_registry", {}).get("agents", {}),
        model_providers=configs.get("model_providers", {}),
        model_profiles=configs.get("model_profiles", {}),
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
    settings, configs = resolve_agent_settings(agentlab_root, agent_name, provider_override, model_override)
    messages = compose_agent_messages(agentlab_root, plan, agent_name, output_path)
    result = generate_text(settings, configs.get("model_providers", {}), messages)

    # Apply file edits if the LLM included structured edit blocks
    if apply_patches and result.status == "completed" and result.content:
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
