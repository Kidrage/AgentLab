"""Single-agent execution helpers for the AgentLab CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from cli_executor import CliAgentNotAvailable, resolve_cli_profile, run_cli_agent
from config_loader import load_agentlab_configs
from llm_provider import generate_text, resolve_env_value, resolve_llm_settings
from policies import assert_path_allowed
from schemas import LLMCallResult, LLMSettings, WorkflowPlan


DEFAULT_REPORT_BY_AGENT = {
    "Supervisor": "01_supervisor_plan.md",
    "RepoScout": "02_reposcout_report.md",
    "Researcher": "03_research_notes.md",
    "InterfaceMapper": "04_interface_map.md",
    "PromptEngineer": "05_coder_prompt.md",
    "Coder": "06_implementation_report.md",
    "ArtifactProducer": "artifact_producer_report.md",
    "Writer": "fiction_draft.md",
    "Reviewer": "fiction_review.yml",
    "Scribe": "continuity_ledger.yml",
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
    "ArtifactProducer": "artifact_producer_report.md",
    "TesterAuditor": "audit_report.md",
    "Archivist": "archive_update.md",
}

ROLE_KEY_BY_AGENT = {
    "supervisor": "supervisor",
    "reposcout": "reposcout",
    "researcher": "researcher",
    "interfacemapper": "interface_mapper",
    "coder": "coder",
    "artifactproducer": "artifact_producer",
    "promptengineer": "prompt_engineer",
    "testerauditor": "tester_auditor",
    "verifier": "verifier",
    "archivist": "archivist",
    "writer": "writer",
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


def _is_context_placeholder(path: Path) -> bool:
    report_names = set(DEFAULT_REPORT_BY_AGENT.values()) | set(LEGACY_REPORT_BY_AGENT.values())
    if path.name not in report_names:
        return False
    return is_placeholder_report(path)


def _story_authority_context_files(project_root: Path, run_dir: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for context_path in (run_dir / "mission_contract.yml", run_dir / "chapter_packet.yml"):
        if not context_path.exists():
            continue
        try:
            contract = yaml.safe_load(context_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for key in ("must_read", "must_read_artifacts"):
            for item in contract.get(key) or []:
                rel = str(item).strip()
                if not rel:
                    continue
                try:
                    path = assert_path_allowed(project_root / rel, project_root)
                except Exception:
                    continue
                if path not in seen:
                    seen.add(path)
                    files.append(path)
    return files


def _skill_context_sections(agentlab_root: Path, plan: WorkflowPlan, agent_name: str) -> list[str]:
    sections: list[str] = []
    selected = (plan.skills or {}).get("selected", [])
    if not isinstance(selected, list):
        return sections
    for item in selected:
        if not isinstance(item, dict):
            continue
        injected_into = item.get("injected_into") or []
        if injected_into and agent_name not in injected_into:
            continue
        raw_path = str(item.get("skill_path") or "").strip()
        if not raw_path:
            continue
        skill_path = Path(raw_path)
        if not skill_path.is_absolute():
            skill_path = agentlab_root / skill_path
        try:
            safe_path = assert_path_allowed(skill_path, agentlab_root)
        except Exception:
            continue
        if safe_path.exists() and safe_path.is_file():
            sections.append(f"## Skill: {item.get('name') or item.get('skill_id')}\n\n{load_text_if_exists(safe_path)}")
    return sections


def writer_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return the local files that contribute to the sealed Writer payload."""
    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    files = [
        agentlab_root / "config" / "agent_registry.yml",
        Path(plan.user_request_path),
        run_dir / "mission_contract.yml",
        run_dir / "chapter_packet.yml",
    ]
    files.extend(_story_authority_context_files(project_root, run_dir))

    configs = load_agentlab_configs(agentlab_root)
    writer_config = (configs.get("agent_registry", {}).get("agents", {}) or {}).get("Writer", {})
    template_text = str(writer_config.get("template_path") or "").strip()
    if template_text:
        files.append(agentlab_root / template_text)

    for item in (plan.skills or {}).get("selected", []) or []:
        if not isinstance(item, dict):
            continue
        injected_into = item.get("injected_into") or []
        if injected_into and "Writer" not in injected_into:
            continue
        raw_path = str(item.get("skill_path") or "").strip()
        if raw_path:
            path = Path(raw_path)
            path = path if path.is_absolute() else agentlab_root / path
            try:
                files.append(assert_path_allowed(path, agentlab_root))
            except Exception:
                continue

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if resolved == output_resolved or resolved in seen or not path.is_file():
            continue
        if _is_context_placeholder(path):
            continue
        seen.add(resolved)
        result.append(path)
    return result


def production_pack_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
) -> list[Path]:
    """Return the minimal files embedded in a production-pack role packet."""
    if (plan.production_pack or {}).get("status") != "synthesis_candidate":
        return []
    if agent_name not in {
        "Supervisor",
        "Researcher",
        "ArtifactProducer",
        "Verifier",
    }:
        return []

    run_dir = Path(plan.run_dir)
    shared = [
        agentlab_root / "config" / "agent_registry.yml",
        Path(plan.user_request_path),
        run_dir / "mission_contract.yml",
        run_dir / "workflow_plan.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
    ]
    role_files = {
        "Supervisor": [
            agentlab_root / "config" / "production_packs.yml",
        ],
        "Researcher": [
            agentlab_root / "config" / "production_packs.yml",
        ],
        "ArtifactProducer": [
            run_dir / "domain_research_brief.md",
            run_dir / "production_pack_research_contract.yml",
            agentlab_root / "config" / "production_packs.yml",
        ],
        "Verifier": [
            run_dir / "domain_research_brief.md",
            run_dir / "production_pack_research_contract.yml",
            run_dir / "artifact_producer_report.md",
            run_dir / "production_pack_proposal.yml",
            run_dir / "domain_memory_contract.yml",
            run_dir / "lifecycle_profile.yml",
            run_dir / "production_pack_output_contract.yml",
        ],
    }
    files = [*shared, *role_files[agent_name]]

    configs = load_agentlab_configs(agentlab_root)
    agent_config = (
        configs.get("agent_registry", {}).get("agents", {}) or {}
    ).get(agent_name, {})
    template_text = str(agent_config.get("template_path") or "").strip()
    if template_text:
        files.append(agentlab_root / template_text)

    for item in (plan.skills or {}).get("selected", []) or []:
        if not isinstance(item, dict):
            continue
        injected_into = item.get("injected_into") or []
        if injected_into and agent_name not in injected_into:
            continue
        raw_path = str(item.get("skill_path") or "").strip()
        if raw_path:
            path = Path(raw_path)
            files.append(path if path.is_absolute() else agentlab_root / path)

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if resolved == output_resolved or resolved in seen or not path.is_file():
            continue
        if _is_context_placeholder(path):
            continue
        seen.add(resolved)
        result.append(path)
    return result


def _production_pack_agent_plan_summary(
    plan: WorkflowPlan,
    agent_name: str,
) -> dict:
    """Return the synthesis contract without local workspace coordinates."""
    summary = _agent_plan_summary(plan, agent_name)
    return {
        "project": summary["project"],
        "task_id": summary["task_id"],
        "agentlab_orchestrator_backend": summary[
            "agentlab_orchestrator_backend"
        ],
        "budget_mode": summary["budget_mode"],
        "budget_profile": summary["budget_profile"],
        "risk_level": summary["risk_level"],
        "route": summary["route"],
        "current_agent": summary["current_agent"],
        "token_budget": summary["token_budget"],
        "validation_gates": summary["validation_gates"],
        "production_pack": summary["production_pack"],
        "missing_inputs": summary["missing_inputs"],
        "selected_skills": summary["selected_skills"],
        "artifact_boundary": {
            "candidate_only": True,
            "write_scope": "current_run_returned_artifacts_only",
            "production_modified": False,
            "auto_promotion": False,
        },
    }


def _sanitize_production_pack_context_text(
    text: str,
    agentlab_root: Path,
    project_root: Path,
    run_dir: Path,
) -> str:
    """Remove local coordinates and credentials before packet assembly."""
    replacements = {
        str(run_dir.resolve(strict=False)): "<RUN_DIR>",
        str(project_root.resolve(strict=False)): "<PROJECT_ROOT>",
        str(agentlab_root.resolve(strict=False)): "<AGENTLAB_ROOT>",
    }
    for local_path, placeholder in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        text = text.replace(local_path, placeholder)
    try:
        from agent_runtime.recovery.redaction import redact_context_text
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from recovery.redaction import redact_context_text
    sanitized, _warnings = redact_context_text(text)
    return sanitized


def _agent_plan_summary(plan: WorkflowPlan, agent_name: str) -> dict:
    """Return a compact execution contract for prompts that do not need full registry data."""
    token_budget = None
    for item in plan.token_budgets:
        phase = getattr(item, "phase", "")
        if agent_name.lower() in phase.lower():
            token_budget = item.model_dump(mode="json")
            break
    current_agent = dict((plan.included_agents or {}).get(agent_name) or {})
    current_agent = {
        key: current_agent.get(key)
        for key in (
            "template_path",
            "model_profile",
            "model_tier",
            "can_edit_source",
            "can_run_shell",
            "can_write_agent_docs",
            "source_write_policy",
            "shell_policy",
            "execution_owner",
            "secondary_executor",
            "local_executor",
            "allowed_backends",
            "required_inputs",
            "required_outputs",
        )
        if key in current_agent
    }
    selected_skills = []
    for item in (plan.skills or {}).get("selected", []) or []:
        if isinstance(item, dict):
            selected_skills.append(
                {
                    "name": item.get("name") or item.get("skill_id"),
                    "injected_into": item.get("injected_into") or [],
                }
            )
    return {
        "project": plan.project,
        "task_id": plan.task_id,
        "agentlab_root": plan.agentlab_root,
        "project_root": plan.project_root,
        "repo_path": plan.repo_path,
        "run_dir": plan.run_dir,
        "user_request_path": plan.user_request_path,
        "agentlab_orchestrator_backend": plan.execution_backend,
        "budget_mode": plan.budget_mode,
        "budget_profile": plan.budget_profile,
        "project_size": plan.project_size,
        "risk_level": plan.risk_level,
        "route": {
            "route_key": plan.route.route_key,
            "task_size": plan.route.task_size,
            "agents": plan.route.agents,
            "skipped_agents": plan.route.skipped_agents,
            "rationale": plan.route.rationale,
        },
        "current_agent": current_agent,
        "token_budget": token_budget,
        "validation_gates": plan.validation_gates,
        "artifact_intent": plan.artifact_intent,
        "production_pack": plan.production_pack,
        "missing_inputs": plan.missing_inputs,
        "selected_skills": selected_skills,
    }


def compose_agent_messages(agentlab_root: Path, plan: WorkflowPlan, agent_name: str, output_path: Path) -> list[dict[str, str]]:
    configs = load_agentlab_configs(agentlab_root)
    registry = configs.get("agent_registry", {}).get("agents", {})
    agent_config = registry.get(agent_name, {})
    template_path = assert_path_allowed(agentlab_root / agent_config.get("template_path", ""), agentlab_root)
    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    production_pack_role_session = (
        (plan.production_pack or {}).get("status") == "synthesis_candidate"
        and agent_name
        in {"Supervisor", "Researcher", "ArtifactProducer", "Verifier"}
    )
    narrative_heavy_audit = plan.route.route_key == "narrative_heavy_audit"

    if agent_name == "Supervisor" and production_pack_role_session:
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            agentlab_root / "config" / "production_packs.yml",
        ]
    elif agent_name == "Writer":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / "chapter_packet.yml",
        ]
        context_files.extend(_story_authority_context_files(project_root, run_dir))
    elif narrative_heavy_audit and agent_name in {"Reviewer", "Scribe", "Verifier"}:
        context_files = [
            Path(plan.user_request_path),
            run_dir / "workflow_plan.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / "mission_contract.yml",
            run_dir / "narrative_audit_manifest.yml",
            run_dir / "narrative_audit_context.md",
            project_root / "project_brain" / "project_fact_snapshot.yml",
            project_root / "project_artifact_index.yml",
        ]
        if agent_name in {"Scribe", "Verifier"}:
            context_files.extend(
                [
                    run_dir / "fiction_review.yml",
                    run_dir / "continuity_failure_report.yml",
                ]
            )
        if agent_name == "Verifier":
            context_files.append(run_dir / "state_transition_proposal.yml")
    elif agent_name in {"Reviewer", "Scribe"}:
        context_files = [
            Path(plan.user_request_path),
            run_dir / "workflow_plan.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / DEFAULT_REPORT_BY_AGENT.get("RepoScout", "02_reposcout_report.md"),
            run_dir / "mission_contract.yml",
            run_dir / "chapter_packet.yml",
            run_dir / "fiction_draft.md",
            run_dir / "fiction_review.yml",
            run_dir / "continuity_ledger.yml",
        ]
        context_files.extend(_story_authority_context_files(project_root, run_dir))
    elif agent_name == "Coder":
        context_files = [
            project_root / "project_config.yml",
            project_root / "agent_docs" / "00_CONTEXT_PACK.md",
            project_root / "agent_docs" / "01_REPO_MAP.md",
            Path(plan.user_request_path),
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / DEFAULT_REPORT_BY_AGENT.get("RepoScout", "02_reposcout_report.md"),
            run_dir / DEFAULT_REPORT_BY_AGENT.get("InterfaceMapper", "04_interface_map.md"),
            run_dir / DEFAULT_REPORT_BY_AGENT.get("TesterAuditor", "08_audit_report.md"),
            run_dir / "verification_report.md",
            run_dir / "artifact_lineage.yml",
            run_dir / "artifact_promotion_plan.yml",
        ]
    elif agent_name == "ArtifactProducer" and (plan.production_pack or {}).get(
        "status"
    ) == "synthesis_candidate":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / "domain_research_brief.md",
            run_dir / "production_pack_research_contract.yml",
            agentlab_root / "config" / "production_packs.yml",
        ]
    elif agent_name == "ArtifactProducer":
        context_files = [
            project_root / "project_config.yml",
            project_root / "project_artifact_index.yml",
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / "artifact_task.yml",
            run_dir / "media_generation_contract.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
        ]
    elif agent_name == "Researcher" and (plan.production_pack or {}).get("status") == "synthesis_candidate":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            agentlab_root / "config" / "production_packs.yml",
        ]
    elif agent_name == "Verifier" and (plan.production_pack or {}).get(
        "status"
    ) == "synthesis_candidate":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / "domain_research_brief.md",
            run_dir / "production_pack_research_contract.yml",
            run_dir / "artifact_producer_report.md",
            run_dir / "production_pack_proposal.yml",
            run_dir / "domain_memory_contract.yml",
            run_dir / "lifecycle_profile.yml",
            run_dir / "production_pack_output_contract.yml",
        ]
    else:
        context_files = [
            agentlab_root / "AGENTS.md",
            agentlab_root / "config" / "repository_handoff_policy.yml",
            agentlab_root / "PROJECT_HANDOFF.md",
            agentlab_root / ".agentlab" / "HandOff.md",
            agentlab_root / "config" / "harness_policy.yml",
            project_root / "project_config.yml",
            project_root / "PROJECT_HANDOFF.md",
            project_root / ".agentlab" / "HandOff.md",
            project_root / "agent_docs" / "HandOff.md",
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
            run_dir / "artifact_lineage.yml",
            run_dir / "artifact_promotion_plan.yml",
            run_dir / "archive_receipt.yml",
        ]

    context_sections = []
    seen_context_texts: set[str] = set()
    output_resolved = output_path.resolve()
    for path in context_files:
        if agent_name == "Writer":
            try:
                path = assert_path_allowed(path, agentlab_root)
            except Exception:
                continue
        try:
            if path.resolve() == output_resolved:
                continue
        except Exception:
            pass
        if _is_context_placeholder(path):
            continue
        if path.exists():
            text = load_text_if_exists(path)
            if production_pack_role_session:
                text = _sanitize_production_pack_context_text(
                    text,
                    agentlab_root,
                    project_root,
                    run_dir,
                )
            if text in seen_context_texts:
                continue
            seen_context_texts.add(text)
            context_sections.append(f"## {path.name}\n\n{text}")
    skill_sections = _skill_context_sections(agentlab_root, plan, agent_name)
    if production_pack_role_session:
        skill_sections = [
            _sanitize_production_pack_context_text(
                section,
                agentlab_root,
                project_root,
                run_dir,
            )
            for section in skill_sections
        ]
    context_sections.extend(skill_sections)

    hard_rules = """
Hard execution rules:
- Before reading repository/project content, discover and read its HandOff. If missing,
  create it with `./agentlab.sh repository-handoff --repo <path> --write` before deep read.
- Safe full path/metadata inventory is required; bulk content reads, binary/secret reads,
  symlink-directory traversal, and dependency-cache scans are forbidden.
- After any material project change and before final reporting, refresh the root-visible,
  local, compatible, and shared-memory HandOff copies.
- Write a report only; do not claim source files were changed unless they actually were.
- Follow `workflow_plan.yml` `artifact_intent`: Coder and ArtifactProducer may write
  candidate deliverables only under the declared candidate directory unless the
  plan declares a production path. If an undeclared production path is needed,
  stop and request a plan revision.
- Archivist must use artifact_lineage.yml and artifact_promotion_plan.yml, archive
  existing production files before replacement, update project_artifact_index.yml,
  and leave archive_receipt.yml as machine-readable evidence.
- Do not invent command results.
- If information is missing, state what is missing and what should happen next.
- Keep the report concise, auditable, and scoped to this task.
"""
    if narrative_heavy_audit and agent_name in {"Reviewer", "Scribe", "Verifier"}:
        hard_rules = """
Narrative heavy audit role-session rules:
- Audit only the injected candidate drafts, ledgers, proposals, and authority memory.
- Return complete full-file AGENTLAB_EDIT blocks for this role's required outputs.
- Keep every output candidate_only: true and production_modified: false.
- Do not emit or modify fiction_draft.md, production/manuscript, project memory, or authority files.
- Reviewer reports findings and continuity failures; it does not rewrite prose.
- Scribe proposes candidate fact-state events; it does not establish canon.
- Verifier emits a revision/rewrite proposal only; it never edits the draft.
- Do not output DSML/tool-call markup or claim unprovided evidence.
"""
    elif agent_name in {"Writer", "Reviewer", "Scribe"}:
        hard_rules = """
Creative writing execution rules:
- Do not request tools, shell commands, file listings, browser access, or repository scans.
- Use only the injected context, mission contract, and story authority files.
- Writer and Scribe must emit AGENTLAB_EDIT blocks only for files listed in mission_contract.yml.
- Reviewer writes a review report only.
- Do not output DSML/tool-call markup.
- If context is incomplete, make the narrowest canon-preserving assumption and continue.
"""
    elif production_pack_role_session:
        hard_rules = """
Production-pack role-session execution rules:
- Use only the exact messages and files embedded in this task packet.
- Do not read or scan the AgentLab repository, project workspace, home directory,
  environment files, credentials, or any path outside this packet.
- Do not mutate the workspace or production. Return stdout only; AgentLab owns
  candidate materialization, validation, and promotion.
- Treat every output as run-local candidate evidence. Never auto-promote it or
  write project memory directly.
- Do not claim commands or file reads unless their evidence is embedded in the
  packet. Local workspace shell commands are forbidden.
- If required private context is missing, state the narrow blocker instead of
  searching for more files.
"""
        if agent_name == "Supervisor":
            hard_rules += """

Production-pack synthesis Supervisor rules:
- Confirm the deterministic mission, synthesis route, candidate-only boundary,
  role order, budget, approval gate, and required returned artifacts.
- Do not inspect repository source, run project commands, or create pack content.
- Assign Researcher, ArtifactProducer, and Verifier using only the embedded
  mission and production-pack contracts.
"""
        elif agent_name == "Researcher":
            hard_rules += """

Production-pack synthesis Researcher rules:
- Research the target domain only to support a new production-pack proposal.
- Public external domain research is allowed when the worker provides it, but
  every external claim remains candidate evidence with explicit provenance.
- Focus on external capability/tool needs, durable memory/state, lifecycle
  phases, quality gates, and failure modes.
- Do not inspect repository source, propose code patches, or request Coder work.
- If live external research is unavailable, state that limitation and provide a
  structured research agenda plus clearly labeled domain assumptions.
"""
        elif agent_name == "ArtifactProducer":
            hard_rules += """

Production-pack synthesis ArtifactProducer rules:
- Produce only the exact candidate files named in Required ArtifactProducer outputs.
- Derive the candidate from the injected research brief and registry contract.
- Do not call media providers, browse, inspect paths, or emit source-code edits.
- Keep candidate_only true, production_modified false, and auto_promote false.
"""
        else:
            hard_rules += """

Production-pack synthesis Verifier rules:
- Verify the returned production_pack_proposal.yml, domain_memory_contract.yml,
  lifecycle_profile.yml, research contract, and output contract as one candidate.
- Reject code-shell lifecycle nodes for non-code domains, unsafe paths, missing
  state/memory records, automatic promotion, or unreviewed external evidence.
- Do not edit candidate files, configuration, project memory, or production.
- Report a clear pass/block decision and every blocking contract issue.
"""
    elif agent_name == "Coder":
        hard_rules += """

Direct API Coder evidence rules:
- This prompt is the direct API text-generation path. You cannot run shell commands,
  list directories, open files, or inspect the repository beyond Available task context.
- In "Files read", list only injected context files, or write "only injected context".
- In "Commands run", write "none by this model call" unless actual command output is
  included in Available task context.
- Do not claim CLI, external_ide, Aider, codex_role_worker, or local tool execution
  unless explicit execution evidence is present in Available task context.
- Candidate implementation is allowed as proposed files or AGENTLAB_EDIT blocks;
  executed command evidence is not.
"""
    elif agent_name == "ArtifactProducer":
        hard_rules += """

Direct API ArtifactProducer rules:
- This prompt is the direct API text-generation path. You cannot run shell
  commands, call media providers, browse, list files, or inspect paths beyond
  Available task context.
- Produce candidate files as complete AGENTLAB_EDIT blocks when the requested
  deliverable is text/YAML/JSON/HTML/CSS/JS or another text artifact.
- Target only paths under artifact_intent.allowed_write_roots, production_pack
  required outputs, or explicitly declared candidate output paths.
- Do not edit repository source code, workflow configuration, project memory, or
  production artifact directories.
- If binary/media generation or external provider execution is required, write
  the required planning/ledger/QC files and report the auth/capability blocker
  instead of pretending the binary was generated.
- In "Commands run", write "none by this model call" unless explicit command
  evidence is present in Available task context.
"""
    elif agent_name == "Researcher" and (plan.production_pack or {}).get("status") == "synthesis_candidate":
        hard_rules += """

Production-pack synthesis Researcher rules:
- Research the target domain only to support a new production-pack proposal.
- Focus on external capability/tool needs, durable memory/state, lifecycle
  phases, quality gates, and failure modes.
- Do not inspect repository source, propose code patches, or request Coder work.
- Do not include implementation reports, repo maps, interface maps, or code
  artifacts in the brief.
- If live external research is unavailable in this execution mode, state that
  limitation and provide a structured research agenda plus domain assumptions.
"""
    elif agent_name == "Verifier" and (plan.production_pack or {}).get(
        "status"
    ) == "synthesis_candidate":
        hard_rules += """

Production-pack synthesis Verifier rules:
- Verify the returned production_pack_proposal.yml, domain_memory_contract.yml,
  lifecycle_profile.yml, research contract, and output contract as one candidate.
- Reject code-shell lifecycle nodes for non-code domains, unsafe paths, missing
  state/memory records, automatic promotion, or unreviewed external evidence.
- Do not edit candidate files, configuration, project memory, or production.
- Report a clear pass/block decision and enumerate every blocking contract issue.
"""

    system = f"""
You are the AgentLab {agent_name} agent.

Follow this role template exactly:

{load_text_if_exists(template_path)}

Agent registry settings:

{yaml.safe_dump(agent_config, sort_keys=False)}

{hard_rules}
"""

    if agent_name == "Archivist":
        system += """

Archivist durable-memory write rules:
- If this task should update project memory, include AGENTLAB_EDIT blocks after the report.
- Target only paths under agent_docs/ and only files listed in config/memory_policy.yml project_memory.
- Do not claim project memory was updated unless the structured edits are present.
- If you cannot produce safe agent_docs edits, explain the blocker instead of writing a completed archive.
"""

    if narrative_heavy_audit and agent_name in {"Reviewer", "Scribe", "Verifier"}:
        from agent_runtime.narrative_heavy_audit import HEAVY_AUDIT_OUTPUTS_BY_AGENT

        required_outputs = HEAVY_AUDIT_OUTPUTS_BY_AGENT[agent_name]
        user = f"""
Narrative heavy audit for:

- project: {plan.project}
- task_id: {plan.task_id}
- role: {agent_name}
- capture_report_path: {output_path.name}

Output contract:

- Do not write a prose wrapper or target capture_report_path.
- Emit exactly one complete full-file AGENTLAB_EDIT block for each required output below and no other edit blocks.
- Every YAML file must set schema_version: 1, candidate_only: true, and production_modified: false.
- fiction_review.yml: status pass|warn|blocked and findings list.
- continuity_failure_report.yml: status pass|warn|blocked, blocking_issue_count integer, and failures list.
- state_transition_proposal.yml: status candidate, requires_user_promotion: true, and events list; every event scope is candidate_only.
- revision_or_rewrite_proposal.yml: status not_required|proposed|blocked, rewrite_required boolean, direct_draft_edits: false, and proposals list.
- Do not emit fiction_draft.md or directly rewrite any chapter.

Required outputs:

{yaml.safe_dump(list(required_outputs), sort_keys=False, allow_unicode=True)}

Workflow plan summary:

{yaml.safe_dump(_agent_plan_summary(plan, agent_name), sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Supervisor" and production_pack_role_session:
        user = f"""
Produce the AgentLab production-pack synthesis Supervisor plan for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}
- execution_backend: {plan.execution_backend}

Output contract:

- Confirm the mission classification and why production-pack synthesis is required.
- Publish the exact role order, candidate outputs, approval boundary, budget, and
  validation gates for this run.
- Keep the run candidate-only with production_modified false and auto-promotion disabled.
- Do not emit AGENTLAB_EDIT blocks, inspect repository files, or produce the pack itself.
- State a clear downstream assignment for Researcher, ArtifactProducer, and Verifier.

Workflow plan summary:

{yaml.safe_dump(_production_pack_agent_plan_summary(plan, agent_name), sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Coder":
        user = f"""
Produce the AgentLab Coder implementation report for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path}
- agentlab_orchestrator_backend: {plan.execution_backend}
- coder_model_call_mode: direct_api_text_generation

Output contract:

- This is an execution-mode Coder call, not a planning placeholder.
- Report Coder backend and execution mode as direct_api_text_generation unless explicit CLI/IDE execution evidence is present in Available task context.
- Do not say "plan-only", "no execution", or "awaits agent execution" unless a concrete blocker prevents implementation.
- Use the workflow plan and request to produce a scoped candidate implementation.
- If source mutation is not allowed or no approved production path exists, produce a candidate patch proposal and concrete file plan instead of claiming files were changed.
- If only candidate paths are available, keep AGENTLAB_EDIT blocks short and focused; prefer a file plan plus representative patch snippets over large full-file dumps.
- For new candidate artifact files, use the HTML-style full-file block:
  <!-- AGENTLAB_EDIT: runs/<task_id>/artifacts/path.ext --> ... <!-- END AGENTLAB_EDIT -->.
- State that this direct API call used only injected context unless explicit execution evidence is present in Available task context.
- State "Commands run by this model call: none" unless explicit command evidence is present in Available task context.
- Include exact proposed validation commands that TesterAuditor should run.
- If AGENTLAB_EDIT blocks are appropriate, target only Supervisor-approved or candidate paths and place them after the markdown report.
- Do not invent command results; separate proposed commands from executed commands.

Workflow plan summary:

{yaml.safe_dump(_agent_plan_summary(plan, agent_name), sort_keys=False)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Writer":
        writer_plan_summary = {
            "project": plan.project,
            "task_id": plan.task_id,
            "route": plan.route.model_dump(mode="json"),
            "writer_required_outputs": (plan.included_agents.get("Writer") or {}).get("required_outputs", []),
            "validation_gates": plan.validation_gates,
            "selected_skills": _agent_plan_summary(plan, agent_name)["selected_skills"],
        }
        user = f"""
Produce the AgentLab narrative candidate files for:

- project: {plan.project}
- task_id: {plan.task_id}
- capture_report_path: {output_path.name}
- execution_backend: {plan.execution_backend}

Output contract:

- Do not write a prose report.
- Do not target capture_report_path with an AGENTLAB_EDIT block.
- Emit exactly one full-file AGENTLAB_EDIT block for each required Writer output allowed by mission_contract.yml.
- For narrative_light_chapter, the required outputs are normally fiction_draft.md, continuity_ledger.yml, state_transition_proposal.yml, and narrative_delivery_receipt.yml.
- Do not claim a file is delivered unless its complete content is present inside an AGENTLAB_EDIT block.
- Keep all generated files candidate-only under the run directory; do not write production/manuscript.

Workflow plan summary:

{yaml.safe_dump(writer_plan_summary, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "ArtifactProducer":
        synthesis_candidate = (
            (plan.production_pack or {}).get("status") == "synthesis_candidate"
        )
        artifact_plan_summary = (
            _production_pack_agent_plan_summary(plan, agent_name)
            if synthesis_candidate
            else _agent_plan_summary(plan, agent_name)
        )
        artifact_required_outputs = (
            (plan.included_agents.get("ArtifactProducer") or {}).get("required_outputs", [])
            or [f"runs/{plan.task_id}/{output}" for output in (plan.production_pack or {}).get("required_outputs", [])]
        )
        synthesis_output_rules = ""
        if synthesis_candidate:
            synthesis_output_rules = f"""
- This is production-pack synthesis. Emit exactly one full-file AGENTLAB_EDIT
  block for each item in Required ArtifactProducer outputs, and no other edit blocks.
- Every target must use `runs/{plan.task_id}/<filename>` and belong to this task.
- Derive the candidate from domain_research_brief.md; do not return a generic or
  fake-provider scaffold.
- production_pack_proposal.yml must set top-level candidate_only: true and
  production_modified: false. Its pack.promotion_policy must set auto_promote:
  false and production_modified: false.
- The three YAML mappings must agree on memory records, lifecycle nodes, resource
  evidence boundaries, quality gates, and the synthesized pack id.
"""
        user = f"""
Produce the AgentLab non-code candidate artifacts for:

- project: {plan.project}
- task_id: {plan.task_id}
- capture_report_path: {output_path.name if synthesis_candidate else output_path}
- execution_backend: {plan.execution_backend}
- artifact_model_call_mode: direct_api_text_generation

Output contract:

- Do not produce a generic prose-only report when required artifact files are listed.
- Emit one complete full-file AGENTLAB_EDIT block for each text/YAML/JSON/HTML/CSS/JS required output you can produce.
- For required production-pack outputs listed without a directory, target the run root path `runs/{plan.task_id}/<output>`.
- For candidate application/site/media planning artifacts, target only the approved candidate artifact directory from artifact_intent.
- Keep all outputs candidate-only unless artifact_intent declares a production path.
- Do not claim binary image/video/audio files were generated by this model call. For media tasks, write planning, prompt, ledger, continuity, QC, and delivery-receipt files, and record provider/auth blockers when applicable.
- State "Commands run by this model call: none" unless explicit command evidence is present in Available task context.
- If a required output cannot be produced, include the exact missing capability or input in artifact_producer_report.md.
{synthesis_output_rules}

Required ArtifactProducer outputs:

{yaml.safe_dump(artifact_required_outputs, sort_keys=False, allow_unicode=True)}

Workflow plan summary:

{yaml.safe_dump(artifact_plan_summary, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Researcher" and (plan.production_pack or {}).get("status") == "synthesis_candidate":
        user = f"""
Produce the AgentLab production-pack domain research brief for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}
- execution_backend: {plan.execution_backend}

Output contract:

- Write a concise domain research brief, not a code/repository report.
- Cover domain capability needs, external resources/providers/tools, persistent memory records, lifecycle phases, validation gates, promotion/acceptance rules, and blockers.
- Explicitly identify which code-factory nodes should remain excluded.
- State "Commands run by this model call: none" unless explicit command evidence is present in Available task context.
- Do not mention repo maps, implementation reports, interface maps, patches, diffs, or source edits unless the production pack is explicitly for code.

Workflow plan summary:

{yaml.safe_dump(_production_pack_agent_plan_summary(plan, agent_name), sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Verifier" and (plan.production_pack or {}).get(
        "status"
    ) == "synthesis_candidate":
        user = f"""
Verify the AgentLab production-pack candidate for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}
- execution_backend: {plan.execution_backend}

Output contract:

- Inspect only the injected candidate, research, and contract artifacts.
- State a final decision of pass or blocked.
- Check pack-registry shape, cross-file consistency, non-code lifecycle isolation,
  resource evidence boundaries, candidate-only state, and disabled auto-promotion.
- Do not emit AGENTLAB_EDIT blocks or modify any file.
- Do not claim commands were run unless explicit command evidence is injected.

Workflow plan summary:

{yaml.safe_dump(_production_pack_agent_plan_summary(plan, agent_name), sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    else:
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
    if production_pack_role_session:
        system = _sanitize_production_pack_context_text(
            system,
            agentlab_root,
            project_root,
            run_dir,
        )
        user = _sanitize_production_pack_context_text(
            user,
            agentlab_root,
            project_root,
            run_dir,
        )
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


def _role_key_for_agent(agent_name: str) -> str:
    return ROLE_KEY_BY_AGENT.get(agent_name.lower(), agent_name.lower().replace(" ", "_"))


def _resolve_cli_profile_for_agent(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
) -> tuple[dict, str, str, dict | None]:
    configs = load_agentlab_configs(agentlab_root)
    agent_model_profiles = configs.get("agent_model_profiles", {})
    budget_mode = getattr(plan, "budget_mode", "balanced") or "balanced"
    agent_role_key = _role_key_for_agent(agent_name)
    mode = os.getenv("AGENTLAB_MODE", agent_model_profiles.get("default_mode", "full_cli"))
    cli_role_profile = resolve_cli_profile(
        agent_model_profiles,
        agent_role=agent_role_key,
        budget_mode=budget_mode,
        mode=mode,
    )
    return configs, mode, agent_role_key, cli_role_profile


def _check_cli_role_binding(agentlab_root: Path, agent_name: str, cli_role_profile: dict) -> tuple[bool, str]:
    worker = str(cli_role_profile.get("cli_agent") or "").strip()
    if not worker:
        return False, f"CLI profile for AgentLab role '{agent_name}' does not declare cli_agent"
    try:
        from agent_runtime.protocols.enforcement import check_role_binding
    except Exception:
        from protocols.enforcement import check_role_binding

    return check_role_binding(agentlab_root, worker, agent_name)


def _blocked_role_binding_result(agent_name: str, worker: str, reason: str) -> LLMCallResult:
    return LLMCallResult(
        provider="agentlab-protocol",
        model=worker or "unknown_cli_worker",
        content=(
            f"# {agent_name} role binding blocked\n\n"
            f"- CLI worker: {worker or 'unknown'}\n"
            f"- Reason: {reason}\n\n"
            "AgentLab refused to execute this CLI worker because "
            "`config/agent_role_bindings.yml` does not authorize the worker for "
            "the requested role."
        ),
        status="blocked_user_decision",
        error=f"role binding denied: {reason}",
        raw_usage={
            "blocked": True,
            "reason": "role_binding_denied",
            "usage_source": "protocol_gate",
            "executor_type": "cli_agent",
            "configured_cli_agent": worker or None,
        },
    )


def resolve_agent_execution_preview(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> dict:
    _configs, mode, agent_role_key, cli_role_profile = _resolve_cli_profile_for_agent(
        agentlab_root,
        plan,
        agent_name,
    )
    if cli_role_profile is not None:
        worker = str(cli_role_profile.get("cli_agent") or "")
        allowed, reason = _check_cli_role_binding(agentlab_root, agent_name, cli_role_profile)
        return {
            "mode": mode,
            "role_key": agent_role_key,
            "executor_type": "cli_agent",
            "cli_agent": worker,
            "role_binding_allowed": allowed,
            "role_binding_reason": reason,
        }

    settings, _ = resolve_agent_settings(
        agentlab_root,
        agent_name,
        provider_override,
        model_override,
        profile_config=(plan.model_profiles or {}).get(agent_name),
    )
    return {
        "mode": mode,
        "role_key": agent_role_key,
        "executor_type": "direct_api",
        "provider": settings.provider,
        "model": settings.model,
        "api_key_configured": settings.api_key_configured,
    }


def run_agent_model(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
    provider_override: str | None = None,
    model_override: str | None = None,
    apply_patches: bool = True,
    allow_cli_api_fallback: bool = True,
):
    from operational_uploader import maybe_run_operational_agent

    operational_result = maybe_run_operational_agent(plan, agent_name)
    if operational_result is not None:
        return operational_result

    # ── CLI Agent dispatch (executor_type: cli_agent) ─────────────────────────
    # Attempt to route this agent call through a local CLI agent (e.g. hermes,
    # claude_code) as defined in config/agent_model_profiles.yml.  If the
    # binary is not installed, we fall through to the direct API path below.
    configs_for_cli, cli_mode, agent_role_key, cli_role_profile = _resolve_cli_profile_for_agent(
        agentlab_root,
        plan,
        agent_name,
    )
    agent_model_profiles = configs_for_cli.get("agent_model_profiles", {})
    budget_mode = getattr(plan, "budget_mode", "balanced") or "balanced"

    # Track execution source for auditability
    cli_fallback_reason: str | None = None
    cli_configured_agent: str | None = None
    cli_attempted: bool = False

    if cli_role_profile is not None:
        cli_configured_agent = cli_role_profile.get("cli_agent", "")
        allowed, binding_reason = _check_cli_role_binding(agentlab_root, agent_name, cli_role_profile)
        if not allowed:
            return _blocked_role_binding_result(agent_name, cli_configured_agent, binding_reason)
        cli_attempted = True
        sealed_messages = None
        task_messages = None
        outbound_source_paths = None
        if agent_name == "Writer":
            sealed_messages = compose_agent_messages(agentlab_root, plan, agent_name, output_path)
            outbound_source_paths = writer_context_source_files(
                agentlab_root, plan, output_path
            )
        elif (
            (plan.production_pack or {}).get("status") == "synthesis_candidate"
            and agent_name
            in {"Supervisor", "Researcher", "ArtifactProducer", "Verifier"}
        ):
            task_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = production_pack_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
        cli_result = run_cli_agent(
            plan,
            agent_name,
            cli_role_profile,
            sealed_messages=sealed_messages,
            task_messages=task_messages,
            outbound_source_paths=outbound_source_paths,
        )
        if not isinstance(cli_result, CliAgentNotAvailable):
            # CLI agent ran (success or failure) — annotate and return.
            _audit_annotate_cli_result(cli_result, cli_role_profile, "cli_executed")
            return cli_result
        # Binary absent or CLI unavailable: record reason, fall through to API.
        cli_fallback_reason = (
            f"{cli_result.reason}: {cli_result.detail[:300]}"
            if hasattr(cli_result, "detail") and cli_result.detail
            else getattr(cli_result, "reason", "cli_unavailable")
        )
        if (
            (plan.production_pack or {}).get("status") == "synthesis_candidate"
            and agent_name
            in {"Supervisor", "Researcher", "ArtifactProducer", "Verifier"}
        ):
            return LLMCallResult(
                provider="agentlab-cli-executor",
                model=cli_configured_agent or "unknown_cli_worker",
                content=(
                    f"# {agent_name} CLI worker unavailable\n\n"
                    "The configured production-pack role worker is unavailable. "
                    "AgentLab refused to switch provider surfaces or use a direct-API "
                    "fallback without a separately planned and approved full_api run.\n"
                ),
                status="blocked_user_decision",
                error="production_pack_cli_unavailable_no_fallback",
                raw_usage={
                    "executor_type": "cli_agent",
                    "configured_cli_agent": cli_configured_agent,
                    "cli_unavailable_reason": getattr(
                        cli_result,
                        "reason",
                        "cli_unavailable",
                    ),
                    "provider_surface_changed": False,
                    "direct_api_fallback_attempted": False,
                },
            )
        if not allow_cli_api_fallback:
            return LLMCallResult(
                provider="agentlab-cli-executor",
                model=cli_configured_agent or "unknown_cli_worker",
                content=(
                    f"# {agent_name} CLI worker unavailable\n\n"
                    "AgentLab refused to switch from the configured CLI worker to a direct-API provider.\n"
                ),
                status="blocked_user_decision",
                error="cli_unavailable_no_fallback",
                raw_usage={
                    "executor_type": "cli_agent",
                    "configured_cli_agent": cli_configured_agent,
                    "cli_unavailable_reason": getattr(
                        cli_result,
                        "reason",
                        "cli_unavailable",
                    ),
                    "provider_surface_changed": False,
                    "direct_api_fallback_attempted": False,
                },
            )
    if not allow_cli_api_fallback and cli_role_profile is None:
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="unconfigured_cli_worker",
            content=(
                f"# {agent_name} CLI profile missing\n\n"
                "AgentLab refused to use a direct-API provider without the required CLI profile.\n"
            ),
            status="blocked_user_decision",
            error="cli_profile_required_no_fallback",
            raw_usage={
                "executor_type": "cli_agent",
                "configured_cli_agent": None,
                "provider_surface_changed": False,
                "direct_api_fallback_attempted": False,
            },
        )
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
    if agent_name == "Writer":
        try:
            from agent_runtime.outbound_context import write_outbound_context_manifest
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from outbound_context import write_outbound_context_manifest

        approval_required = (
            str(plan.task_id).startswith("task_narrative_eval_")
            or os.getenv("AGENTLAB_TRUSTED_LIVE_RUNNER") == "1"
        )
        manifest = write_outbound_context_manifest(
            agentlab_root,
            Path(plan.run_dir) / "outbound_context_manifest_writer.yml",
            item_id=str(plan.task_id),
            role="Writer",
            provider_surface=f"direct_api:{settings.provider}",
            payload_kind="writer_direct_api_messages",
            payload_text=json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            source_paths=writer_context_source_files(agentlab_root, plan, output_path),
            private_context=True,
            exact_payload=True,
            sealed_context=True,
            execution_workspace_isolated=True,
            approval_required=approval_required,
        )
        if not manifest.get("execution_allowed"):
            return LLMCallResult(
                provider=settings.provider,
                model=settings.model,
                content=(
                    "# Writer outbound context blocked\n\n"
                    "The deterministic outbound-context gate refused the provider call. "
                    "Inspect outbound_context_manifest_writer.yml for content-free reasons.\n"
                ),
                status="blocked_user_decision",
                error="writer_outbound_context_gate_blocked",
                raw_usage={
                    "outbound_context_manifest": str(
                        Path(plan.run_dir) / "outbound_context_manifest_writer.yml"
                    ),
                    "outbound_context_status": manifest.get("status"),
                },
            )
    elif (
        (plan.production_pack or {}).get("status") == "synthesis_candidate"
        and agent_name
        in {"Supervisor", "Researcher", "ArtifactProducer", "Verifier"}
    ):
        try:
            from agent_runtime.outbound_context import (
                PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
                write_outbound_context_manifest,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from outbound_context import (
                PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
                write_outbound_context_manifest,
            )

        manifest_path = (
            Path(plan.run_dir)
            / f"outbound_context_manifest_{agent_name.lower()}.yml"
        )
        manifest = write_outbound_context_manifest(
            agentlab_root,
            manifest_path,
            item_id=str(plan.task_id),
            role=agent_name,
            provider_surface=f"direct_api:{settings.provider}",
            payload_kind="production_pack_direct_api_messages",
            payload_text=json.dumps(
                messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            source_paths=production_pack_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            ),
            private_context=True,
            exact_payload=True,
            sealed_context=True,
            execution_workspace_isolated=True,
            approval_required=True,
            approval_env_name=PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
            provider_shell_or_browser_requested=agent_name == "Researcher",
            source_inventory_required=True,
        )
        if not manifest.get("execution_allowed"):
            return LLMCallResult(
                provider=settings.provider,
                model=settings.model,
                content=(
                    f"# {agent_name} outbound context blocked\n\n"
                    "The deterministic production-pack outbound-context gate "
                    "refused the provider call. Inspect "
                    f"{manifest_path.name} for content-free reasons.\n"
                ),
                status="blocked_user_decision",
                error="production_pack_outbound_context_gate_blocked",
                raw_usage={
                    "outbound_context_manifest": str(manifest_path),
                    "outbound_context_status": manifest.get("status"),
                    "approval_env_name": (
                        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
                    ),
                },
            )
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

    # ── Audit annotation: record execution source metadata ──────────────────
    if cli_attempted and cli_fallback_reason:
        # Case 2: CLI configured but fell back to API
        _audit_annotate_api_fallback_result(
            result, cli_configured_agent, cli_fallback_reason
        )
    elif cli_role_profile is None and not cli_attempted:
        # Case 3/4: Direct API or special/skipped — annotate accordingly
        _audit_annotate_api_result_source(result, agent_model_profiles, agent_role_key, cli_mode, budget_mode)
    # ─────────────────────────────────────────────────────────────────────────

    patch_application_allowed = _patch_application_enabled(configs, agent_name, apply_patches)
    if (
        not patch_application_allowed
        and agent_name in {"Coder", "ArtifactProducer"}
        and apply_patches
        and _candidate_artifact_patch_application_allowed(plan)
    ):
        patch_application_allowed = True

    # Apply file edits only when policy explicitly allows direct mutation.
    if patch_application_allowed and result.status == "completed" and result.content:
        from patch_applicator import apply_all_patches, strip_edit_blocks_from_report
        from artifact_contract import has_unclosed_structured_edit_block

        if has_unclosed_structured_edit_block(result.content):
            result.raw_usage = {
                **(result.raw_usage or {}),
                "patch_applied": 0,
                "patch_failed": 1,
                "patch_blocked_reason": "unclosed_structured_edit_block",
            }
            patch_results = []
        else:
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
    allowed_from_contract: set[str] = set()
    contract_path = Path(plan.run_dir) / "mission_contract.yml"
    if contract_path.exists():
        try:
            contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
            for key in ("allowed_output_files", "allowed_edit_files"):
                values = contract.get(key) or []
                if isinstance(values, list):
                    allowed_from_contract.update(str(item) for item in values)
        except Exception:
            pass
    if allowed_from_contract:
        return allowed_from_contract
    allowed_from_artifact_intent: set[str] = set()
    project_root = Path(plan.project_root)
    artifact_intent = plan.artifact_intent or {}
    for raw_root in artifact_intent.get("allowed_write_roots") or []:
        try:
            root_path = Path(str(raw_root))
            rel = root_path.relative_to(project_root) if root_path.is_absolute() else root_path
        except Exception:
            continue
        allowed_from_artifact_intent.add(rel.as_posix().rstrip("/") + "/")
    for raw_path in artifact_intent.get("declared_production_paths") or []:
        text = str(raw_path).strip()
        if text:
            allowed_from_artifact_intent.add(text.lstrip("/"))
    if allowed_from_artifact_intent:
        return allowed_from_artifact_intent
    if not coder_config:
        return None
    allowed = coder_config.get("allowed_files") or coder_config.get("editable_files")
    if allowed and isinstance(allowed, list):
        return {str(f) for f in allowed}
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _candidate_artifact_patch_application_allowed(plan: WorkflowPlan) -> bool:
    """Allow direct Coder writes only for run-local candidate artifact roots.

    Production source edits remain governed by execution_policy.yml. This exception
    exists so direct API Coder can materialize generated candidate artifacts without
    opening automatic mutation for repository files.
    """
    artifact_intent = plan.artifact_intent or {}
    roots = artifact_intent.get("allowed_write_roots") or []
    if not roots:
        return False
    if artifact_intent.get("declared_production_paths") or artifact_intent.get("allowed_overwrite_paths"):
        return False

    raw_candidate_dir = artifact_intent.get("candidate_dir")
    if not raw_candidate_dir:
        return False

    run_dir = Path(plan.run_dir).resolve(strict=False)
    project_root = Path(plan.project_root).resolve(strict=False)
    candidate_dir = Path(str(raw_candidate_dir))
    if not candidate_dir.is_absolute():
        candidate_dir = run_dir / candidate_dir
    candidate_dir = candidate_dir.resolve(strict=False)

    if not _is_relative_to(candidate_dir, run_dir):
        return False

    for raw_root in roots:
        root = Path(str(raw_root))
        if not root.is_absolute():
            root = project_root / root
        root = root.resolve(strict=False)
        if root != candidate_dir and not _is_relative_to(root, candidate_dir):
            return False

    return True


def _role_for_agent(agent_name: str) -> str:
    return {
        "RepoScout": "repo_reader",
        "Researcher": "researcher",
        "Archivist": "archivist",
    }.get(agent_name, agent_name.lower())


# ── Audit helpers for execution-source transparency ───────────────────────


def _audit_annotate_cli_result(
    result: "LLMCallResult",
    role_profile: dict,
    disposition: str,
) -> None:
    """Annotate a CLI-executed result with audit metadata."""
    result.raw_usage = {
        **(result.raw_usage or {}),
        "usage_source": "cli_agent",
        "executor_type": "cli_agent",
        "cli_agent": role_profile.get("cli_agent", ""),
        "resolved_mode": role_profile.get("resolved_mode", ""),
        "resolved_tier": role_profile.get("resolved_tier", ""),
        "resolved_schema": role_profile.get("resolved_schema", ""),
        "api_fallback_used": False,
        "disposition": disposition,
    }


def _audit_annotate_api_fallback_result(
    result: "LLMCallResult",
    configured_cli_agent: str | None,
    fallback_reason: str,
) -> None:
    """Annotate an API result that was reached via CLI-fallback path."""
    result.raw_usage = {
        **(result.raw_usage or {}),
        "usage_source": "api_usage",
        "executor_type": "cli_agent_fallback",
        "configured_cli_agent": configured_cli_agent or "unknown",
        "api_fallback_used": True,
        "fallback_reason": fallback_reason,
        "fallback_model": result.model,
    }


def _audit_annotate_api_result_source(
    result: "LLMCallResult",
    agent_model_profiles: dict,
    agent_role_key: str,
    mode: str,
    tier: str,
) -> None:
    """Annotate a direct-API result with config-source metadata."""
    modes = agent_model_profiles.get("modes", {}) or {}
    source_type = "direct_api"
    role_cfg = {}
    if modes:
        mode_cfg = modes.get(mode, {}) or {}
        tiers = mode_cfg.get("tiers", {}) or {}
        tier_cfg = tiers.get(tier, {}) or {}
        role_cfg_raw = tier_cfg.get(agent_role_key)
        if isinstance(role_cfg_raw, str) and role_cfg_raw.lower() in {"skip", "skip_unless_required"}:
            source_type = "skip"
        elif isinstance(role_cfg_raw, dict):
            role_cfg = role_cfg_raw
            if role_cfg.get("executor_type") == "special":
                source_type = "special"
            elif role_cfg.get("executor_type") == "direct_api":
                source_type = "direct_api"
    result.raw_usage = {
        **(result.raw_usage or {}),
        "usage_source": "api_usage" if source_type != "skip" else "skipped",
        "executor_type": source_type,
        "api_fallback_used": False,
        "resolved_mode": mode,
        "resolved_tier": tier,
        "resolved_schema": "modes_v4" if modes else "legacy_profiles",
    }


def _patch_application_enabled(configs: dict, agent_name: str, requested: bool) -> bool:
    if not requested:
        return False
    if agent_name in {"Writer", "Scribe"}:
        return True
    if agent_name != "Coder":
        return False
    execution_policy = configs.get("execution_policy", {})
    tier_policy = execution_policy.get("execution_policy", {})
    coder_policy = execution_policy.get("coder_policy", {})
    if coder_policy.get("automatic_patch_application") is True:
        return True
    return tier_policy.get("patch_application_policy") == "apply_directly"
