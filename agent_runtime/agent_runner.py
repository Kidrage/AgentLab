"""Single-agent execution helpers for the AgentLab CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import yaml

from cli_executor import CliAgentNotAvailable, resolve_cli_profile, run_cli_agent
from config_loader import load_agentlab_configs
from llm_provider import generate_text, resolve_env_value, resolve_llm_settings
from policies import assert_path_allowed
from repository_handoff import discover_handoff
from role_keys import normalize_role_key
from schemas import LLMCallResult, LLMSettings, WorkflowPlan


DEFAULT_REPORT_BY_AGENT = {
    "Supervisor": "01_supervisor_plan.md",
    "RepoScout": "02_reposcout_report.md",
    "Researcher": "03_research_notes.md",
    "Observer": "observation_report.yml",
    "InterfaceMapper": "04_interface_map.md",
    "PromptEngineer": "05_coder_prompt.md",
    "Coder": "06_implementation_report.md",
    "ArtifactProducer": "artifact_producer_report.md",
    "NarrativePlanner": "chapter_state_plan.yml",
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

_OBSERVER_TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".json",
    ".md",
    ".rst",
    ".srt",
    ".tsv",
    ".txt",
    ".vtt",
    ".xml",
    ".yaml",
    ".yml",
}
_OBSERVER_MODALITY_BY_SUFFIX = {
    ".aac": "audio",
    ".avi": "video",
    ".bmp": "image",
    ".flac": "audio",
    ".gif": "image",
    ".heic": "image",
    ".jpeg": "image",
    ".jpg": "image",
    ".m4a": "audio",
    ".mkv": "video",
    ".mov": "video",
    ".mp3": "audio",
    ".mp4": "video",
    ".mpeg": "video",
    ".ogg": "audio",
    ".pdf": "pdf",
    ".png": "image",
    ".tif": "image",
    ".tiff": "image",
    ".wav": "audio",
    ".webm": "video",
    ".webp": "image",
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
    if not path.is_file():
        return f"[missing: {path}]"
    return path.read_text(encoding="utf-8")


def _is_context_placeholder(path: Path) -> bool:
    report_names = set(DEFAULT_REPORT_BY_AGENT.values()) | set(LEGACY_REPORT_BY_AGENT.values())
    if path.name not in report_names:
        return False
    return is_placeholder_report(path)


def _repository_handoff_context_files(*roots: Path) -> list[Path]:
    """Select at most one authoritative or legacy handoff per repository."""
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        handoff = discover_handoff(root)
        if handoff is None:
            continue
        resolved = handoff.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(handoff)
    return files


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
        if not isinstance(contract, dict):
            continue
        for key in ("must_read", "must_read_artifacts"):
            items = contract.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
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
        run_dir / "writer_contract_retry_feedback.yml",
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


def supervisor_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return every local file embedded in a sealed Supervisor payload."""

    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    files = [
        agentlab_root / "AGENTS.md",
        agentlab_root / "config" / "repository_handoff_policy.yml",
        agentlab_root / "config" / "harness_policy.yml",
        project_root / "project_config.yml",
        project_root / "agent_docs" / "00_CONTEXT_PACK.md",
        project_root / "agent_docs" / "01_REPO_MAP.md",
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / "mission_contract.yml",
    ]
    files[2:2] = _repository_handoff_context_files(agentlab_root, project_root)
    configs = load_agentlab_configs(agentlab_root)
    supervisor = (configs.get("agent_registry", {}).get("agents", {}) or {}).get(
        "Supervisor",
        {},
    )
    template_ref = str(supervisor.get("template_path") or "").strip()
    if template_ref:
        files.append(agentlab_root / template_ref)

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if path.is_symlink():
            path = resolved
        if resolved == output_resolved or resolved in seen or not path.is_file():
            continue
        if _is_context_placeholder(path):
            continue
        seen.add(resolved)
        result.append(path)
    return result


def narrative_heavy_audit_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
) -> list[Path]:
    """Return the files embedded in a sealed narrative heavy-audit session."""

    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    files = [
        agentlab_root / "config" / "agent_registry.yml",
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
        run_dir / "mission_contract.yml",
        run_dir / "narrative_audit_manifest.yml",
        run_dir
        / f"narrative_heavy_audit_{agent_name.lower()}_output_contract.yml",
    ]
    if agent_name == "Reviewer":
        files.extend(
            [
                run_dir / "narrative_audit_context.md",
                project_root / "project_brain" / "project_fact_snapshot.yml",
                project_root / "project_artifact_index.yml",
            ]
        )
    if agent_name in {"Scribe", "Verifier"}:
        files.extend(
            [
                run_dir / "fiction_review.yml",
                run_dir / "continuity_failure_report.yml",
            ]
        )
    if agent_name == "Verifier":
        files.append(run_dir / "state_transition_proposal.yml")

    configs = load_agentlab_configs(agentlab_root)
    agent_config = (
        (configs.get("agent_registry", {}).get("agents", {}) or {}).get(
            agent_name, {}
        )
    )
    template_text = str(agent_config.get("template_path") or "").strip()
    if template_text:
        files.append(agentlab_root / template_text)

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


def researcher_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return the exact local inputs embedded in a sealed Researcher packet."""

    run_dir = Path(plan.run_dir)
    files = [
        agentlab_root / "config" / "agent_registry.yml",
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / "mission_contract.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
    ]
    configs = load_agentlab_configs(agentlab_root)
    researcher_config = (
        (configs.get("agent_registry", {}).get("agents", {}) or {}).get(
            "Researcher", {}
        )
    )
    template_text = str(researcher_config.get("template_path") or "").strip()
    if template_text:
        files.append(agentlab_root / template_text)

    for item in (plan.skills or {}).get("selected", []) or []:
        if not isinstance(item, dict):
            continue
        injected_into = item.get("injected_into") or []
        if injected_into and "Researcher" not in injected_into:
            continue
        raw_path = str(item.get("skill_path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        files.append(path if path.is_absolute() else agentlab_root / path)

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        try:
            allowed = assert_path_allowed(path, agentlab_root)
        except Exception:
            continue
        resolved = allowed.resolve(strict=False)
        if (
            resolved == output_resolved
            or resolved in seen
            or not allowed.is_file()
            or _is_context_placeholder(allowed)
        ):
            continue
        seen.add(resolved)
        result.append(allowed)
    return result


def observer_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return only explicitly assigned, bounded Observer inputs.

    Multimodal files are never discovered by scanning. They must be listed in
    ``observation_contract.yml`` or ``artifact_task.yml`` as ``path`` values.
    """
    run_dir = Path(plan.run_dir)
    project_root = Path(plan.project_root)
    files = [
        Path(plan.user_request_path),
        run_dir / "01_supervisor_plan.md",
        run_dir / "observation_contract.yml",
        run_dir / "artifact_task.yml",
        run_dir / "media_generation_contract.yml",
    ]
    visual_observation = output_path.name == "visual_observation_report.yml"
    if visual_observation:
        files.extend(
            [
                run_dir / "artifacts" / "media_backend" / "generation_ledger.yml",
                run_dir / "artifacts" / "media_backend" / "generation_receipt.yml",
                run_dir / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
                run_dir / "generation_ledger.yml",
                run_dir / "generation_receipt.yml",
                run_dir / "generated_assets_manifest.yml",
            ]
        )
        manifest_path = next(
            (
                path
                for path in (
                    run_dir / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
                    run_dir / "generated_assets_manifest.yml",
                )
                if path.is_file()
            ),
            None,
        )
        if manifest_path is not None:
            try:
                manifest = yaml.safe_load(
                    manifest_path.read_text(encoding="utf-8")
                ) or {}
            except (OSError, yaml.YAMLError):
                manifest = {}
            assets = manifest.get("assets") if isinstance(manifest, dict) else []
            for item in assets if isinstance(assets, list) else []:
                raw = item.get("path") if isinstance(item, dict) else None
                if not isinstance(raw, str) or not raw.strip():
                    continue
                candidate = Path(raw)
                if not candidate.is_absolute():
                    candidate = run_dir / candidate
                try:
                    allowed = assert_path_allowed(candidate, run_dir)
                    assert_path_allowed(allowed, agentlab_root)
                except Exception:
                    continue
                if allowed.is_file():
                    files.append(allowed)
    try:
        from agent_runtime.observation_contract import validated_observation_inputs
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from observation_contract import validated_observation_inputs

    files.extend(validated_observation_inputs(plan))

    # ArtifactTask remains a compatibility source for generated-artifact
    # observation. Dedicated observation contracts are resolved above through
    # their strict task/path/hash/read-only validator.
    for contract_path in (run_dir / "artifact_task.yml",):
        try:
            contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(contract, dict):
            continue
        assigned = contract.get("assigned_inputs") or contract.get("inputs") or []
        if not isinstance(assigned, list):
            continue
        for item in assigned:
            raw = item.get("path") if isinstance(item, dict) else item
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw)
            candidates = [candidate] if candidate.is_absolute() else [
                run_dir / candidate,
                project_root / candidate,
            ]
            for resolved_candidate in candidates:
                try:
                    allowed = assert_path_allowed(resolved_candidate, agentlab_root)
                except Exception:
                    continue
                if allowed.is_file():
                    files.append(allowed)
                    break

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if resolved == output_resolved or resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        result.append(path)
    return result


def visual_acceptance_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
) -> list[Path]:
    """Return bounded text evidence for media Reviewer or Verifier sessions."""

    run_dir = Path(plan.run_dir)
    common = [
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / "media_generation_contract.yml",
        run_dir / "artifacts" / "media_backend" / "generation_ledger.yml",
        run_dir / "artifacts" / "media_backend" / "generation_receipt.yml",
        run_dir / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
        run_dir / "generation_ledger.yml",
        run_dir / "generation_receipt.yml",
        run_dir / "generated_assets_manifest.yml",
        run_dir / "visual_observation_report.yml",
    ]
    if agent_name == "Verifier":
        common.extend(
            [
                run_dir / "visual_review_report.yml",
                run_dir / "media_qc_report.yml",
                run_dir / "07_validation_report.md",
                run_dir / "08_audit_report.md",
            ]
        )
    manifest_path = next(
        (
            path
            for path in (
                run_dir / "artifacts" / "media_backend" / "generated_assets_manifest.yml",
                run_dir / "generated_assets_manifest.yml",
            )
            if path.is_file()
        ),
        None,
    )
    if manifest_path is not None:
        try:
            manifest = yaml.safe_load(
                manifest_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            manifest = {}
        assets = manifest.get("assets") if isinstance(manifest, dict) else []
        for item in assets if isinstance(assets, list) else []:
            raw = item.get("path") if isinstance(item, dict) else None
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            try:
                allowed = assert_path_allowed(candidate, run_dir)
                assert_path_allowed(allowed, agentlab_root)
            except Exception:
                continue
            if allowed.is_file():
                common.append(allowed)
    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in common:
        try:
            allowed = assert_path_allowed(path, agentlab_root)
        except Exception:
            continue
        resolved = allowed.resolve(strict=False)
        if resolved == output_resolved or resolved in seen or not allowed.is_file():
            continue
        seen.add(resolved)
        result.append(allowed)
    return result


def observer_required_modalities(paths: list[Path]) -> list[str]:
    modalities = {"text"}
    for path in paths:
        modality = _OBSERVER_MODALITY_BY_SUFFIX.get(path.suffix.lower())
        if modality:
            modalities.add(modality)
    return sorted(modalities)


def production_pack_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
) -> list[Path]:
    """Return the minimal files embedded in a production-pack role packet."""
    if not _is_production_pack_synthesis_role(plan, agent_name):
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


def artifact_producer_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return the exact files embedded in a bounded ArtifactTask session."""

    run_dir = Path(plan.run_dir)
    project_root = Path(plan.project_root)
    files = [
        Path(plan.user_request_path),
        run_dir / "mission_contract.yml",
        run_dir / "artifact_task.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
        project_root / "project_config.yml",
        project_root / "project_artifact_index.yml",
    ]
    artifact_task_path = run_dir / "artifact_task.yml"
    if artifact_task_path.is_symlink():
        artifact_task = {}
    else:
        try:
            artifact_task = yaml.safe_load(
                artifact_task_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            artifact_task = {}
    if isinstance(artifact_task, dict):
        try:
            from agent_runtime.protocols.artifact_task import (
                validate_artifact_task_inputs,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from protocols.artifact_task import validate_artifact_task_inputs
        try:
            validated_inputs = validate_artifact_task_inputs(
                agentlab_root,
                artifact_task,
            )
        except ValueError:
            # ``run_cli_agent`` owns the fail-closed receipt.  This discovery
            # helper merely guarantees an invalid row cannot enter the
            # outbound source inventory or the bounded provider context.
            validated_inputs = []
        files.extend(Path(item["_source_path"]) for item in validated_inputs)
    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if path.is_symlink():
            path = resolved
        if resolved == output_resolved or resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        result.append(path)
    return result


def _validated_narrative_rewrite_inputs(
    agentlab_root: Path,
    plan: WorkflowPlan,
) -> list[Path]:
    """Return hash-bound inputs from a valid narrative rewrite contract."""

    contract_path = Path(plan.run_dir) / "narrative_rewrite_contract.yml"
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ValueError("narrative_rewrite_contract_missing_or_symlinked")
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("narrative_rewrite_contract_invalid_yaml") from exc
    if not isinstance(contract, dict):
        raise ValueError("narrative_rewrite_contract_root_invalid")
    expected = {
        "schema_version": 1,
        "project": plan.project,
        "status": "candidate_contract",
        "candidate_only": True,
        "production_modified": False,
        "blocking_evidence_confirmed": True,
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        raise ValueError("narrative_rewrite_contract_boundary_invalid")
    chapter_range = contract.get("chapter_range")
    if not (
        isinstance(chapter_range, list)
        and len(chapter_range) == 2
        and all(type(item) is int and item > 0 for item in chapter_range)
        and chapter_range[0] <= chapter_range[1]
    ):
        raise ValueError("narrative_rewrite_contract_chapter_range_invalid")
    assigned_inputs = contract.get("assigned_inputs")
    if not isinstance(assigned_inputs, list) or not assigned_inputs:
        raise ValueError("narrative_rewrite_contract_inputs_missing")
    try:
        from agent_runtime.protocols.artifact_task import validate_artifact_task_inputs
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from protocols.artifact_task import validate_artifact_task_inputs
    try:
        validated = validate_artifact_task_inputs(agentlab_root, contract)
    except ValueError as exc:
        raise ValueError("narrative_rewrite_contract_input_validation_failed") from exc
    if not validated:
        raise ValueError("narrative_rewrite_contract_inputs_missing")
    return [Path(item["_source_path"]) for item in validated]


def narrative_planner_context_source_files(
    agentlab_root: Path,
    plan: WorkflowPlan,
    output_path: Path,
) -> list[Path]:
    """Return the sealed governance files and hash-bound rewrite evidence."""

    run_dir = Path(plan.run_dir)
    files = [
        Path(plan.user_request_path),
        run_dir / "workflow_plan.yml",
        run_dir / "mission_contract.yml",
        run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
        run_dir / "narrative_rewrite_contract.yml",
    ]
    try:
        files.extend(_validated_narrative_rewrite_inputs(agentlab_root, plan))
    except ValueError:
        # Execution validates fail-closed before starting a provider process.
        # Dry-run message composition still exposes the missing contract input.
        pass

    output_resolved = output_path.resolve(strict=False)
    result: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve(strict=False)
        if path.is_symlink():
            path = resolved
        if resolved == output_resolved or resolved in seen or not path.is_file():
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
        "workflow_driver": summary["workflow_driver"],
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
            "can_edit_source",
            "can_run_shell",
            "can_write_agent_docs",
            "source_write_policy",
            "shell_policy",
            "required_inputs",
            "required_outputs",
        )
        if key in current_agent
    }
    resolved_execution = dict((plan.model_profiles or {}).get(agent_name) or {})
    execution_profile = {
        key: resolved_execution.get(key)
        for key in (
            "executor_type",
            "cli_agent",
            "invocation_contract",
            "catalog_key",
            "provider",
            "model",
            "capacity_route",
            "resolved_mode",
            "resolved_tier",
        )
        if key in resolved_execution
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
        "workflow_driver": plan.execution_backend,
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
        "execution_profile": execution_profile,
        "token_budget": token_budget,
        "validation_gates": plan.validation_gates,
        "artifact_intent": plan.artifact_intent,
        "production_pack": plan.production_pack,
        "missing_inputs": plan.missing_inputs,
        "selected_skills": selected_skills,
    }


def _is_production_pack_synthesis_role(plan: WorkflowPlan, agent_name: str) -> bool:
    pack = plan.production_pack or {}
    configured_roles = list(pack.get("agents") or plan.route.agents or [])
    return (
        pack.get("status") == "synthesis_candidate"
        and agent_name in set(configured_roles)
    )


def compose_agent_messages(agentlab_root: Path, plan: WorkflowPlan, agent_name: str, output_path: Path) -> list[dict[str, str]]:
    configs = load_agentlab_configs(agentlab_root)
    registry = configs.get("agent_registry", {}).get("agents", {})
    agent_config = registry.get(agent_name, {})
    template_variants = agent_config.get("template_variants", {}) or {}
    template_ref = template_variants.get(
        plan.route.route_key,
        agent_config.get("template_path", ""),
    )
    template_path = assert_path_allowed(agentlab_root / template_ref, agentlab_root)
    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    artifact_task: dict = {}
    artifact_cli_session = False
    if agent_name == "ArtifactProducer":
        try:
            loaded_artifact_task = yaml.safe_load(
                (run_dir / "artifact_task.yml").read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            loaded_artifact_task = {}
        if isinstance(loaded_artifact_task, dict):
            artifact_task = loaded_artifact_task
            routing = artifact_task.get("routing") or {}
            artifact_cli_session = (
                isinstance(routing, dict)
                and routing.get("provider_type") == "cli"
            )
    production_pack_role_session = _is_production_pack_synthesis_role(
        plan, agent_name
    )
    narrative_rewrite_plan = plan.route.route_key == "narrative_rewrite_plan"
    narrative_heavy_audit = plan.route.route_key == "narrative_heavy_audit"
    media_visual_route = plan.route.route_key == "media_generation_task"
    if agent_name == "Supervisor" and production_pack_role_session:
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            agentlab_root / "config" / "production_packs.yml",
        ]
    elif narrative_rewrite_plan and agent_name == "NarrativePlanner":
        context_files = narrative_planner_context_source_files(
            agentlab_root,
            plan,
            output_path,
        )
    elif agent_name == "Writer":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "mission_contract.yml",
            run_dir / "chapter_packet.yml",
        ]
        context_files.extend(_story_authority_context_files(project_root, run_dir))
    elif agent_name == "Observer" and output_path.name == "visual_observation_report.yml":
        context_files = observer_context_source_files(
            agentlab_root,
            plan,
            output_path,
        )
    elif agent_name == "Observer":
        context_files = observer_context_source_files(
            agentlab_root,
            plan,
            output_path,
        )
    elif media_visual_route and agent_name in {"Reviewer", "Verifier"}:
        context_files = visual_acceptance_context_source_files(
            agentlab_root,
            plan,
            agent_name,
            output_path,
        )
    elif narrative_heavy_audit and agent_name in {"Reviewer", "Scribe", "Verifier"}:
        context_files = [
            Path(plan.user_request_path),
            run_dir / "workflow_plan.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
            run_dir / "mission_contract.yml",
            run_dir / "narrative_audit_manifest.yml",
            run_dir
            / f"narrative_heavy_audit_{agent_name.lower()}_output_contract.yml",
        ]
        if agent_name == "Reviewer":
            context_files.extend(
                [
                    run_dir / "narrative_audit_context.md",
                    project_root / "project_brain" / "project_fact_snapshot.yml",
                    project_root / "project_artifact_index.yml",
                ]
            )
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
    elif agent_name == "Researcher":
        context_files = [
            Path(plan.user_request_path),
            run_dir / "workflow_plan.yml",
            run_dir / "mission_contract.yml",
            run_dir / DEFAULT_REPORT_BY_AGENT.get("Supervisor", "01_supervisor_plan.md"),
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
            run_dir / "artifact_lineage.yml",
            run_dir / "artifact_promotion_plan.yml",
            run_dir / "archive_receipt.yml",
        ]
        context_files[2:2] = _repository_handoff_context_files(
            agentlab_root,
            project_root,
        )

    context_sections = []
    seen_context_texts: set[str] = set()
    output_resolved = output_path.resolve()
    for path in context_files:
        if agent_name in {"Writer", "Observer"} or (
            media_visual_route and agent_name in {"Reviewer", "Verifier"}
        ):
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
            if (
                agent_name == "Observer"
                or (media_visual_route and agent_name in {"Reviewer", "Verifier"})
            ) and path.suffix.lower() not in _OBSERVER_TEXT_SUFFIXES:
                try:
                    byte_count = path.stat().st_size
                except OSError:
                    byte_count = None
                text = yaml.safe_dump(
                    {
                        "assigned_multimodal_input": path.name,
                        "byte_count": byte_count,
                        "delivery": "staged_read_only_file_listed_in_task_packet",
                    },
                    sort_keys=False,
                ).strip()
            else:
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
- After any material project change and before final reporting, refresh canonical
  PROJECT_HANDOFF.md. Write a shared fallback only when explicitly requested or
  when the repository is read-only; never rewrite legacy aliases.
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
    if narrative_rewrite_plan and agent_name == "NarrativePlanner":
        hard_rules = """
Narrative rewrite planning role-session rules:
- Use only the complete context embedded in this sealed task packet.
- Do not request tools, shell commands, file reads, repository scans, browser
  access, subagents, or workflow discovery.
- Convert declared blocking audit evidence into one coherent, ordered chapter
  state plan; do not write or revise manuscript prose.
- Return raw YAML for chapter_state_plan.yml only, with candidate_only true and
  production_modified false.
- Do not edit project memory, establish canon, write production, approve
  promotion, emit AGENTLAB_EDIT blocks, or claim AgentLab receipts are missing.
- Preserve authority memory and make each scene goal, irreversible plot change,
  and timeline slot specific and unique.
"""
    elif narrative_heavy_audit and agent_name == "Supervisor":
        hard_rules = """
Narrative heavy-audit Supervisor role-session rules:
- Use only the complete context embedded in this sealed task packet.
- Do not request tools, shell commands, file reads, repository scans, browser access,
  subagents, or workflow discovery; all permitted evidence is already injected.
- Produce the governed audit/rewrite plan requested by user_request.md directly.
- Keep all deliverables candidate-only, production_modified false, and promotion disabled.
- Do not draft manuscript prose, mutate files, or claim AgentLab receipts are missing;
  AgentLab owns runtime receipt creation outside the model response.
- If the request defines an exact machine-readable deliverable, return it completely
  before ancillary governance commentary.
"""
    elif narrative_heavy_audit and agent_name in {"Reviewer", "Scribe", "Verifier"}:
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
    elif media_visual_route and agent_name == "Reviewer":
        hard_rules = """
Independent media acceptance rules:
- Inspect the exact read-only candidate media plus sealed generation receipts and
  Observer evidence. You are the only role making visual quality judgments.
- Never mutate a media file, regenerate an asset, browse, scan, or promote anything.
- Return one YAML document only, with status and candidates. Each candidate must
  bind its candidate_id to separate aesthetic, continuity, technical, and
  factual_safety verdicts with concrete evidence.
- The ArtifactProducer cannot act as Observer, Reviewer, or Verifier. Do not copy
  or invent another role's identity; AgentLab stamps runtime identity itself.
- pending, unknown, missing_auth, missing evidence, or a hash mismatch is blocking.
- Set candidate_only true and production_modified false. Never self-approve.
"""
    elif media_visual_route and agent_name == "Verifier":
        hard_rules = """
Independent media verification rules:
- Verify only the sealed generation receipt, asset manifest, Observer report,
  Reviewer report, and their declared identities/hashes. Do not claim visual
  perception or repeat aesthetic judgments.
- Never mutate, regenerate, browse, scan, approve, or promote media.
- Return one YAML document only. Each candidate must contain status and checks
  for asset_integrity, evidence_chain, reviewer_independence, and
  promotion_boundary, each with a verdict and concrete evidence.
- pending, unknown, missing_auth, missing evidence, identity overlap, or a hash
  mismatch is blocking. Runtime performs the final byte-level hash recheck.
- Set candidate_only true and production_modified false. Never self-approve.
"""
    elif agent_name in {"Writer", "Reviewer", "Scribe"}:
        hard_rules = """
Creative writing execution rules:
- Do not request tools, shell commands, file listings, browser access, or repository scans.
- Use only the injected context, mission contract, and story authority files.
- Do not copy substantive prose from the previous candidate chapter.
- Writer and Scribe must emit AGENTLAB_EDIT blocks only for files listed in mission_contract.yml.
- Reviewer writes a review report only.
- Do not output DSML/tool-call markup.
- If context is incomplete, make the narrowest canon-preserving assumption and continue.
"""
    elif agent_name == "Observer" and output_path.name == "visual_observation_report.yml":
        hard_rules = """
Post-production visual Observer rules:
- Inspect only exact read-only assets staged from generated_assets_manifest.yml.
- Return one YAML document only with status and candidates; each candidate row
  must contain candidate_id, status, the exact asset path/hash/size, observations,
  and media locators: image keyframes, video keyframes+timestamps, audio
  timestamps, or PDF pages.
- Missing files, hashes, frames/pages/timestamps, auth, or inspection capability
  must remain explicit and blocking. Never infer that an asset was seen.
- Do not generate, edit, review, approve, or promote media. AgentLab stamps the
  actual Observer backend/model identity; do not invent runtime identity.
"""
    elif agent_name == "Observer":
        hard_rules = """
Read-only multimodal Observer rules:
- Inspect only the exact staged inputs named in this sealed task packet. Never scan,
  browse, invoke a shell, follow unrelated paths, or mutate the workspace.
- Treat long text, images, video, audio, and PDF files as evidence. Bind every
  observation to an input filename and, where applicable, a page, frame, or timestamp.
- Separate direct observation, scientific/external evidence supplied in the packet,
  inference, uncertainty, and actionable suggestion. Never fabricate a citation.
- Return observation_report.yml content only. Set candidate_only: true,
  production_modified: false, self_approved: false, and safety_receipt.writes: [].
- You are not a Writer or ArtifactProducer: do not draft final prose, generate media,
  edit an asset, aesthetically approve your own work, or promote any candidate.
"""
    elif production_pack_role_session:
        if artifact_cli_session:
            hard_rules = """
Production-pack ArtifactTask CLI execution rules:
- Use only the exact messages and files embedded in this task packet.
- Work only inside the isolated workspace. Local shell/file tools are allowed
  solely to create and validate the exact paths in required_outputs/write_scope.
- Do not read the AgentLab repository, project workspace, home directory,
  environment files, credentials, or any unlisted path.
- Do not browse or call any provider beyond the selected Qwen model endpoint.
- Create the declared files directly; do not emit AGENTLAB_EDIT blocks and do
  not write production or project memory. AgentLab copies only declared files.
- Treat every output as run-local candidate evidence and never auto-promote it.
"""
        else:
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
- Do not call media providers, browse, inspect unlisted paths, or emit source-code edits.
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
    elif agent_name == "Researcher":
        hard_rules = """
Bounded external Researcher rules:
- Use only the messages and local evidence embedded in this sealed task packet.
- Never inspect or scan the AgentLab repository, project workspace, home
  directory, environment files, credentials, or any undeclared local path.
- Local shell and file mutation are forbidden. The isolated workspace is
  read-only and the result must be returned through stdout only.
- Public web, social, and xAI search may be used only for the assigned research
  question. Preserve source URLs and retrieval timestamps, and distinguish
  observed facts from inference and uncertainty.
- Do not edit code, write longform final prose, generate media, act as an
  aesthetic judge, update project memory, or promote a candidate.
- If external research or authentication is unavailable, report that narrow
  blocker; never switch provider/model or fabricate sources.
"""
    elif agent_name == "ArtifactProducer":
        if artifact_cli_session:
            hard_rules += """

Isolated CLI ArtifactProducer rules:
- Work only inside the isolated workspace and create every exact path declared
  by artifact_task.yml validation.required_paths.
- Local file and shell tools may be used only for those outputs and their
  validation. Do not inspect unlisted paths or use network tools.
- Do not emit AGENTLAB_EDIT blocks. AgentLab copies only declared, validated
  outputs into the current task run and records hashes in a runtime receipt.
- Never edit source code, workflow configuration, project memory, or production.
"""
        else:
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
- Use this exact envelope for every file: `<!-- AGENTLAB_EDIT: filename.yml -->`, then raw YAML, then `<!-- END AGENTLAB_EDIT -->`.
- Every YAML file must set schema_version: 1, candidate_only: true, and production_modified: false.
- Those three boundary keys are mandatory at the YAML document top level; nested copies do not satisfy the contract.
- YAML sequence text containing `: ` must be quoted or written as a block scalar so the returned file parses deterministically.
- If the CLI runtime enforces a structured-output schema, return its files/content object instead of hand-writing YAML; AgentLab will serialize the validated object into these same AGENTLAB_EDIT files.
- fiction_review.yml: status pass|warn|blocked and findings list.
- continuity_failure_report.yml: status pass|warn|blocked, blocking_issue_count integer, and failures list.
- narrative_quality_scorecard.yml: status pass|warn|blocked, candidate_sha256, and one chapter entry with all six evidence-bound quality dimensions for every audited chapter; batch summaries without complete per-chapter coverage are invalid.
- state_transition_proposal.yml: status candidate, requires_user_promotion: true, and events list; every event scope is candidate_only.
- revision_or_rewrite_proposal.yml: status not_required|proposed|blocked, rewrite_required boolean, direct_draft_edits: false, and proposals list. Every proposed rewrite must be a scene-level revision contract with chapter_id, target_scene, problem_type, exact evidence, must_preserve, must_change, allowed_freedom, causal_requirements, character knowledge before/after, decision_cost, new_information, and forbidden_regressions.
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
- workflow_driver: {plan.execution_backend}

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
- workflow_driver: {plan.execution_backend}
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
    elif agent_name == "NarrativePlanner":
        planner_plan_summary = {
            "project": plan.project,
            "task_id": plan.task_id,
            "route": plan.route.model_dump(mode="json"),
            "required_outputs": (
                plan.included_agents.get("NarrativePlanner") or {}
            ).get("required_outputs", []),
            "validation_gates": plan.validation_gates,
        }
        user = f"""
Produce the AgentLab narrative rewrite plan for:

- project: {plan.project}
- task_id: {plan.task_id}
- target: chapter_state_plan.yml
- workflow_driver: {plan.execution_backend}

Output contract:

- Return one raw YAML mapping only. Do not wrap it in Markdown fences.
- Use only the chapter range, authority memory, outlines, audit findings, and
  rewrite proposals included in Available task context.
- The root must set schema_version 1, project {plan.project}, status candidate,
  candidate_only true, and production_modified false.
- Include chapter_range, target_character_range, hard_character_range,
  chapter_state_plan, and validation_contract.
- Include one ordered, contiguous entry per chapter with every field required by
  the NarrativePlanner template. Do not merge, skip, duplicate, or reset chapters.
- Do not produce fiction prose, a review, a receipt, or any other file.

Workflow plan summary:

{yaml.safe_dump(planner_plan_summary, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Writer":
        chapter_packet_data: dict[str, Any] = {}
        try:
            chapter_packet_data = yaml.safe_load(
                (run_dir / "chapter_packet.yml").read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            pass
        if not isinstance(chapter_packet_data, dict):
            chapter_packet_data = {}
        chapter_intent = chapter_packet_data.get("chapter_intent") or {}
        if not isinstance(chapter_intent, dict):
            chapter_intent = {}
        target_character_range = chapter_intent.get("target_character_range")
        hard_character_range = chapter_intent.get("hard_character_range")
        character_contract_section = (
            "\nDraft length contract (characters, deterministic gate):\n"
            f"- target_character_range: {target_character_range}\n"
            f"- hard_character_range: {hard_character_range}\n"
            "- fiction_draft.md must stay inside hard_character_range.\n"
            if isinstance(target_character_range, list)
            and isinstance(hard_character_range, list)
            else ""
        )
        retry_feedback = load_text_if_exists(
            run_dir / "writer_contract_retry_feedback.yml"
        ).strip()
        retry_feedback_section = (
            "\nContract retry correction (mandatory):\n\n"
            f"```yaml\n{retry_feedback}\n```\n"
            if retry_feedback
            else ""
        )
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
- workflow_driver: {plan.execution_backend}

Output contract:

- Do not write a prose report.
- Do not target capture_report_path with an AGENTLAB_EDIT block.
- Emit exactly one full-file AGENTLAB_EDIT block for each required Writer output allowed by mission_contract.yml.
- For narrative_light_chapter, the required outputs are normally fiction_draft.md, continuity_ledger.yml, state_transition_proposal.yml, and narrative_delivery_receipt.yml.
- Do not claim a file is delivered unless its complete content is present inside an AGENTLAB_EDIT block.
- Keep all generated files candidate-only under the run directory; do not write production/manuscript.
{character_contract_section}
{retry_feedback_section}

Workflow plan summary:

{yaml.safe_dump(writer_plan_summary, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Observer" and output_path.name == "visual_observation_report.yml":
        observer_inputs = [
            {
                "filename": path.name,
                "kind": (
                    "embedded_text"
                    if path.suffix.lower() in _OBSERVER_TEXT_SUFFIXES
                    else "staged_multimodal_file"
                ),
            }
            for path in observer_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
        ]
        user = f"""
Inspect the generated media candidates for independent visual observation.

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}

Return exactly one YAML mapping with status and candidates. Every candidate row
must contain candidate_id, status, the exact asset path/sha256/size_bytes,
observations, and modality locators (keyframes, timestamps, or pages).

Do not include observer identity; AgentLab stamps trusted runtime provenance.
Do not return markdown, edit blocks, generated media, or approval claims.

Assigned inputs:

{yaml.safe_dump(observer_inputs, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif media_visual_route and agent_name in {"Reviewer", "Verifier"}:
        visual_inputs = [
            {
                "filename": path.name,
                "kind": (
                    "embedded_text"
                    if path.suffix.lower() in _OBSERVER_TEXT_SUFFIXES
                    else "staged_multimodal_file"
                ),
            }
            for path in visual_acceptance_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
        ]
        output_contract = (
            "Each candidate row must contain candidate_id, status: complete, the "
            "exact inspected asset path/sha256/size_bytes, and "
            "dimensions for aesthetic, continuity, technical, and factual_safety. "
            "Every dimension requires a verdict and non-empty evidence. Inspect the "
            "actual staged visual input; if it cannot be inspected, block."
            if agent_name == "Reviewer"
            else "Each candidate row must contain candidate_id, status: complete, the "
            "exact verified asset path/sha256/size_bytes, and "
            "checks for asset_integrity, evidence_chain, reviewer_independence, and "
            "promotion_boundary. Every check requires a verdict and non-empty evidence. "
            "Do not claim direct visual inspection or emit dimensions."
        )
        user = f"""
Perform the independent {agent_name} stage for generated media candidates.

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}

Return exactly one YAML mapping with status and candidates. {output_contract}

Do not include reviewer identity; AgentLab stamps the trusted executed
backend/model/session. Do not return markdown, edits, mutations, or promotion.

Assigned inputs:

{yaml.safe_dump(visual_inputs, sort_keys=False, allow_unicode=True)}

Available task context:

{chr(10).join(context_sections)}
"""
    elif agent_name == "Observer":
        observer_inputs = [
            {
                "filename": path.name,
                "kind": (
                    "embedded_text"
                    if path.suffix.lower() in _OBSERVER_TEXT_SUFFIXES
                    else "staged_multimodal_file"
                ),
            }
            for path in observer_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
        ]
        user = f"""
Observe the bounded AgentLab evidence for:

- project: {plan.project}
- task_id: {plan.task_id}
- target_report_path: {output_path.name}
- workflow_driver: {plan.execution_backend}

Output contract:

- Return one complete YAML document for observation_report.yml and no edit blocks.
- Include schema_version, status, candidate_only, production_modified,
  self_approved, observations, scientific_evidence, uncertainties,
  actionable_suggestions, and safety_receipt. Do not invent a model receipt or
  local path; AgentLab attaches the runtime-owned role-scoped receipt after the
  CLI process exits.
- Each observation must identify its source filename plus page/frame/timestamp when
  that locator exists. Missing evidence must remain explicit, never guessed.
- Do not claim that an input was inspected unless it is listed below and actually
  available in the sealed packet or its read-only observer_inputs directory.

Assigned inputs:

{yaml.safe_dump(observer_inputs, sort_keys=False, allow_unicode=True)}

Workflow plan summary:

{yaml.safe_dump(_agent_plan_summary(plan, agent_name), sort_keys=False, allow_unicode=True)}

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
            ((artifact_task.get("validation") or {}).get("required_paths", []))
            if isinstance(artifact_task.get("validation"), dict)
            else []
        ) or (
            (plan.included_agents.get("ArtifactProducer") or {}).get("required_outputs", [])
            or [f"runs/{plan.task_id}/{output}" for output in (plan.production_pack or {}).get("required_outputs", [])]
        )
        synthesis_output_rules = ""
        if synthesis_candidate:
            synthesis_delivery_rule = (
                "Create every Required ArtifactProducer output directly in the isolated workspace; do not emit AGENTLAB_EDIT blocks."
                if artifact_cli_session
                else "Emit exactly one full-file AGENTLAB_EDIT block for each Required ArtifactProducer output, and no other edit blocks."
            )
            synthesis_output_rules = f"""
- This is production-pack synthesis. {synthesis_delivery_rule}
- Every target must use `runs/{plan.task_id}/<filename>` and belong to this task.
- Derive the candidate from domain_research_brief.md; do not return a generic or
  fake-provider scaffold.
- production_pack_proposal.yml must set top-level candidate_only: true and
  production_modified: false. Its pack.promotion_policy must set auto_promote:
  false and production_modified: false.
- The three YAML mappings must agree on memory records, lifecycle nodes, resource
  evidence boundaries, quality gates, and the synthesized pack id.
"""
        artifact_delivery_rules = (
            """
- Create every exact required output path directly inside the isolated workspace.
- Use local tools only to create and validate those declared paths.
- Do not emit AGENTLAB_EDIT blocks or claim any file that does not exist.
- AgentLab will copy only declared outputs and verify their bytes and hashes.
"""
            if artifact_cli_session
            else """
- Emit one complete full-file AGENTLAB_EDIT block for each text/YAML/JSON/HTML/CSS/JS required output you can produce.
- Binary outputs are unsupported on this direct API text path; report a capability mismatch rather than fabricating one.
- State "Commands run by this model call: none" unless explicit command evidence is present in Available task context.
"""
        )
        user = f"""
Produce the AgentLab non-code candidate artifacts for:

- project: {plan.project}
- task_id: {plan.task_id}
- capture_report_path: {output_path.name if synthesis_candidate else output_path}
- workflow_driver: {plan.execution_backend}
- artifact_model_call_mode: {'isolated_cli_file_materialization' if artifact_cli_session else 'direct_api_text_generation'}

Output contract:

- Do not produce a generic prose-only report when required artifact files are listed.
- Follow artifact_task.yml output.format and validation.required_paths exactly.
- For required production-pack outputs listed without a directory, target the run root path `runs/{plan.task_id}/<output>`.
- For candidate application/site/media planning artifacts, target only the approved candidate artifact directory from artifact_intent.
- Keep all outputs candidate-only unless artifact_intent declares a production path.
- If a required output cannot be produced, include the exact missing capability or input in artifact_producer_report.md.
{artifact_delivery_rules}
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
- workflow_driver: {plan.execution_backend}

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
- workflow_driver: {plan.execution_backend}

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
- workflow_driver: {plan.execution_backend}

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
        model_providers=configs.get("model_providers", {}),
        agent_model_profiles=configs.get("agent_model_profiles", {}),
        model_catalog=configs.get("model_catalog", {}),
        provider_override=provider_override,
        model_override=model_override,
    )
    return settings, configs


def _role_key_for_agent(agent_name: str) -> str:
    return normalize_role_key(agent_name)


def _artifact_task_profile_for_plan(
    agentlab_root: Path,
    plan: WorkflowPlan,
    configs: dict,
    budget_mode: str,
    execution_mode: str,
) -> dict:
    """Bind ArtifactProducer to the provider capable of the concrete artifact."""
    try:
        from agent_runtime.protocols.artifact_task import (
            DEFAULT_FORMAT_BY_TYPE,
            build_artifact_task_contract,
            capabilities_for_artifact_type,
            infer_artifact_components,
            infer_artifact_type,
            infer_output_format,
            route_artifact_provider,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from protocols.artifact_task import (
            DEFAULT_FORMAT_BY_TYPE,
            build_artifact_task_contract,
            capabilities_for_artifact_type,
            infer_artifact_components,
            infer_artifact_type,
            infer_output_format,
            route_artifact_provider,
        )

    run_dir = Path(plan.run_dir)
    contract_path = run_dir / "artifact_task.yml"
    contract: dict = {}
    if contract_path.exists():
        loaded = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            contract = loaded

    request_path = Path(plan.user_request_path)
    task_text = (
        request_path.read_text(encoding="utf-8", errors="replace")
        if request_path.exists()
        else str((plan.production_pack or {}).get("pack_id") or "")
    )
    artifact_type = str(contract.get("artifact_type") or "").strip()
    if not artifact_type:
        artifact_type = infer_artifact_type(task_text) or "text"
    artifact_components = list(
        contract.get("artifact_components")
        or infer_artifact_components(task_text)
        or [artifact_type]
    )
    output_format = str(
        ((contract.get("output") or {}).get("format") if isinstance(contract.get("output"), dict) else "")
        or infer_output_format(task_text, artifact_type)
        or DEFAULT_FORMAT_BY_TYPE.get(artifact_type, "artifact")
    )
    required = list(
        contract.get("required_capabilities")
        or capabilities_for_artifact_type(agentlab_root, artifact_type)
    )
    if artifact_type == "mixed" and artifact_components:
        required = list(
            dict.fromkeys(
                [
                    *required,
                    *[
                        capability
                        for component in artifact_components
                        for capability in capabilities_for_artifact_type(
                            agentlab_root,
                            str(component),
                        )
                    ],
                ]
            )
        )

    def normalize_output_path(raw: object) -> str | None:
        text = str(raw or "").strip()
        if not text:
            return None
        candidate = Path(text)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve(strict=False).relative_to(
                    Path(plan.project_root).resolve(strict=False)
                )
            except ValueError:
                try:
                    candidate = candidate.resolve(strict=False).relative_to(
                        Path(plan.agentlab_root).resolve(strict=False)
                    )
                except ValueError:
                    return None
        if ".." in candidate.parts:
            return None
        if candidate.parts[:2] == ("projects", plan.project):
            candidate = Path(*candidate.parts[2:])
        elif candidate.parts[:1] == ("projects",):
            return None
        if candidate.parts[:2] == ("runs", plan.task_id):
            return candidate.as_posix()
        if candidate.parts[:1] == ("runs",):
            return None
        return (Path("runs") / plan.task_id / candidate).as_posix()

    pack_outputs: list[str] = []
    declared_outputs = (
        (plan.included_agents.get("ArtifactProducer") or {}).get("required_outputs")
        or (plan.production_pack or {}).get("required_outputs")
        or []
    )
    for raw in declared_outputs:
        normalized = normalize_output_path(str(raw).replace("task_xxxx", plan.task_id))
        if normalized and normalized not in pack_outputs:
            pack_outputs.append(normalized)

    existing_output = (
        (contract.get("output") or {}).get("path")
        if isinstance(contract.get("output"), dict)
        else None
    )
    output_path = normalize_output_path(existing_output)
    if not output_path:
        compatible_suffixes = {
            "markdown": {".md", ".markdown"},
            "txt": {".txt"},
            "docx": {".docx"},
            "xlsx": {".xlsx"},
            "csv": {".csv"},
            "pptx": {".pptx"},
            "pdf": {".pdf"},
            "png": {".png"},
            "jpg": {".jpg", ".jpeg"},
            "webp": {".webp"},
            "mp4": {".mp4"},
            "mov": {".mov"},
            "wav": {".wav"},
            "mp3": {".mp3"},
        }.get(output_format, set())
        output_path = next(
            (
                path
                for path in pack_outputs
                if Path(path).suffix.lower() in compatible_suffixes
                and not any(
                    marker in Path(path).stem.lower()
                    for marker in (
                        "report",
                        "receipt",
                        "check",
                        "validation",
                        "manifest",
                        "ledger",
                        "proposal",
                    )
                )
            ),
            None,
        )
    if not output_path:
        output_path = (
            Path("runs")
            / plan.task_id
            / "artifacts"
            / f"{artifact_type}.{output_format}"
        ).as_posix()

    required_paths = list(dict.fromkeys([output_path, *pack_outputs]))
    existing_selected = (
        ((contract.get("routing") or {}).get("selected") or {})
        if isinstance(contract.get("routing"), dict)
        else {}
    )
    bound_provider = (
        str(existing_selected.get("provider_id") or "")
        if isinstance(existing_selected, dict)
        else ""
    )
    provider_type = "api" if execution_mode == "full_api" else "cli"
    assigned_inputs_declared = bool(contract) and "assigned_inputs" in contract
    assigned_inputs = contract.get("assigned_inputs") if assigned_inputs_declared else []
    direct_api_has_inputs = execution_mode == "full_api" and (
        (assigned_inputs_declared and not isinstance(assigned_inputs, list))
        or bool(assigned_inputs)
    )
    if direct_api_has_inputs:
        route = {
            "artifact_type": artifact_type,
            "output_format": output_format,
            "provider_type": "api",
            "required_capabilities": sorted(set(required)),
            "selected": None,
            "candidates": [],
            "status": "capability_mismatch",
            "mode_blocker": "full_api_assigned_inputs_unsupported",
        }
    elif execution_mode not in {"full_api", "full_cli"}:
        route = {
            "artifact_type": artifact_type,
            "output_format": output_format,
            "provider_type": None,
            "required_capabilities": sorted(set(required)),
            "selected": None,
            "candidates": [],
            "status": "capability_mismatch",
            "mode_blocker": f"unsupported_artifact_execution_mode:{execution_mode}",
        }
    else:
        route = route_artifact_provider(
            agentlab_root,
            artifact_type,
            required_capabilities=required,
            preferred_provider=bound_provider or None,
            provider_type=provider_type,
            output_format=output_format,
        )
    if not contract:
        contract = build_artifact_task_contract(
            agentlab_root,
            task_text,
            artifact_type=artifact_type,
            output_path=output_path,
            project=plan.project,
            task_id=plan.task_id,
        )
    contract["output"] = {"path": output_path, "format": output_format}
    contract["artifact_components"] = artifact_components
    contract["required_capabilities"] = required
    contract["required_outputs"] = required_paths
    contract["validation"] = {
        "mode": "required_paths_exist",
        "required_paths": required_paths,
    }
    contract["routing"] = route

    selected = route.get("selected") if isinstance(route, dict) else None
    profile = {
        "executor_type": "blocked",
        "cli_agent": "",
        "artifact_routing_status": route.get("status", "capability_mismatch"),
        "artifact_routing_reason": (
            f"no approved {provider_type} provider satisfies {artifact_type}/{output_format}: "
            f"{', '.join(required)}"
        ),
        "artifact_type": artifact_type,
        "_artifact_task_contract": contract,
    }
    if direct_api_has_inputs:
        profile["artifact_routing_reason"] = (
            "full_api ArtifactProducer does not support assigned file inputs; "
            "use the governed isolated CLI surface"
        )
    if not isinstance(selected, dict):
        return profile

    policy_path = agentlab_root / "config" / "artifact_task_policy.yml"
    policy = (
        yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        if policy_path.exists()
        else {}
    )
    provider_id = str(selected.get("provider_id") or "")
    provider_cfg = ((policy.get("providers") or {}).get(provider_id) or {})
    if provider_type == "api":
        if (
            provider_cfg.get("runtime_activation") == "explicit_full_api_only"
            and execution_mode != "full_api"
        ):
            profile["artifact_routing_status"] = "capability_mismatch"
            profile["artifact_routing_reason"] = (
                f"provider {provider_id} requires explicit full_api mode"
            )
            return profile
        profile.update(
            {
                "executor_type": "direct_api",
                "artifact_provider": provider_id,
                "artifact_allowed_runtime_providers": list(
                    provider_cfg.get("allowed_runtime_providers") or []
                ),
                "artifact_routing_status": "routed",
                "artifact_routing_reason": str(selected.get("reason") or ""),
            }
        )
        return profile

    tier = {
        "quality": "full",
        "balanced": "performance",
        "frugal": "low",
        "max_quality": "full",
    }.get(str(budget_mode).lower(), str(budget_mode).lower())
    route_map = provider_cfg.get("capacity_routes") or {}
    capacity_route_id = str(
        (route_map.get(tier) if isinstance(route_map, dict) else route_map) or ""
    )
    capacity_route = ((configs.get("model_capacity") or {}).get("routes") or {}).get(
        capacity_route_id
    ) or {}
    invocation_contract = str(capacity_route.get("invocation_contract") or "")
    worker = str(selected.get("worker") or "")
    contract_cfg = (
        (configs.get("worker_invocation_contracts") or {}).get("contracts") or {}
    ).get(invocation_contract) or {}
    if not (
        capacity_route_id
        and str(capacity_route.get("role") or "") == "artifact_producer"
        and str(capacity_route.get("worker") or "") == worker
        and str(contract_cfg.get("worker_id") or "") == worker
        and capacity_route.get("model_key")
    ):
        profile["artifact_routing_status"] = "capability_mismatch"
        profile["artifact_routing_reason"] = (
            f"provider {provider_id} lacks a matching CLI capacity/contract route"
        )
        return profile

    profile.update(
        {
            "executor_type": "cli_agent",
            "cli_agent": worker,
            "invocation_contract": invocation_contract,
            "default": str(capacity_route["model_key"]),
            "capacity_route": capacity_route_id,
            "artifact_provider": provider_id,
            "artifact_routing_status": "routed",
            "artifact_routing_reason": str(selected.get("reason") or ""),
        }
    )
    return profile


def _apply_writer_workflow_activation(
    plan: WorkflowPlan,
    configs: dict,
    profile: dict | None,
) -> dict | None:
    """Select the task-local Ultracode route only from an explicit plan opt-in."""

    if profile is None:
        return None
    writer_plan = plan.included_agents.get("Writer") or {}
    if (
        not isinstance(writer_plan, dict)
        or writer_plan.get("ultracode_opt_in") is not True
    ):
        return profile

    route_id = "WriterUltracode"
    route = ((configs.get("model_capacity") or {}).get("routes") or {}).get(
        route_id
    )
    contracts = (
        (configs.get("worker_invocation_contracts") or {}).get("contracts") or {}
    )
    contract_name = (
        str(route.get("invocation_contract") or "")
        if isinstance(route, dict)
        else ""
    )
    contract = contracts.get(contract_name) if contract_name else None
    worker = str(profile.get("cli_agent") or "")
    valid = bool(
        isinstance(route, dict)
        and str(route.get("role") or "") == "writer"
        and str(route.get("worker") or "") == worker == "claude_code"
        and contract_name == "claude_writer_ultracode"
        and isinstance(contract, dict)
        and str(contract.get("worker_id") or "") == worker
        and str(route.get("model_key") or "")
        and str(route.get("pool") or "")
        and not list(route.get("approved_fallbacks") or [])
    )
    activated = dict(profile)
    if not valid:
        activated.update(
            {
                "writer_workflow_activation_status": "blocked",
                "writer_workflow_activation_reason": (
                    "WriterUltracode capacity/contract binding is incomplete"
                ),
            }
        )
        return activated

    activated.update(
        {
            "invocation_contract": contract_name,
            "default": str(route["model_key"]),
            "capacity_route": route_id,
            "writer_workflow_activation_status": "requested",
            "writer_workflow": "developmental_ultracode",
            "writer_work_type": writer_plan.get("work_type"),
        }
    )
    return activated


def _resolve_cli_profile_for_agent(
    agentlab_root: Path,
    plan: WorkflowPlan,
    agent_name: str,
) -> tuple[dict, str, str, dict | None]:
    configs = load_agentlab_configs(agentlab_root)
    agent_model_profiles = configs.get("agent_model_profiles", {})
    budget_mode = getattr(plan, "budget_mode", "balanced") or "balanced"
    agent_role_key = _role_key_for_agent(agent_name)
    route_key = str(getattr(getattr(plan, "route", None), "route_key", "") or "")
    mode = os.getenv("AGENTLAB_MODE", agent_model_profiles.get("default_mode", "full_cli"))
    if agent_name == "Reviewer" and route_key == "media_generation_task":
        agent_role_key = "visual_reviewer"
    if agent_name == "ArtifactProducer" and route_key != "media_generation_task":
        return (
            configs,
            mode,
            agent_role_key,
            _artifact_task_profile_for_plan(
                agentlab_root,
                plan,
                configs,
                budget_mode,
                mode,
            ),
        )
    cli_role_profile = resolve_cli_profile(
        agent_model_profiles,
        agent_role=agent_role_key,
        budget_mode=budget_mode,
        mode=mode,
    )
    if agent_name == "Writer":
        cli_role_profile = _apply_writer_workflow_activation(
            plan,
            configs,
            cli_role_profile,
        )
    return configs, mode, agent_role_key, cli_role_profile


def _check_cli_role_binding(agentlab_root: Path, agent_name: str, cli_role_profile: dict) -> tuple[bool, str]:
    if cli_role_profile.get("artifact_routing_status") == "capability_mismatch":
        return False, str(
            cli_role_profile.get("artifact_routing_reason")
            or "artifact capability mismatch"
        )
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


def _blocked_artifact_capability_result(profile: dict) -> LLMCallResult:
    contract = profile.get("_artifact_task_contract") or {}
    route = contract.get("routing") if isinstance(contract, dict) else {}
    return LLMCallResult(
        provider="agentlab-artifact-router",
        model=str(profile.get("cli_agent") or "no_compatible_provider"),
        content=(
            "# ArtifactProducer capability mismatch\n\n"
            f"- Artifact type: {profile.get('artifact_type') or 'unknown'}\n"
            f"- Reason: {profile.get('artifact_routing_reason') or 'capability mismatch'}\n\n"
            "AgentLab did not start a provider and did not switch to an "
            "unapproved artifact backend."
        ),
        status="blocked_user_decision",
        error="capability_mismatch",
        raw_usage={
            "blocked": True,
            "reason": "capability_mismatch",
            "artifact_type": profile.get("artifact_type"),
            "required_capabilities": (
                contract.get("required_capabilities", [])
                if isinstance(contract, dict)
                else []
            ),
            "artifact_routing": route if isinstance(route, dict) else {},
            "provider_process_started": False,
            "provider_surface_changed": False,
            "direct_api_fallback_attempted": False,
        },
    )


def _blocked_writer_workflow_activation_result(profile: dict) -> LLMCallResult:
    reason = str(
        profile.get("writer_workflow_activation_reason")
        or "Ultracode activation policy is incomplete"
    )
    return LLMCallResult(
        provider="agentlab-protocol",
        model=str(profile.get("cli_agent") or "claude_code"),
        content=(
            "# Writer Ultracode activation blocked\n\n"
            f"- Reason: {reason}\n\n"
            "No provider process was started and the ordinary Writer route was "
            "not substituted for the requested developmental workflow."
        ),
        status="blocked_user_decision",
        error="writer_ultracode_activation_policy_invalid",
        raw_usage={
            "usage_source": "protocol_gate",
            "provider_process_started": False,
            "writer_workflow_activation_status": "blocked",
            "writer_workflow_activation_reason": reason,
            "provider_surface_changed": False,
        },
    )


def _apply_contract_bound_cli_model_override(
    configs: dict,
    plan: WorkflowPlan,
    agent_name: str,
    role_profile: dict,
    model_key: str,
    *,
    apply_patches: bool,
    allow_cli_api_fallback: bool,
) -> tuple[dict | None, str | None]:
    """Reject ad-hoc model swaps; approved alternatives live in model_capacity."""
    return None, (
        "Ad-hoc CLI model overrides are disabled. Declare a same-role route and "
        "failure class in config/model_capacity.yml instead."
    )


def _blocked_cli_model_override_result(
    agent_name: str,
    worker: str,
    model_key: str,
    reason: str,
) -> LLMCallResult:
    return LLMCallResult(
        provider="agentlab-protocol",
        model=worker or "unknown_cli_worker",
        content=(
            f"# {agent_name} CLI model override blocked\n\n"
            f"- CLI worker: {worker or 'unknown'}\n"
            f"- Requested model: {model_key}\n"
            f"- Reason: {reason}\n"
        ),
        status="blocked_user_decision",
        error="invalid_cli_model_override",
        raw_usage={
            "blocked": True,
            "reason": "invalid_cli_model_override",
            "executor_type": "cli_agent",
            "configured_cli_agent": worker or None,
            "requested_model_key": model_key,
        },
    )


def _capacity_profile_for_route(
    base_profile: dict,
    capacity_policy: dict,
    route_id: str,
) -> dict:
    route = (capacity_policy.get("routes") or {}).get(route_id) or {}
    profile = dict(base_profile)
    profile.update(
        {
            "cli_agent": route.get("worker"),
            "invocation_contract": route.get("invocation_contract"),
            "default": route.get("model_key"),
            "capacity_selected_route": route_id,
            "capacity_pool": route.get("pool"),
        }
    )
    profile.pop("binary_candidates", None)
    return profile


def _capacity_blocked_result(
    agent_name: str,
    primary_route: str,
    decision: dict,
    *,
    last_error: str | None = None,
) -> LLMCallResult:
    reset_at = decision.get("reset_at")
    remaining = decision.get("remaining")
    return LLMCallResult(
        provider="agentlab-capacity",
        model=primary_route,
        content=(
            f"# {agent_name} capacity routes unavailable\n\n"
            f"- Approved route chain: {primary_route}\n"
            f"- Failure class: {decision.get('failure_class') or 'unknown'}\n"
            f"- Observed reset: {reset_at or 'unknown'}\n"
            f"- Remaining capacity: {remaining if remaining is not None else 'unknown'}\n\n"
            "AgentLab exhausted only the pre-approved same-role routes and did not "
            "silently change provider surfaces."
            + (f"\n\nLast execution error: {last_error}" if last_error else "")
        ),
        status="blocked_user_decision",
        error="approved_capacity_routes_unavailable",
        raw_usage={
            "usage_source": "capacity_gate",
            "exact_usage_available": False,
            "exact_cost_available": False,
            "capacity_primary_route": primary_route,
            "capacity_route_id": decision.get("route_id"),
            "capacity_pool_id": decision.get("pool_id"),
            "capacity_status": decision.get("capacity_status", "unknown"),
            "capacity_failure_class": decision.get("failure_class"),
            "capacity_reset_at": reset_at,
            "capacity_remaining": remaining,
            "capacity_attempt_id": decision.get("attempt_id"),
            "provider_surface_changed": False,
            "direct_api_fallback_attempted": False,
        },
    )


def _capacity_failure_message(result: LLMCallResult) -> str:
    raw_usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
    failure_class = str(raw_usage.get("failure_class") or "").replace("_", " ")
    parts = [failure_class, str(result.error or ""), str(result.content or "")[-4000:]]
    return "\n".join(part for part in parts if part)


def _annotate_capacity_result(
    result: LLMCallResult,
    *,
    primary_route: str,
    decision: dict,
    observation: dict | None = None,
) -> None:
    raw_usage = dict(result.raw_usage or {})
    raw_usage.update(
        {
            "capacity_primary_route": primary_route,
            "capacity_route_id": decision.get("route_id"),
            "capacity_pool_id": decision.get("pool_id"),
            "capacity_status": decision.get("capacity_status", "unknown"),
            "capacity_selection_kind": decision.get("selection_kind"),
            "capacity_attempt_id": decision.get("attempt_id"),
            "capacity_remaining": (
                observation.get("remaining")
                if observation is not None
                else decision.get("remaining")
            ),
        }
    )
    if observation:
        raw_usage.update(
            {
                "capacity_failure_class": observation.get("failure_class"),
                "capacity_reset_at": observation.get("reset_at"),
                "capacity_observed_at": observation.get("observed_at"),
                "capacity_evidence_source": observation.get("source_kind"),
                "capacity_confidence": observation.get("confidence"),
            }
        )
    result.raw_usage = raw_usage


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
            "invocation_contract": cli_role_profile.get("invocation_contract"),
            "capacity_route": cli_role_profile.get("capacity_route"),
            "writer_workflow_activation_status": cli_role_profile.get(
                "writer_workflow_activation_status"
            ),
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
    cli_model_override: str | None = None,
    apply_patches: bool = True,
    allow_cli_api_fallback: bool = False,
):
    diagnostics_interval_started = monotonic()
    from operational_uploader import maybe_run_operational_agent

    operational_result = maybe_run_operational_agent(plan, agent_name)
    if operational_result is not None:
        return operational_result

    if agent_name == "NarrativePlanner":
        try:
            _validated_narrative_rewrite_inputs(agentlab_root, plan)
        except ValueError as exc:
            return LLMCallResult(
                provider="agentlab-protocol",
                model="claude_code",
                content=(
                    "# NarrativePlanner input contract blocked\n\n"
                    "The hash-bound narrative rewrite contract failed local "
                    "validation. No provider process was started.\n"
                ),
                status="blocked_user_decision",
                error=str(exc),
                raw_usage={
                    "usage_source": "protocol_gate",
                    "provider_process_started": False,
                },
            )

    if (
        agent_name == "ArtifactProducer"
        and plan.route.route_key == "media_generation_task"
    ):
        return LLMCallResult(
            provider="agentlab-media-backend",
            model="adapter_owned",
            content=(
                "# ArtifactProducer dispatch blocked\n\n"
                "Media ArtifactProducer execution is owned exclusively by "
                "pipeline_runner._execute_media_backend_role_outputs so one task "
                "cannot invoke the generation provider twice."
            ),
            status="blocked_user_decision",
            error="media_artifact_producer_requires_adapter_execution",
            raw_usage={
                "usage_source": "protocol_gate",
                "provider_process_started": False,
                "single_execution_authority": "media_backend_adapter",
            },
        )

    # ── CLI Agent dispatch (executor_type: cli_agent) ─────────────────────────
    # Route this call through the configured local CLI surface. A configured
    # CLI never falls through to direct API; only explicit full_api mode may
    # enter the API path below.
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
    artifact_api_profile: dict | None = None

    if cli_role_profile is not None:
        if cli_role_profile.get("writer_workflow_activation_status") == "blocked":
            return _blocked_writer_workflow_activation_result(cli_role_profile)
        artifact_contract = cli_role_profile.get("_artifact_task_contract")
        if agent_name == "ArtifactProducer" and isinstance(artifact_contract, dict):
            artifact_task_path = Path(plan.run_dir) / "artifact_task.yml"
            artifact_task_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_task_path.write_text(
                yaml.safe_dump(
                    artifact_contract,
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
        if cli_role_profile.get("artifact_routing_status") == "capability_mismatch":
            return _blocked_artifact_capability_result(cli_role_profile)
        if cli_role_profile.get("executor_type") == "direct_api":
            artifact_api_profile = cli_role_profile
            cli_role_profile = None

    if cli_role_profile is not None:
        if cli_model_override:
            override_worker = str(cli_role_profile.get("cli_agent") or "")
            overridden_profile, override_issue = _apply_contract_bound_cli_model_override(
                configs_for_cli,
                plan,
                agent_name,
                cli_role_profile,
                cli_model_override,
                apply_patches=apply_patches,
                allow_cli_api_fallback=allow_cli_api_fallback,
            )
            if override_issue:
                return _blocked_cli_model_override_result(
                    agent_name,
                    override_worker,
                    cli_model_override,
                    override_issue,
                )
            cli_role_profile = overridden_profile

        capacity_policy = configs_for_cli.get("model_capacity") or {}
        primary_capacity_route = str(cli_role_profile.get("capacity_route") or "").strip()
        capacity_manager = None
        capacity_decision: dict | None = None
        capacity_required_modalities: list[str] = []
        observer_capacity_source_paths: list[Path] | None = None
        if agent_name == "Observer":
            observer_capacity_source_paths = observer_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
            capacity_required_modalities = observer_required_modalities(
                observer_capacity_source_paths
            )
        elif (
            agent_name == "Reviewer"
            and plan.route.route_key == "media_generation_task"
        ):
            observer_capacity_source_paths = visual_acceptance_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            capacity_required_modalities = observer_required_modalities(
                observer_capacity_source_paths
            )
        if primary_capacity_route:
            try:
                from agent_runtime.model_capacity import ModelCapacity
            except ModuleNotFoundError:  # pragma: no cover - direct script path
                from model_capacity import ModelCapacity

            if not isinstance(capacity_policy, dict) or not capacity_policy.get("routes"):
                return _capacity_blocked_result(
                    agent_name,
                    primary_capacity_route,
                    {
                        "capacity_status": "unknown",
                        "failure_class": "capacity_policy_missing",
                        "reset_at": None,
                    },
                )
            capacity_manager = ModelCapacity(
                capacity_policy,
                Path(plan.run_dir)
                / str(
                    (capacity_policy.get("ledger") or {}).get(
                        "filename",
                        "model_capacity_ledger.yml",
                    )
                ),
            )
            try:
                capacity_decision = capacity_manager.select_route(
                    primary_capacity_route,
                    role=agent_name,
                    attempt_id=f"{plan.task_id}:{agent_name}:{uuid4().hex}",
                    required_modalities=capacity_required_modalities,
                )
            except (ValueError, TypeError) as exc:
                return _capacity_blocked_result(
                    agent_name,
                    primary_capacity_route,
                    {
                        "capacity_status": "unknown",
                        "failure_class": "invalid_capacity_policy",
                        "reset_at": None,
                    },
                    last_error=str(exc),
                )
            if capacity_decision.get("status") != "selected":
                return _capacity_blocked_result(
                    agent_name,
                    primary_capacity_route,
                    capacity_decision,
                )

        sealed_messages = None
        task_messages = None
        outbound_source_paths = None
        if agent_name == "Supervisor":
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = supervisor_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
        elif agent_name == "NarrativePlanner":
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = narrative_planner_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
        elif agent_name == "Writer":
            sealed_messages = compose_agent_messages(agentlab_root, plan, agent_name, output_path)
            outbound_source_paths = writer_context_source_files(
                agentlab_root, plan, output_path
            )
        elif agent_name == "Observer":
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = observer_capacity_source_paths or []
        elif (
            plan.route.route_key == "media_generation_task"
            and agent_name in {"Reviewer", "Verifier"}
        ):
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = visual_acceptance_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
        elif (
            plan.route.route_key == "narrative_heavy_audit"
            and agent_name in {"Reviewer", "Scribe", "Verifier"}
        ):
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = narrative_heavy_audit_context_source_files(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
        elif _is_production_pack_synthesis_role(plan, agent_name):
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
        elif agent_name == "ArtifactProducer":
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = artifact_producer_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )
        elif agent_name == "Researcher":
            sealed_messages = compose_agent_messages(
                agentlab_root,
                plan,
                agent_name,
                output_path,
            )
            outbound_source_paths = researcher_context_source_files(
                agentlab_root,
                plan,
                output_path,
            )

        attempted_capacity_routes: set[str] = set()
        while True:
            selected_profile = cli_role_profile
            if capacity_manager is not None and capacity_decision is not None:
                selected_profile = _capacity_profile_for_route(
                    cli_role_profile,
                    capacity_policy,
                    str(capacity_decision["route_id"]),
                )
                selected_profile["capacity_attempt_id"] = capacity_decision.get(
                    "attempt_id"
                )
                selected_profile["capacity_selection_kind"] = capacity_decision.get(
                    "selection_kind"
                )
            cli_configured_agent = selected_profile.get("cli_agent", "")
            if selected_profile.get("artifact_routing_status") == "capability_mismatch":
                return _blocked_artifact_capability_result(selected_profile)
            allowed, binding_reason = _check_cli_role_binding(
                agentlab_root,
                agent_name,
                selected_profile,
            )
            if not allowed:
                return _blocked_role_binding_result(
                    agent_name,
                    cli_configured_agent,
                    binding_reason,
                )
            cli_attempted = True
            local_orchestration_seconds = monotonic() - diagnostics_interval_started
            cli_result = run_cli_agent(
                plan,
                agent_name,
                selected_profile,
                sealed_messages=sealed_messages,
                task_messages=task_messages,
                outbound_source_paths=outbound_source_paths,
            )
            if isinstance(cli_result, CliAgentNotAvailable):
                cli_fallback_reason = (
                    f"{cli_result.reason}: {cli_result.detail[:300]}"
                    if hasattr(cli_result, "detail") and cli_result.detail
                    else getattr(cli_result, "reason", "cli_unavailable")
                )
                if capacity_manager is not None and capacity_decision is not None:
                    return _capacity_blocked_result(
                        agent_name,
                        primary_capacity_route,
                        capacity_decision,
                        last_error=cli_fallback_reason,
                    )
                break

            _audit_annotate_cli_result(cli_result, selected_profile, "cli_executed")
            from agent_runtime.narrative.diagnostics.telemetry import (
                record_narrative_invocation,
            )

            record_narrative_invocation(
                plan,
                agent_name,
                cli_result,
                provider_surface=f"cli_agent:{cli_configured_agent}",
                capacity_route=(
                    str(capacity_decision["route_id"])
                    if capacity_decision is not None
                    else selected_profile.get("capacity_route")
                ),
                local_orchestration_seconds=local_orchestration_seconds,
            )
            diagnostics_interval_started = monotonic()
            if capacity_manager is None or capacity_decision is None:
                finalized = _apply_agent_result_patches(
                    configs_for_cli,
                    plan,
                    agent_name,
                    cli_result,
                    apply_patches,
                )
                return _enforce_artifact_task_result(
                    plan,
                    agent_name,
                    output_path,
                    finalized,
                )

            selected_route = str(capacity_decision["route_id"])
            attempted_capacity_routes.add(selected_route)
            if cli_result.status == "completed":
                success_observation = capacity_manager.record_success(
                    selected_route,
                    attempt_id=str(capacity_decision["attempt_id"]),
                )
                _annotate_capacity_result(
                    cli_result,
                    primary_route=primary_capacity_route,
                    decision=capacity_decision,
                    observation=success_observation,
                )
                finalized = _apply_agent_result_patches(
                    configs_for_cli,
                    plan,
                    agent_name,
                    cli_result,
                    apply_patches,
                )
                return _enforce_artifact_task_result(
                    plan,
                    agent_name,
                    output_path,
                    finalized,
                )

            failure_observation = capacity_manager.record_failure(
                selected_route,
                message=_capacity_failure_message(cli_result),
                attempt_id=str(capacity_decision["attempt_id"]),
            )
            _annotate_capacity_result(
                cli_result,
                primary_route=primary_capacity_route,
                decision=capacity_decision,
                observation=failure_observation,
            )
            next_decision = capacity_manager.select_route(
                primary_capacity_route,
                role=agent_name,
                attempt_id=f"{plan.task_id}:{agent_name}:{uuid4().hex}",
                required_modalities=capacity_required_modalities,
            )
            next_route = str(next_decision.get("route_id") or "")
            if (
                next_decision.get("status") == "selected"
                and next_route
                and next_route not in attempted_capacity_routes
            ):
                capacity_decision = next_decision
                continue

            cli_result.raw_usage = {
                **dict(cli_result.raw_usage or {}),
                "capacity_route_chain_exhausted": True,
                "capacity_next_route_id": next_route or None,
                "capacity_next_route_already_attempted": bool(
                    next_decision.get("status") == "selected"
                    and next_route in attempted_capacity_routes
                ),
                "capacity_next_failure_class": next_decision.get("failure_class"),
                "capacity_next_reset_at": next_decision.get("reset_at"),
                "direct_api_fallback_attempted": False,
            }
            return cli_result

        if _is_production_pack_synthesis_role(plan, agent_name):
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
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model=cli_configured_agent or "unknown_cli_worker",
            content=(
                f"# {agent_name} CLI worker unavailable\n\n"
                "AgentLab refused to switch from the configured CLI worker to a direct-API provider. "
                "Select an explicit full_api mode or an approved capacity route.\n"
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
    if cli_role_profile is None and cli_mode != "full_api":
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="unconfigured_cli_worker",
            content=(
                f"# {agent_name} CLI profile missing\n\n"
                "AgentLab refused to use a direct-API provider outside explicit full_api mode.\n"
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
    if artifact_api_profile is not None:
        allowed_runtime_providers = set(
            artifact_api_profile.get("artifact_allowed_runtime_providers") or []
        )
        if (
            allowed_runtime_providers
            and str(settings.provider) not in allowed_runtime_providers
        ):
            blocked_profile = dict(artifact_api_profile)
            blocked_profile["artifact_routing_status"] = "capability_mismatch"
            blocked_profile["artifact_routing_reason"] = (
                f"selected API route requires one of "
                f"{sorted(allowed_runtime_providers)}, got {settings.provider}"
            )
            return _blocked_artifact_capability_result(blocked_profile)

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
    narrative_context_manifest_path: Path | None = None
    if agent_name == "Writer":
        try:
            from agent_runtime.outbound_context import write_outbound_context_manifest
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from outbound_context import write_outbound_context_manifest

        approval_required = (
            str(plan.task_id).startswith("task_narrative_eval_")
            or os.getenv("AGENTLAB_TRUSTED_LIVE_RUNNER") == "1"
        )
        narrative_context_manifest_path = (
            Path(plan.run_dir) / "outbound_context_manifest_writer.yml"
        )
        manifest = write_outbound_context_manifest(
            agentlab_root,
            narrative_context_manifest_path,
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
    elif _is_production_pack_synthesis_role(plan, agent_name):
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
    local_orchestration_seconds = monotonic() - diagnostics_interval_started
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

    from agent_runtime.narrative.diagnostics.telemetry import (
        record_narrative_invocation,
    )

    record_narrative_invocation(
        plan,
        agent_name,
        result,
        provider_surface=f"direct_api:{settings.provider}",
        context_manifest_path=narrative_context_manifest_path,
        local_orchestration_seconds=local_orchestration_seconds,
    )

    result = _apply_agent_result_patches(
        configs,
        plan,
        agent_name,
        result,
        apply_patches,
    )
    result = _enforce_artifact_task_result(
        plan,
        agent_name,
        output_path,
        result,
    )

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


def _apply_agent_result_patches(
    configs: dict,
    plan: WorkflowPlan,
    agent_name: str,
    result: LLMCallResult,
    apply_patches: bool,
) -> LLMCallResult:
    """Materialize governed text edit envelopes from API or isolated CLI output."""

    patch_application_allowed = _patch_application_enabled(
        configs,
        agent_name,
        apply_patches,
    )
    if (
        not patch_application_allowed
        and agent_name in {"Coder", "ArtifactProducer"}
        and apply_patches
        and _candidate_artifact_patch_application_allowed(plan)
    ):
        patch_application_allowed = True
    if not (
        patch_application_allowed
        and result.status == "completed"
        and result.content
    ):
        return result

    from patch_applicator import apply_all_patches, strip_edit_blocks_from_report
    from artifact_contract import has_unclosed_structured_edit_block

    if has_unclosed_structured_edit_block(result.content):
        result.raw_usage = {
            **(result.raw_usage or {}),
            "patch_applied": 0,
            "patch_failed": 1,
            "patch_blocked_reason": "unclosed_structured_edit_block",
        }
        return result

    patch_results = apply_all_patches(
        llm_output=result.content,
        project_root=Path(plan.project_root),
        allowed_files=_extract_allowed_files(plan),
    )
    if not patch_results:
        return result

    applied = [item for item in patch_results if item.success]
    failed = [item for item in patch_results if not item.success]
    summary: list[str] = []
    if applied:
        changed = [
            f"{item.path} (L{item.line_start}-{item.line_end})"
            for item in applied
        ]
        summary.append(f"Applied {len(applied)} edit(s) to: {', '.join(changed)}")
    if failed:
        errors = [f"{item.path}: {item.error}" for item in failed]
        summary.append(f"Failed {len(failed)} edit(s): {'; '.join(errors)}")
    result.content = (
        strip_edit_blocks_from_report(result.content)
        + "\n\n## Patch Application Results\n\n"
        + "\n".join(summary)
        + "\n"
    )
    result.raw_usage = {
        **(result.raw_usage or {}),
        "patch_applied": len(applied),
        "patch_failed": len(failed),
        "patch_details": [item.__dict__ for item in patch_results],
    }
    return result


def _enforce_artifact_task_result(
    plan: WorkflowPlan,
    agent_name: str,
    output_path: Path,
    result: LLMCallResult,
) -> LLMCallResult:
    if agent_name != "ArtifactProducer" or result.status != "completed":
        return result
    try:
        from agent_runtime.artifact_contract import validate_artifact_task_outputs
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from artifact_contract import validate_artifact_task_outputs

    issues = validate_artifact_task_outputs(
        Path(plan.run_dir),
        deferred_paths={output_path.name},
    )
    raw_usage = result.raw_usage or {}
    current_attempt_paths = {
        str(item.get("path") or "")
        for item in raw_usage.get("patch_details", [])
        if isinstance(item, dict) and item.get("success") is True
    }
    if (
        raw_usage.get("executor_type") == "direct_api"
        and not raw_usage.get("artifact_materialization_receipt")
    ):
        contract_path = Path(plan.run_dir) / "artifact_task.yml"
        try:
            contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            contract = {}
        validation = contract.get("validation") if isinstance(contract, dict) else {}
        required_paths = (
            validation.get("required_paths")
            if isinstance(validation, dict)
            else []
        )
        for raw in required_paths if isinstance(required_paths, list) else []:
            normalized = Path(str(raw)).as_posix()
            if Path(normalized).name == output_path.name:
                continue
            if normalized not in current_attempt_paths:
                issues.append(
                    {
                        "file": normalized,
                        "issue": "not_materialized_by_current_direct_api_attempt",
                    }
                )
    if not issues:
        result.raw_usage = {
            **(result.raw_usage or {}),
            "artifact_task_validation": "pass",
            "artifact_task_validation_issues": [],
        }
        return result
    result.status = "blocked_user_decision"
    result.error = "artifact_validation_failed"
    result.raw_usage = {
        **(result.raw_usage or {}),
        "artifact_task_validation": "fail",
        "artifact_task_validation_issues": issues,
    }
    result.content = (
        result.content.rstrip()
        + "\n\n## ArtifactTask validation\n\n"
        + "Required outputs were not materialized or failed format validation:\n"
        + "\n".join(
            f"- {item['file']}: {item['issue']}" for item in issues
        )
        + "\n"
    )
    return result


def _extract_allowed_files(plan: WorkflowPlan) -> set[str] | None:
    """Extract Supervisor-approved file paths from the plan, if available."""
    included = plan.included_agents or {}
    coder_config = included.get("Coder", {}) or plan.included_agents.get("Coder", {})
    allowed_from_artifact_task: set[str] = set()
    artifact_task_path = Path(plan.run_dir) / "artifact_task.yml"
    if artifact_task_path.exists():
        try:
            artifact_task = yaml.safe_load(
                artifact_task_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            artifact_task = {}
        validation = (
            artifact_task.get("validation")
            if isinstance(artifact_task, dict)
            else {}
        )
        required_paths = (
            validation.get("required_paths")
            if isinstance(validation, dict)
            else []
        )
        for raw in required_paths if isinstance(required_paths, list) else []:
            path = Path(str(raw))
            if (
                not path.is_absolute()
                and ".." not in path.parts
                and path.parts[:2] == ("runs", plan.task_id)
            ):
                allowed_from_artifact_task.add(path.as_posix())
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
        return allowed_from_contract | allowed_from_artifact_task
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
        return allowed_from_artifact_intent | allowed_from_artifact_task
    if not coder_config:
        return allowed_from_artifact_task or None
    allowed = coder_config.get("allowed_files") or coder_config.get("editable_files")
    if allowed and isinstance(allowed, list):
        return {str(f) for f in allowed} | allowed_from_artifact_task
    return allowed_from_artifact_task or None


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
        "NarrativePlanner": "narrative_planner",
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
        "resolved_model_key": role_profile.get("default", ""),
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
