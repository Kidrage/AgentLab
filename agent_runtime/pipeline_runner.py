"""AgentLab Dry-run Pipeline Runner.

Single-step node executor. No recursion — iteration is caller's responsibility.
Supports quota failure simulation and resume.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import re
import subprocess
from uuid import uuid4
import yaml

from atomic_io import atomic_write_yaml
from lifecycle_graph import (
    load_lifecycle, save_lifecycle, next_node, mark_node_started,
    mark_node_completed, mark_node_failed,
    LIFECYCLE_NODES, OPTIONAL_NODES,
    create_lifecycle,
    _production_pack_nodes,
    _skip_reason_for_node,
)
from fake_provider import fake_output_for_agent
from artifact_contract import (
    artifact_content_issues,
    validate_artifacts,
    write_artifact_manifest,
)
from command_runner import run_validation_commands_if_present
from state_store import load_state, save_state
from progress_tracker import create_progress, load_progress, save_progress
from task_events import append_task_event, classify_blocked_status
from feedback_manager import create_decision_card, write_feedback_status

try:
    from ingestion.github_reader import extract_github_urls, build_repo_manifest, parse_github_url
    from ingestion.repo_manifest import write_repo_manifest, RepoManifest
    from ingestion.resource_ledger import ResourceLedger, write_resource_ledger
except ImportError:  # pragma: no cover
    extract_github_urls = None
    build_repo_manifest = None
    parse_github_url = None
    write_repo_manifest = None
    RepoManifest = None
    ResourceLedger = None
    write_resource_ledger = None

ARTIFACT_ALIASES = {
    "01_supervisor_plan.md": "supervisor_plan.md",
    "02_reposcout_report.md": "reposcout_report.md",
    "06_implementation_report.md": "implementation_report.md",
    "07_validation_report.md": "validation_report.md",
    "09_archive_update.md": "archive_update.md",
}

NODE_TO_AGENT = {
    "SUPERVISOR_PLAN": "Supervisor",
    "REPO_CONTEXT": "RepoScout",
    "RESEARCH_OPTIONAL": "Researcher",
    "OBSERVATION_OPTIONAL": "Observer",
    "INTERFACE_OPTIONAL": "InterfaceMapper",
    "WRITER_DRAFT": "Writer",
    "FICTION_REVIEW": "Reviewer",
    "SCRIBE_LEDGER": "Scribe",
    "CODER_IMPLEMENTATION": "Coder",
    "ARTIFACT_PRODUCTION": "ArtifactProducer",
    "VISUAL_OBSERVATION": "Observer",
    "VISUAL_REVIEW": "Reviewer",
    "VALIDATION": "TesterAuditor",
    "AUDIT": "TesterAuditor",
    "VERIFY": "Verifier",
    "ARCHIVE": "Archivist",
}

NODE_TO_REPORT = {
    "SUPERVISOR_PLAN": "01_supervisor_plan.md",
    "REPO_CONTEXT": "02_reposcout_report.md",
    "RESEARCH_OPTIONAL": "03_research_notes.md",
    "OBSERVATION_OPTIONAL": "observation_report.yml",
    "INTERFACE_OPTIONAL": "04_interface_map.md",
    "WRITER_DRAFT": "fiction_draft.md",
    "FICTION_REVIEW": "fiction_review.yml",
    "SCRIBE_LEDGER": "continuity_ledger.yml",
    "CODER_IMPLEMENTATION": "06_implementation_report.md",
    "ARTIFACT_PRODUCTION": "artifact_producer_report.md",
    "VISUAL_OBSERVATION": "visual_observation_report.yml",
    "VISUAL_REVIEW": "visual_review_report.yml",
    "VALIDATION": "07_validation_report.md",
    "AUDIT": "08_audit_report.md",
    "VERIFY": "verification_report.md",
    "ARCHIVE": "09_archive_update.md",
    "SELF_CHECK": "self_check_report.yml",
    "SYNC_OPTIONAL": "sync_report.yml",
}

NODE_TO_PROGRESS = {
    "INIT_TASK": "init", "CONTEXT_PROFILE": "context_profile",
    "CONTEXT_BUDGET": "context_budget", "CONTEXT_PACK": "context_pack", "PREPARE_PLAN": "planning",
    "SUPERVISOR_PLAN": "planning", "REPO_CONTEXT": "scouting",
    "RESEARCH_OPTIONAL": "research", "OBSERVATION_OPTIONAL": "observing",
    "INTERFACE_OPTIONAL": "interfacing",
    "WRITER_DRAFT": "writing", "FICTION_REVIEW": "reviewing", "SCRIBE_LEDGER": "ledgering",
    "CODER_IMPLEMENTATION": "implementation", "ARTIFACT_PRODUCTION": "artifact_production",
    "VISUAL_OBSERVATION": "visual_observing", "VISUAL_REVIEW": "visual_reviewing",
    "VALIDATION": "validation",
    "AUDIT": "audit", "VERIFY": "verifying", "ARCHIVE": "archiving",
    "SELF_CHECK": "checking", "SYNC_OPTIONAL": "syncing", "FINALIZE": "completing",
}

NODE_TO_PCT = {
    "INIT_TASK": 5, "CONTEXT_PROFILE": 7, "CONTEXT_BUDGET": 8, "CONTEXT_PACK": 9,
    "PREPARE_PLAN": 10, "SUPERVISOR_PLAN": 20,
    "REPO_CONTEXT": 30, "RESEARCH_OPTIONAL": 35, "OBSERVATION_OPTIONAL": 38,
    "INTERFACE_OPTIONAL": 40,
    "WRITER_DRAFT": 45, "FICTION_REVIEW": 50, "SCRIBE_LEDGER": 53,
    "CODER_IMPLEMENTATION": 55, "ARTIFACT_PRODUCTION": 62,
    "VISUAL_OBSERVATION": 65, "VISUAL_REVIEW": 68,
    "VALIDATION": 70, "AUDIT": 78,
    "VERIFY": 82, "ARCHIVE": 86, "SELF_CHECK": 90, "SYNC_OPTIONAL": 95, "FINALIZE": 100,
}


def _repo_analysis_requested(text: str) -> bool:
    lowered = (text or "").lower()
    triggers = [
        "repo analysis", "repo profile", "repository review", "architecture analysis",
        "analyze repository", "analyse repository", "分析仓库", "仓库分析", "架构分析",
    ]
    clone_triggers = ["git clone", "full clone", "clone/build/test", "build and test", "run tests"]
    return any(t in lowered for t in triggers) and not any(t in lowered for t in clone_triggers)


def _write_repo_stage_context(run_dir: Path, manifest_paths: list[Path], warnings: list[str]) -> None:
    context = {
        "repo_profile": {
            "access_mode": "repo_profile",
            "clone_allowed": False,
            "full_clone_allowed": False,
            "build_allowed": False,
            "repo_manifest_paths": [str(path) for path in manifest_paths],
            "warnings": warnings,
        }
    }
    path = run_dir / "stage_context.yml"
    existing = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}
    existing.update(context)
    atomic_write_yaml(path, existing)


def ensure_repo_manifest_for_run(agentlab_root: Path, project: str, task_id: str) -> list[Path]:
    """API-first repo ingestion hook for repo analysis/profile tasks."""
    if extract_github_urls is None or build_repo_manifest is None:
        return []
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    request_path = run_dir / "user_request.md"
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
    urls = extract_github_urls(task_text)
    if not urls or not _repo_analysis_requested(task_text):
        return []
    existing_single = run_dir / "repo_manifest.json"
    if existing_single.exists():
        _write_repo_stage_context(run_dir, [existing_single], [])
        return [existing_single]
    manifest_paths: list[Path] = []
    warnings: list[str] = []
    manifests_dir = run_dir / "repo_manifests"
    for index, url in enumerate(urls):
        try:
            manifest = build_repo_manifest(url, mode="repo_profile", agentlab_root=agentlab_root)
        except Exception as exc:
            ref = parse_github_url(url) if parse_github_url else None
            manifest = RepoManifest(
                repo_url=getattr(ref, "repo_url", url),
                owner=getattr(ref, "owner", "unknown"),
                repo=getattr(ref, "repo", "unknown"),
                ref=getattr(ref, "ref", "main"),
                clone_performed=False,
                warnings=[f"repo_manifest_build_failed: {type(exc).__name__}: {exc}"],
            )
        warnings.extend(manifest.warnings)
        if len(urls) == 1:
            path = write_repo_manifest(run_dir, manifest)
        else:
            manifests_dir.mkdir(parents=True, exist_ok=True)
            path = manifests_dir / f"{manifest.owner}__{manifest.repo}.json"
            from atomic_io import atomic_write_json
            atomic_write_json(path, manifest.as_dict())
        manifest_paths.append(path)

    if manifest_paths and ResourceLedger is not None:
        first_manifest_data = None
        try:
            import json
            first_manifest_data = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        except Exception:
            first_manifest_data = None
        ledger = ResourceLedger.from_manifest(task_id, first_manifest_data or {"repo_url": urls[0], "files_read": [], "bytes_downloaded": 0, "clone_performed": False})
        ledger.repo_access.update({
            "access_mode": "repo_profile",
            "clone_allowed": False,
            "full_clone_allowed": False,
            "build_allowed": False,
            "clone_performed": False,
            "manifest_paths": [str(path) for path in manifest_paths],
            "warnings": warnings,
        })
        write_resource_ledger(run_dir, ledger)
    _write_repo_stage_context(run_dir, manifest_paths, warnings)
    return manifest_paths


def _resolve_execution_mode(dry_run: bool, fake_provider: bool) -> dict:
    """Resolve execution mode based on dry_run and fake_provider flags.

    Returns a dict with:
      - execution_mode: str (dry_run / mock_provider / execute)
      - effective_fake_provider: bool
      - allow_real_provider: bool
      - allow_patches: bool
    """
    if dry_run:
        return {
            "execution_mode": "dry_run",
            "effective_fake_provider": True,
            "allow_real_provider": False,
            "allow_patches": False,
        }
    if fake_provider:
        return {
            "execution_mode": "mock_provider",
            "effective_fake_provider": True,
            "allow_real_provider": False,
            "allow_patches": False,
        }
    return {
        "execution_mode": "execute",
        "effective_fake_provider": False,
        "allow_real_provider": True,
        "allow_patches": True,
    }


def _safe_block_reason(reason: str, max_chars: int = 500) -> str:
    try:
        from agent_runtime.recovery.redaction import redact_context_text
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from recovery.redaction import redact_context_text

    redacted, _warnings = redact_context_text(str(reason or "unspecified_block"))
    compact = " ".join(redacted.split()) or "unspecified_block"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _block_task(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
    *,
    agent: str | None,
    reason: str,
    stage: str = "blocked",
    report_path: Path | None = None,
    user_action_required: bool = True,
    block_type: str = "generic",
    execution_mode: str | None = None,
    mark_lifecycle: bool = True,
) -> dict:
    """Unified helper to write blocked state across state/progress/lifecycle.

    Always writes USER_DECISION_REQUIRED.md when user_action_required=True.
    Returns a dict with status='paused' and success=False.

    mark_lifecycle: When False, skips mark_node_failed to avoid creating
                    non-standard nodes (e.g. "PIPELINE") in lifecycle.yml.
    """
    reason = _safe_block_reason(reason)
    if mark_lifecycle:
        mark_node_failed(run_dir, node_id, reason)
    state = load_state(run_dir, project, task_id)
    state.status = "blocked"
    state.current_agent = agent
    state.last_event = f"Blocked at {node_id}: {reason}"
    save_state(run_dir, state)

    progress = load_progress(run_dir)
    if progress:
        progress["status"] = "blocked"
        progress["current_agent"] = None
        progress["current_stage"] = stage
        progress["last_event"] = state.last_event
        if agent and agent in progress.get("agents", {}):
            progress["agents"][agent]["status"] = "blocked"
        save_progress(run_dir, progress)

    if user_action_required:
        decision_lines = [
            "# User Decision Required",
            "",
            f"- Project: {project}",
            f"- Task: {task_id}",
            f"- Node: {node_id}",
            f"- Block Type: {block_type}",
            f"- Reason: {reason}",
        ]
        if report_path and report_path.exists():
            decision_lines.append(f"- Evidence: {report_path}")
        (run_dir / "USER_DECISION_REQUIRED.md").write_text(
            "\n".join(decision_lines) + "\n", encoding="utf-8"
        )
        card, card_path = create_decision_card(
            run_dir,
            task_id=task_id,
            card_type=block_type,
            title=f"{node_id} requires user action",
            reason=reason,
            stage=stage,
            risk="medium",
            options=[
                {"id": "approve_resume", "label": "Approve resume", "risk": "medium"},
                {"id": "defer", "label": "Defer", "risk": "low"},
                {"id": "stop_task", "label": "Stop task", "risk": "none"},
            ],
            recommended_action="approve_resume",
        )
    else:
        card = None
        card_path = None

    append_task_event(
        run_dir,
        "NODE_BLOCKED",
        stage=stage,
        status=classify_blocked_status(block_type),
        severity="BLOCKED" if user_action_required else "FAILED_RECOVERABLE",
        message=reason,
        payload={
            "project": project,
            "task_id": task_id,
            "node": node_id,
            "agent": agent,
            "block_type": block_type,
            "report_path": str(report_path) if report_path else None,
            "decision_card": str(card_path) if card_path else None,
        },
    )
    feedback_status_path = write_feedback_status(run_dir)

    result: dict = {
        "status": "paused",
        "node": node_id,
        "message": reason,
        "block_type": block_type,
        "requires_user_action": user_action_required,
        "success": False,
        "feedback_status": str(feedback_status_path),
    }
    if card_path and card:
        result["decision_card"] = str(card_path)
        result["decision_id"] = card.get("id")
    if execution_mode:
        result["execution_mode"] = execution_mode

    # ── P1-3: Sync task_card.yml and task_index.yml on blocked state ──
    _sync_task_summary(agentlab_root, project, task_id, run_dir)

    return result


def _mark_node_completed(run_dir: Path, node_id: str, report_path: str | None = None) -> None:
    mark_node_completed(run_dir, node_id, report_path)
    append_task_event(
        run_dir,
        "NODE_COMPLETED",
        stage=NODE_TO_PROGRESS.get(node_id, node_id.lower()),
        status="RUNNING",
        severity="MILESTONE",
        message=f"{node_id} completed.",
        payload={"node": node_id, "report_path": report_path},
    )
    write_feedback_status(run_dir)


def _write_pipeline_incident(
    run_dir: Path,
    *,
    incident_type: str,
    reason: str,
    node_id: str | None = None,
    max_steps: int | None = None,
) -> Path:
    """Write pipeline_incident.yml for pipeline-level errors.

    These incidents are orthogonal to agent-level lifecycle nodes.
    """
    import datetime as dt_mod
    incident = {
        "version": 1,
        "incident_type": incident_type,
        "reason": reason,
        "node_id": node_id,
        "max_steps": max_steps,
        "created_at": dt_mod.datetime.now(dt_mod.timezone.utc).isoformat(),
    }
    path = run_dir / "pipeline_incident.yml"
    path.write_text(
        yaml.safe_dump(incident, sort_keys=False), encoding="utf-8"
    )
    return path


def _sync_task_summary(
    agentlab_root: Path, project: str, task_id: str, run_dir: Path,
) -> None:
    """Refresh task_card.yml and project-level task_index.yml for a run.

    Non-fatal — writes index_sync_warning.log on failure so
    missing task_card/task_index sync is visible.
    """
    try:
        from task_index import (
            generate_per_task_artifacts,
            build_project_task_index,
            save_project_task_index,
        )
        # Refresh per-task card
        generate_per_task_artifacts(agentlab_root, project, task_id)
        # Refresh project-level index
        index = build_project_task_index(agentlab_root, project)
        save_project_task_index(agentlab_root, project, index)
    except Exception as exc:
        warning_path = run_dir / "index_sync_warning.log"
        warning_lines = [
            "# Task Index Sync Warning",
            "",
            f"- Project: {project}",
            f"- Task: {task_id}",
            f"- Exception Type: {type(exc).__name__}",
            f"- Exception Message: {exc}",
            "",
            "This warning did not stop the pipeline, but task_card.yml or task_index.yml may be stale.",
        ]
        warning_path.write_text("\n".join(warning_lines), encoding="utf-8")



def _write_artifact_alias(run_dir: Path, report_name: str) -> None:
    alias = ARTIFACT_ALIASES.get(report_name)
    if alias and (run_dir / report_name).exists():
        (run_dir / alias).write_text(
            (run_dir / report_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _normalize_pack_output_path(raw: str) -> Path | None:
    text = raw.strip()
    if not text:
        return None
    for prefix in ("runs/task_xxxx/", "runs/<task_id>/", "./"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _write_pack_candidate_outputs(
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    execution_mode: str,
) -> list[str]:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return []
    try:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    pack = plan.get("production_pack") if isinstance(plan, dict) else {}
    if not isinstance(pack, dict):
        return []
    outputs = pack.get("required_outputs")
    if not isinstance(outputs, list) or not outputs:
        return []

    written: list[str] = []
    pack_id = str(pack.get("pack_id") or "unknown")
    independently_owned_media_outputs = {
        "media_qc_report.yml",
        "visual_observation_report.yml",
        "visual_review_report.yml",
        "visual_verification_report.yml",
        "visual_acceptance_candidate.yml",
        "visual_acceptance_decision.yml",
    }
    for output in outputs:
        rel_path = _normalize_pack_output_path(str(output))
        if rel_path is None:
            continue
        if (
            pack_id in {"media_generation", "media_series_production"}
            and rel_path.name in independently_owned_media_outputs
        ):
            continue
        path = run_dir / rel_path
        existing_text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        rewrite_synthesis_scaffold = (
            bool(existing_text)
            and pack_id == "pack_synthesis_candidate"
            and rel_path.name
            in {
                "production_pack_proposal.yml",
                "domain_memory_contract.yml",
                "lifecycle_profile.yml",
            }
        )
        if existing_text and not rewrite_synthesis_scaffold:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in {".yml", ".yaml"}:
            atomic_write_yaml(
                path,
                _pack_candidate_payload(
                    pack_id,
                    rel_path.as_posix(),
                    project,
                    task_id,
                    execution_mode=execution_mode,
                    pack=pack,
                ),
            )
        else:
            path.write_text(
                "\n".join([
                    f"# {rel_path.name}",
                    "",
                    f"- project: {project}",
                    f"- task_id: {task_id}",
                    f"- production_pack: {pack_id}",
                    "- status: candidate",
                    f"- execution_mode: {execution_mode}",
                    "- generated_by: fake_provider",
                    "",
                ]),
                encoding="utf-8",
            )
        written.append(rel_path.as_posix())
    return written


def _workflow_plan_for_run(run_dir: Path) -> dict:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return {}
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_synthesis_domain_research_brief(
    run_dir: Path,
    *,
    source_report: Path | None = None,
    execution_mode: str,
    source_provider: str | None = None,
    source_model: str | None = None,
    source_status: str | None = None,
) -> str | None:
    from hashlib import sha256

    plan = _workflow_plan_for_run(run_dir)
    pack = plan.get("production_pack") if isinstance(plan, dict) else {}
    if not isinstance(pack, dict) or pack.get("status") != "synthesis_candidate":
        return None
    path = run_dir / "domain_research_brief.md"
    contract_path = run_dir / "production_pack_research_contract.yml"
    source_excerpt = ""
    if source_report and source_report.exists():
        source_excerpt = source_report.read_text(encoding="utf-8").strip()
    source_sha256 = (
        sha256(source_excerpt.encode("utf-8")).hexdigest()
        if source_excerpt
        else None
    )
    provider_returned = (
        execution_mode == "execute"
        and bool(source_excerpt)
        and source_status == "completed"
        and source_provider != "fake_provider"
    )
    if path.exists() and contract_path.exists():
        existing_text = path.read_text(encoding="utf-8").strip()
        existing_contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        expected_status = "pass" if execution_mode == "execute" else "scaffold"
        if (
            existing_text
            and "## Resource Discovery Contract" in existing_text
            and "evidence_ledger_required" in existing_text
            and "memory_promotion_boundary" in existing_text
            and "## Promotion Boundary" in existing_text
            and existing_contract.get("status") == expected_status
            and existing_contract.get("execution_mode") == execution_mode
            and existing_contract.get("source_report")
            == (source_report.name if source_report else None)
            and existing_contract.get("source_provider") == source_provider
            and existing_contract.get("source_model") == source_model
            and existing_contract.get("source_status") == source_status
            and existing_contract.get("provider_returned_research")
            == provider_returned
            and existing_contract.get("source_sha256") == source_sha256
        ):
            return path.name
    route = plan.get("route", {}) if isinstance(plan, dict) else {}
    route_key = route.get("route_key") if isinstance(route, dict) else pack.get("route_key")
    content = "\n".join([
        "# Domain Research Brief",
        "",
        f"- production_pack: {pack.get('pack_id', 'pack_synthesis_candidate')}",
        f"- task_domain: {pack.get('task_domain') or 'unknown'}",
        f"- artifact_type: {pack.get('artifact_type') or 'unknown'}",
        f"- route_key: {route_key or 'unknown'}",
        f"- execution_mode: {execution_mode}",
        "",
        "## Capability Questions",
        "- What external tools/providers/files are needed?",
        "- What persistent state must be remembered between runs?",
        "- Which lifecycle nodes are needed, and which code-factory nodes are forbidden?",
        "",
        "## Resource Discovery Contract",
        "- resource_discovery_required: true",
        "- resource_sources: user_provided_files, configured_local_tools, registered_role_workers",
        "- optional_external_research: evidence gathering only after approval",
        "- authority_boundary: external research may inform a proposal but does not become project memory",
        "- evidence_ledger_required: source notes and external findings stay in a run-local evidence ledger",
        "- memory_promotion_boundary: external findings require review before any fact snapshot or project memory update",
        "- tool_selection_policy: prefer internal AgentLab role workers and registered local CLIs before new providers",
        "",
        "## Candidate Memory Requirements",
        "- domain_state_snapshot",
        "- artifact_index",
        "- generation_or_revision_ledger",
        "- delivery_receipt",
        "",
        "## Promotion Boundary",
        "- candidate_only: true",
        "- production_modified: false",
        "- promotion_requires: human_or_supervisor_approval",
        "- candidate_facts_remain_run_local_until_promotion",
        "",
        "## Source Research Notes",
        source_excerpt or "Dry-run research scaffold: no external lookup was performed.",
        "",
    ])
    path.write_text(content, encoding="utf-8")
    atomic_write_yaml(
        contract_path,
        {
            "schema_version": 1,
            "report_type": "agentlab_production_pack_research_contract",
            "status": "pass" if provider_returned else "scaffold",
            "execution_mode": execution_mode,
            "source_report": source_report.name if source_report else None,
            "source_provider": source_provider,
            "source_model": source_model,
            "source_status": source_status,
            "provider_returned_research": provider_returned,
            "harness_normalized_brief": True,
            "harness_generated_domain_findings": False,
            "source_sha256": source_sha256,
            "brief_sha256": sha256(content.encode("utf-8")).hexdigest(),
            "candidate_only": True,
            "production_modified": False,
        },
        sort_keys=False,
        allow_unicode=True,
    )
    return path.name


def _base_pack_candidate_payload(
    pack_id: str,
    artifact: str,
    project: str,
    task_id: str,
    *,
    execution_mode: str,
) -> dict:
    return {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "production_pack": pack_id,
        "artifact": artifact,
        "status": "candidate",
        "execution_mode": execution_mode,
        "generated_by": "fake_provider",
        "candidate_only": True,
        "production_modified": False,
    }


def _pack_candidate_payload(
    pack_id: str,
    artifact: str,
    project: str,
    task_id: str,
    *,
    execution_mode: str,
    pack: dict | None = None,
) -> dict:
    payload = _base_pack_candidate_payload(
        pack_id,
        artifact,
        project,
        task_id,
        execution_mode=execution_mode,
    )

    if pack_id == "media_series_production":
        payload.update(_media_series_candidate_fields(artifact))
        return payload
    if pack_id == "media_generation":
        payload.update(_media_generation_candidate_fields(artifact))
        return payload
    if pack_id == "pack_synthesis_candidate":
        return _synthesis_candidate_fields(
            payload,
            artifact,
            project,
            task_id,
            execution_mode=execution_mode,
            pack=pack or {},
        )

    payload["items"] = [
        {
            "id": "candidate_content_contract",
            "status": "needs_executor_content",
            "note": "Dry-run scaffold only; a real executor must replace this with domain content.",
        }
    ]
    return payload


def _safe_pack_token(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or fallback


def _synthesized_pack_id(pack: dict, project: str, task_id: str) -> str:
    task_domain = _safe_pack_token(str(pack.get("task_domain") or ""), "")
    artifact_type = _safe_pack_token(str(pack.get("artifact_type") or ""), "")
    base = task_domain or artifact_type or _safe_pack_token(f"{project}_{task_id}", "domain")
    return f"synth_{base}"[:80].rstrip("_")


def _synthesis_candidate_fields(
    payload: dict,
    artifact: str,
    project: str,
    task_id: str,
    *,
    execution_mode: str,
    pack: dict,
) -> dict:
    pack_id = _synthesized_pack_id(pack, project, task_id)
    project_type = str(pack.get("project_type") or "unknown_project")
    task_domain = str(pack.get("task_domain") or "unknown")
    artifact_type = str(pack.get("artifact_type") or "unknown")
    route_key = str(pack.get("route_key") or "artifact_production_task")
    lifecycle_nodes = [
        "INIT_TASK",
        "CONTEXT_PROFILE",
        "CONTEXT_BUDGET",
        "CONTEXT_PACK",
        "PREPARE_PLAN",
        "SUPERVISOR_PLAN",
        "RESEARCH_OPTIONAL",
        "ARTIFACT_PRODUCTION",
        "VERIFY",
        "SELF_CHECK",
        "FINALIZE",
    ]
    memory_contract = [
        "domain_state_snapshot",
        "artifact_index",
        "generation_or_revision_ledger",
        "delivery_receipt",
    ]
    required_outputs = [
        "domain_state_snapshot.yml",
        "artifact_index.yml",
        "generation_or_revision_ledger.yml",
        "delivery_receipt.yml",
    ]
    quality_gates = [
        "domain_research_brief_reviewed",
        "resource_discovery_reviewed",
        "memory_contract_written",
        "candidate_fact_boundary_enforced",
        "delivery_receipt_written",
        "approval_before_promotion",
    ]
    resource_contract = {
        "resource_discovery_required": True,
        "allowed_sources": [
            "user_provided_files",
            "configured_local_tools",
            "registered_role_workers",
            "approved_external_research",
        ],
        "authority_boundary": "external research can inform candidate proposals but never becomes authoritative memory",
        "external_research_requires_approval": True,
        "external_research_outputs": [
            "source_notes",
            "resource_evidence_ledger",
        ],
        "external_research_may_not_write_project_memory": True,
        "evidence_to_memory_promotion_requires_review": True,
        "prefer_internal_workers": True,
        "new_provider_requires_approval": True,
    }
    promotion_policy = {
        "candidate_only": True,
        "auto_promote": False,
        "production_modified": False,
        "approval_required": "human_or_supervisor_approval",
        "candidate_facts_remain_run_local": True,
    }
    if artifact == "production_pack_proposal.yml":
        return {
            "schema_version": 1,
            "status": "candidate",
            "generated_by": "AgentLab pack_synthesis_candidate",
            "candidate_only": True,
            "production_modified": False,
            "source": {
                "project": project,
                "task_id": task_id,
                "execution_mode": execution_mode,
                "source_pack": payload.get("production_pack"),
            },
            "pack": {
                "pack_id": pack_id,
                "name": f"Synthesized {task_domain.replace('_', ' ').title()} Pack",
                "description": (
                    "Candidate production pack synthesized for an unconfigured non-code domain. "
                    "It must be reviewed and explicitly promoted before use."
                ),
                "routes": [route_key],
                "project_types": [project_type],
                "task_domains": [task_domain],
                "artifact_types": [artifact_type],
                "lifecycle_nodes": lifecycle_nodes,
                "domain_phases": [
                    "domain_requirements_review",
                    "state_contract_design",
                    "artifact_generation",
                    "quality_review",
                    "acceptance_or_rewrite",
                ],
                "required_outputs": required_outputs,
                "memory_contract": memory_contract,
                "resource_contract": resource_contract,
                "quality_gates": quality_gates,
                "promotion_policy": promotion_policy,
            },
        }
    if artifact == "domain_memory_contract.yml":
        payload.update(
            {
                "synthesized_pack_id": pack_id,
                "memory_contract": memory_contract,
                "candidate_fact_policy": "candidate facts remain run-local until explicit promotion",
                "resource_contract": resource_contract,
                "promotion_inputs": ["human_acceptance", "quality_review", "state_transition_proposal"],
                "promotion_policy": promotion_policy,
            }
        )
        return payload
    if artifact == "lifecycle_profile.yml":
        payload.update(
            {
                "synthesized_pack_id": pack_id,
                "lifecycle_nodes": lifecycle_nodes,
                "forbidden_nodes": ["CODER_IMPLEMENTATION", "ARCHIVE"],
                "approval_gate": "user_or_supervisor_approval_before_pack_promotion",
                "quality_gates": quality_gates,
                "promotion_policy": promotion_policy,
            }
        )
        return payload
    payload.update(
        {
            "synthesized_pack_id": pack_id,
            "items": [{"id": "unknown_synthesis_artifact", "status": "candidate"}],
        }
    )
    return payload


def _media_series_candidate_fields(artifact: str) -> dict:
    if artifact == "episode_plan.yml":
        return {
            "source_scope": "user_request_or_named_story_source",
            "episodes": [
                {
                    "episode_id": "ep01",
                    "status": "candidate_outline",
                    "source_range": "to_be_bound_from_story_source",
                    "deliverables": ["comic_sequence", "short_video", "poster_set"],
                    "continuity_focus": [
                        "character_visual_identity",
                        "scene_asset_reuse",
                        "shot_to_shot_temporal_order",
                    ],
                }
            ],
        }
    if artifact == "shot_list.yml":
        return {
            "shots": [
                {
                    "shot_id": "ep01_sh001",
                    "episode_id": "ep01",
                    "target_media": ["comic_panel", "short_video_clip", "poster_frame"],
                    "purpose": "establish reusable visual continuity anchors",
                    "required_assets": ["character_visual_bible", "asset_registry"],
                    "prompt_ref": "prompt_ep01_sh001",
                    "continuity_keys": ["cast_lock", "location_lock", "timeline_position"],
                }
            ],
        }
    if artifact == "character_visual_bible.yml":
        return {
            "characters": [
                {
                    "character_id": "primary_cast_from_source",
                    "status": "needs_source_extraction",
                    "locked_traits": [],
                    "consistency_rules": [
                        "extract traits from approved story source before live generation",
                        "reuse the same character_id across prompts and generated assets",
                        "record any accepted visual change in media_continuity_ledger.yml",
                    ],
                }
            ],
        }
    if artifact == "asset_registry.yml":
        return {
            "assets": [
                {
                    "asset_id": "visual_continuity_seed_ep01",
                    "type": "continuity_reference",
                    "status": "candidate_placeholder",
                    "source": "dry_run_no_media_generated",
                    "promotion_allowed": False,
                    "used_by": ["ep01_sh001"],
                }
            ],
        }
    if artifact == "prompt_pack.yml":
        return {
            "prompts": [
                {
                    "prompt_id": "prompt_ep01_sh001",
                    "target_media": ["comic_panel", "short_video_clip", "poster_frame"],
                    "source_refs": ["episode_plan.yml#ep01", "shot_list.yml#ep01_sh001"],
                    "positive_prompt": (
                        "Use approved Crown of Ash source facts, character visual bible, "
                        "and asset registry to render the same moment across media formats."
                    ),
                    "negative_prompt": "Do not introduce unapproved character traits, costumes, locations, or timeline jumps.",
                }
            ],
        }
    if artifact == "generation_ledger.yml":
        return {
            "generated_assets": [],
            "generations": [
                {
                    "generation_id": "dry_run_backend_preflight",
                    "status": "not_executed",
                    "live": False,
                    "backend": "not_called",
                    "reason": "dry_run candidate scaffold; no media artifact was generated",
                    "artifacts_written": [],
                }
            ],
        }
    if artifact == "generation_receipt.yml":
        return {
            "status": "not_required",
            "producer": {"role": "ArtifactProducer", "id": "fake-provider"},
            "backend": "not_called",
            "model": "not_called",
            "prompt_parameters": {"execution_mode": "mock_provider"},
            "reference_assets": [],
        }
    if artifact == "generated_assets_manifest.yml":
        return {"status": "not_required", "assets": []}
    if artifact == "media_continuity_ledger.yml":
        return {
            "continuity_checks": [
                {
                    "check_id": "media_series_identity_lock",
                    "status": "pending_live_assets",
                    "scope": ["character_visual_bible.yml", "asset_registry.yml", "shot_list.yml"],
                    "blocking_if_failed": True,
                }
            ],
        }
    if artifact == "media_qc_report.yml":
        return {
            "checks": [
                {
                    "check_id": "dry_run_no_fabricated_media",
                    "status": "pass",
                    "evidence": "No live backend execution occurred and no final media was promoted.",
                },
                {
                    "check_id": "live_generation_required_for_visual_quality",
                    "status": "pending",
                    "evidence": "Visual quality cannot be assessed from dry-run scaffold.",
                },
            ],
        }
    if artifact == "narrative_media_delivery_receipt.yml":
        return {
            "required_files": [
                "episode_plan.yml",
                "shot_list.yml",
                "character_visual_bible.yml",
                "asset_registry.yml",
                "prompt_pack.yml",
                "generation_ledger.yml",
                "media_continuity_ledger.yml",
                "media_qc_report.yml",
            ],
            "live_generation": False,
            "delivery_status": "candidate_scaffold_only",
            "acceptance_required_before_promotion": True,
        }
    return {
        "items": [
            {
                "id": "media_series_candidate_content",
                "status": "needs_executor_content",
            }
        ]
    }


def _media_generation_candidate_fields(artifact: str) -> dict:
    if artifact == "generation_ledger.yml":
        return {
            "generated_assets": [],
            "generations": [
                {
                    "generation_id": "dry_run_backend_preflight",
                    "status": "not_executed",
                    "live": False,
                    "backend": "not_called",
                    "artifacts_written": [],
                }
            ],
        }
    if artifact == "generation_receipt.yml":
        return {
            "status": "not_required",
            "producer": {"role": "ArtifactProducer", "id": "fake-provider"},
            "backend": "not_called",
            "model": "not_called",
            "prompt_parameters": {"execution_mode": "mock_provider"},
            "reference_assets": [],
        }
    if artifact == "generated_assets_manifest.yml":
        return {"status": "not_required", "assets": []}
    if artifact == "media_qc_report.yml":
        return {
            "checks": [
                {
                    "check_id": "dry_run_no_fabricated_media",
                    "status": "pass",
                    "evidence": "No live backend execution occurred.",
                }
            ],
        }
    if artifact in {"media_delivery_receipt.yml", "narrative_media_delivery_receipt.yml"}:
        return {
            "live_generation": False,
            "delivery_status": "candidate_scaffold_only",
            "acceptance_required_before_promotion": True,
            "required_files": ["generation_ledger.yml", "media_qc_report.yml"],
        }
    return {
        "items": [
            {
                "id": "media_generation_candidate_content",
                "status": "needs_executor_content",
            }
        ]
    }


def _write_media_backend_dry_run_outputs(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
) -> list[str]:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return []
    try:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(plan, dict):
        return []
    pack = plan.get("production_pack") if isinstance(plan.get("production_pack"), dict) else {}
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    is_media_pack = str(pack.get("pack_id") or "") in {"media_generation", "media_series_production"}
    is_media_route = str(route.get("route_key") or "") == "media_generation_task"
    if not (is_media_pack or is_media_route):
        return []

    contract_path = run_dir / "media_generation_contract.yml"
    if not contract_path.exists():
        request_path = run_dir / "user_request.md"
        if not request_path.exists():
            return []
        try:
            from agent_runtime.brain.mission_contract import build_mission_contract
            from agent_runtime.brain.renderer import render_mission_contract_outputs
        except ImportError:  # pragma: no cover - direct runtime import path
            from brain.mission_contract import build_mission_contract
            from brain.renderer import render_mission_contract_outputs

        prompt = request_path.read_text(encoding="utf-8")
        contract = build_mission_contract(
            prompt,
            project_id=project,
            task_id=task_id,
            agentlab_root=agentlab_root,
        )
        if not contract.get("media_generation_contract"):
            return []
        render_mission_contract_outputs(contract, run_dir)

    try:
        from agent_runtime.media_backend_adapter import execute_media_contract, load_media_generation_contract
    except ImportError:  # pragma: no cover - direct runtime import path
        from media_backend_adapter import execute_media_contract, load_media_generation_contract

    out_dir = run_dir / "artifacts" / "media_backend"
    execute_media_contract(
        load_media_generation_contract(contract_path),
        agentlab_root,
        out_dir,
        live=False,
    )
    for filename in (
        "role_session_receipt.yml",
        "generation_ledger.yml",
        "generation_receipt.yml",
        "generated_assets_manifest.yml",
    ):
        canonical = out_dir / filename
        if canonical.exists():
            payload = yaml.safe_load(canonical.read_text(encoding="utf-8")) or {}
            if isinstance(payload, dict):
                atomic_write_yaml(run_dir / filename, payload)
    written: list[str] = []
    for rel in (
        "artifacts/media_backend/media_backend_preflight.yml",
        "artifacts/media_backend/media_backend_payload_plan.yml",
        "artifacts/media_backend/role_session_receipt.yml",
        "artifacts/media_backend/generation_ledger.yml",
        "artifacts/media_backend/generation_receipt.yml",
        "artifacts/media_backend/generated_assets_manifest.yml",
    ):
        if (run_dir / rel).exists():
            written.append(rel)
    return written


def _run_media_capacity_probe(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run only the narrow, non-secret xAI OAuth status probe."""

    allowed = ("hermes", "auth", "status", "xai-oauth")
    if command != allowed:
        raise ValueError("media capacity probe command is not allowlisted")
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _execute_media_backend_role_outputs(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    pack_id: str,
    *,
    capacity_probe_runner=None,
) -> dict[str, Any]:
    """Execute and verify the ArtifactProducer-owned media backend receipts.

    This is called only from the pipeline's explicit execute mode. The adapter
    owns the provider invocation and hashes returned local files; text-only
    output, an undisclosed generation model, or incomplete receipts fail closed.
    """

    contract_path = run_dir / "media_generation_contract.yml"
    if not contract_path.is_file():
        return {
            "status": "blocked",
            "issues": ["missing:media_generation_contract.yml"],
            "outputs": [],
        }
    try:
        from agent_runtime.media_backend_adapter import (
            execute_media_contract,
            load_media_generation_contract,
        )
    except ImportError:  # pragma: no cover - direct runtime import path
        from media_backend_adapter import (
            execute_media_contract,
            load_media_generation_contract,
        )

    contract = load_media_generation_contract(contract_path)
    capacity_receipt_path = run_dir / "media_capacity_route_receipt.yml"
    attempt_id = f"{task_id}:ArtifactProducer:media:{uuid4().hex}"
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    capacity_receipt: dict[str, Any] = {
        "schema_version": "media-capacity-route-receipt/v1",
        "status": "pending",
        "role": "ArtifactProducer",
        "primary_route_id": "ArtifactProducer",
        "attempt_id": attempt_id,
        "observed_at": observed_at,
        "requested_modality": contract.get("modality"),
        "contract_routing_status": contract.get("routing_status"),
        "contract_selected_backend": contract.get("selected_backend"),
        "contract_fallback_chain": list(contract.get("fallback_chain") or [])
        if isinstance(contract.get("fallback_chain"), list)
        else None,
        "provider_invocation_started": False,
    }

    def block_capacity_route(
        issue: str,
        *,
        failure_class: str,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capacity_receipt.update(
            {
                "status": "blocked",
                "failure_class": failure_class,
                "provider_invocation_started": False,
            }
        )
        if decision is not None:
            capacity_receipt["capacity_decision"] = dict(decision)
            capacity_receipt["pool_id"] = decision.get("pool_id")
            capacity_receipt["route_id"] = decision.get("route_id")
        atomic_write_yaml(capacity_receipt_path, capacity_receipt)
        return {
            "status": "blocked",
            "issues": [issue],
            "outputs": ["media_capacity_route_receipt.yml"],
        }

    capacity_policy_path = agentlab_root / "config" / "model_capacity.yml"
    try:
        capacity_policy = yaml.safe_load(
            capacity_policy_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, yaml.YAMLError):
        capacity_policy = {}
    if not isinstance(capacity_policy, dict):
        capacity_policy = {}
    routes = capacity_policy.get("routes")
    primary_route = routes.get("ArtifactProducer") if isinstance(routes, dict) else None
    if not isinstance(primary_route, dict):
        return block_capacity_route(
            "media_capacity_route_missing:ArtifactProducer",
            failure_class="capacity_policy_missing",
        )

    configured_backend = str(primary_route.get("media_backend") or "")
    configured_pool = str(primary_route.get("pool") or "")
    configured_worker = str(primary_route.get("worker") or "")
    capacity_receipt.update(
        {
            "configured_primary_backend": configured_backend or None,
            "configured_primary_pool": configured_pool or None,
            "configured_primary_worker": configured_worker or None,
        }
    )
    if (
        not configured_backend
        or configured_pool != "xai_subscription_shared"
        or configured_worker != "grok"
    ):
        return block_capacity_route(
            "media_capacity_route_invalid:ArtifactProducer",
            failure_class="invalid_capacity_policy",
        )

    fallback_chain = contract.get("fallback_chain")
    if not isinstance(fallback_chain, list) or configured_backend not in {
        str(item) for item in fallback_chain
    }:
        return block_capacity_route(
            f"media_backend_not_in_contract_fallback_chain:{configured_backend}",
            failure_class="contract_route_mismatch",
        )

    contract_status = str(contract.get("routing_status") or "")
    contract_backend = str(contract.get("selected_backend") or "")
    if contract_backend and contract_backend != configured_backend:
        return block_capacity_route(
            "media_backend_capacity_route_mismatch:"
            f"{contract_backend}:{configured_backend}",
            failure_class="contract_route_mismatch",
        )
    if contract_status not in {"selected", "pending_capacity"}:
        return block_capacity_route(
            f"media_contract_not_executable:{contract_status or 'missing'}",
            failure_class="contract_not_executable",
        )
    if contract_status == "selected" and not contract_backend:
        return block_capacity_route(
            "media_contract_selected_backend_missing",
            failure_class="contract_route_mismatch",
        )

    try:
        from agent_runtime.model_capacity import ModelCapacity
    except ImportError:  # pragma: no cover - direct runtime import path
        from model_capacity import ModelCapacity

    ledger_name = str(
        ((capacity_policy.get("ledger") or {}).get("filename"))
        or "model_capacity_ledger.yml"
    )
    capacity_manager = ModelCapacity(capacity_policy, run_dir / ledger_name)

    if contract_status == "pending_capacity":
        blocker = contract.get("execution_blocker")
        pending_backend = (
            str(blocker.get("backend") or "") if isinstance(blocker, dict) else ""
        )
        if pending_backend != configured_backend:
            return block_capacity_route(
                "media_pending_backend_capacity_route_mismatch:"
                f"{pending_backend or '<missing>'}:{configured_backend}",
                failure_class="contract_route_mismatch",
            )
        try:
            safe_command = capacity_manager.safe_probe_command(configured_pool)
        except (ValueError, TypeError) as exc:
            return block_capacity_route(
                f"media_capacity_probe_policy_invalid:{type(exc).__name__}",
                failure_class="invalid_capacity_policy",
            )
        if safe_command != ("hermes", "auth", "status", "xai-oauth"):
            return block_capacity_route(
                "media_capacity_probe_not_allowlisted",
                failure_class="unsafe_capacity_probe",
            )
        try:
            probe_result = capacity_manager.probe(
                configured_pool,
                runner=capacity_probe_runner or _run_media_capacity_probe,
                attempt_id=attempt_id,
            )
        except Exception as exc:
            observation = capacity_manager.record_failure(
                "ArtifactProducer",
                message="safe capacity probe execution failed",
                attempt_id=attempt_id,
            )
            capacity_receipt["probe"] = {
                "command": list(safe_command),
                "status": "blocked",
                "failure_class": observation.get("failure_class"),
                "error_type": type(exc).__name__,
            }
            return block_capacity_route(
                f"media_capacity_probe_failed:{observation.get('failure_class') or 'unknown'}",
                failure_class=str(observation.get("failure_class") or "unknown"),
            )
        probe_observation = (
            probe_result.get("observation")
            if isinstance(probe_result.get("observation"), dict)
            else {}
        )
        probe_failure = probe_observation.get("failure_class")
        capacity_receipt["probe"] = {
            "command": list(safe_command),
            "status": "pass" if probe_failure is None else "blocked",
            "failure_class": probe_failure,
            "observation": dict(probe_observation),
        }
        if probe_failure is not None:
            return block_capacity_route(
                f"media_capacity_probe_failed:{probe_failure}",
                failure_class=str(probe_failure),
            )

    modality = str(contract.get("modality") or "").strip().lower()
    try:
        capacity_decision = capacity_manager.select_route(
            "ArtifactProducer",
            role="ArtifactProducer",
            attempt_id=attempt_id,
            required_modalities=[modality] if modality else [],
        )
    except (ValueError, TypeError) as exc:
        return block_capacity_route(
            f"media_capacity_selection_failed:{type(exc).__name__}",
            failure_class="invalid_capacity_policy",
        )
    if capacity_decision.get("status") != "selected":
        return block_capacity_route(
            "media_capacity_route_not_selected:"
            f"{capacity_decision.get('failure_class') or capacity_decision.get('capacity_status') or 'unknown'}",
            failure_class=str(
                capacity_decision.get("failure_class")
                or capacity_decision.get("capacity_status")
                or "unknown"
            ),
            decision=capacity_decision,
        )

    selected_route_id = str(capacity_decision.get("route_id") or "")
    selected_route = routes.get(selected_route_id) if isinstance(routes, dict) else None
    selected_backend = (
        str(selected_route.get("media_backend") or "")
        if isinstance(selected_route, dict)
        else ""
    )
    selected_worker = (
        str(selected_route.get("worker") or "")
        if isinstance(selected_route, dict)
        else ""
    )
    if (
        not selected_backend
        or selected_worker != "grok"
        or selected_backend not in {str(item) for item in fallback_chain}
        or (contract_backend and contract_backend != selected_backend)
    ):
        return block_capacity_route(
            f"media_selected_capacity_route_mismatch:{selected_route_id or '<missing>'}",
            failure_class="contract_route_mismatch",
            decision=capacity_decision,
        )

    effective_contract = dict(contract)
    effective_contract.update(
        {
            "selected_backend": selected_backend,
            "routing_status": "selected",
            "executable": True,
            "execution_blocker": None,
        }
    )
    atomic_write_yaml(contract_path, effective_contract)
    capacity_receipt.update(
        {
            "status": "selected",
            "route_id": selected_route_id,
            "pool_id": capacity_decision.get("pool_id"),
            "media_backend": selected_backend,
            "worker": selected_worker,
            "model_key": selected_route.get("model_key")
            if isinstance(selected_route, dict)
            else None,
            "selection_kind": capacity_decision.get("selection_kind"),
            "capacity_status": capacity_decision.get("capacity_status"),
            "provider_invocation_started": False,
        }
    )
    atomic_write_yaml(capacity_receipt_path, capacity_receipt)

    out_dir = run_dir / "artifacts" / "media_backend"
    try:
        from agent_runtime.protocols import build_role_session
    except ImportError:  # pragma: no cover - direct runtime import path
        from protocols import build_role_session
    role_session = build_role_session(
        agentlab_root,
        "ArtifactProducer",
        selected_worker,
        project=project,
        task_id=task_id,
    )
    capacity_receipt["adapter_execution_started"] = True
    atomic_write_yaml(capacity_receipt_path, capacity_receipt)
    try:
        result = execute_media_contract(
            effective_contract,
            agentlab_root,
            out_dir,
            live=True,
            role_session=role_session,
        )
    except Exception as exc:
        failure_observation = capacity_manager.record_failure(
            selected_route_id,
            message=str(exc) or f"media backend exception {type(exc).__name__}",
            attempt_id=attempt_id,
        )
        capacity_receipt.update(
            {
                "status": "blocked",
                "failure_class": failure_observation.get("failure_class"),
                "capacity_observation": failure_observation,
                "provider_result_status": "exception",
                "provider_error_type": type(exc).__name__,
            }
        )
        atomic_write_yaml(capacity_receipt_path, capacity_receipt)
        return {
            "status": "blocked",
            "issues": [f"media_backend_exception:{type(exc).__name__}"],
            "outputs": ["media_capacity_route_receipt.yml"],
        }
    issues: list[str] = []
    if result.get("status") != "completed":
        failure_message = str(
            result.get("reason") or result.get("status") or "media backend failed"
        )
        failure_observation = capacity_manager.record_failure(
            selected_route_id,
            message=failure_message,
            attempt_id=attempt_id,
        )
        capacity_receipt.update(
            {
                "status": "blocked",
                "failure_class": failure_observation.get("failure_class"),
                "capacity_observation": failure_observation,
                "provider_result_status": result.get("status"),
            }
        )
        issues.append(
            "media_backend_not_completed:"
            + failure_message
        )
    else:
        # A completed live adapter result necessarily crossed the provider
        # boundary. Blocked/preflight results do not expose that fact, so keep
        # the field false rather than overclaiming an invocation.
        capacity_receipt["provider_invocation_started"] = True
    if result.get("artifact_generation_verified") is not True:
        issues.append("media_backend_returned_no_verified_asset")

    required = {
        "role_session_receipt.yml": "complete",
        "generation_ledger.yml": "completed",
        "generation_receipt.yml": "complete",
        "generated_assets_manifest.yml": "complete",
    }
    payloads: dict[str, dict[str, Any]] = {}
    for filename, expected_status in required.items():
        path = out_dir / filename
        if not path.is_file():
            issues.append(f"missing:artifacts/media_backend/{filename}")
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            issues.append(f"invalid_yaml:artifacts/media_backend/{filename}")
            continue
        if not isinstance(payload, dict):
            issues.append(f"invalid_mapping:artifacts/media_backend/{filename}")
            continue
        payloads[filename] = payload
        if str(payload.get("status") or "") != expected_status:
            issues.append(
                f"invalid_status:artifacts/media_backend/{filename}:"
                f"{payload.get('status') or '<missing>'}"
            )

    receipt = payloads.get("generation_receipt.yml") or {}
    producer = receipt.get("producer") if isinstance(receipt.get("producer"), dict) else {}
    role_receipt = payloads.get("role_session_receipt.yml") or {}
    if producer.get("role") != "ArtifactProducer" or not producer.get("id"):
        issues.append("invalid:generation_receipt.producer")
    if producer.get("id") != role_receipt.get("role_session_id"):
        issues.append("invalid:generation_receipt.role_session_mismatch")
    if producer.get("execution_id") != role_receipt.get("execution_id"):
        issues.append("invalid:generation_receipt.execution_id_mismatch")
    if str(receipt.get("backend") or "") != selected_backend:
        issues.append("invalid:generation_receipt.backend_route_mismatch")
    if not receipt.get("model"):
        issues.append("invalid:generation_receipt.actual_model_missing")
    manifest = payloads.get("generated_assets_manifest.yml") or {}
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        issues.append("invalid:generated_assets_manifest.assets")

    if issues:
        capacity_receipt.setdefault("failure_class", "artifact_validation_failed")
        capacity_receipt["status"] = "blocked"
        capacity_receipt["validation_issues"] = list(dict.fromkeys(issues))
        atomic_write_yaml(capacity_receipt_path, capacity_receipt)
        return {
            "status": "blocked",
            "issues": list(dict.fromkeys(issues)),
            "outputs": ["media_capacity_route_receipt.yml"],
        }

    success_observation = capacity_manager.record_success(
        selected_route_id,
        attempt_id=attempt_id,
    )
    capacity_receipt.update(
        {
            "status": "complete",
            "failure_class": None,
            "capacity_observation": success_observation,
            "provider_result_status": result.get("status"),
            "artifact_generation_verified": True,
        }
    )
    atomic_write_yaml(capacity_receipt_path, capacity_receipt)

    outputs: list[str] = ["media_capacity_route_receipt.yml"]
    for filename, payload in payloads.items():
        atomic_write_yaml(run_dir / filename, payload)
        outputs.extend([f"artifacts/media_backend/{filename}", filename])
    delivery_name = (
        "narrative_media_delivery_receipt.yml"
        if pack_id == "media_series_production"
        else "media_delivery_receipt.yml"
    )
    atomic_write_yaml(
        run_dir / delivery_name,
        {
            "schema_version": "media-delivery-receipt/v1",
            "status": "candidate_ready_for_independent_review",
            "producer": dict(producer),
            "live_generation": True,
            "candidate_only": True,
            "production_modified": False,
            "generated_assets": list(assets),
            "source_receipts": [
                "role_session_receipt.yml",
                "generation_ledger.yml",
                "generation_receipt.yml",
                "generated_assets_manifest.yml",
                "media_capacity_route_receipt.yml",
            ],
            "independent_acceptance_required": True,
            "promotion_performed": False,
        },
    )
    outputs.append(delivery_name)
    return {
        "status": "complete",
        "issues": [],
        "outputs": outputs,
        "backend_status": result.get("status"),
    }


def _workflow_route_key(run_dir: Path) -> str:
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        return ""
    try:
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    route = plan.get("route", {}) if isinstance(plan, dict) else {}
    if isinstance(route, dict):
        return str(route.get("route_key") or "")
    return ""


def _write_narrative_batch_candidate_outputs(
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    execution_mode: str,
) -> list[str]:
    if _workflow_route_key(run_dir) != "narrative_batch_chapters":
        return []
    written: list[str] = []
    plan = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "route_key": "narrative_batch_chapters",
        "status": "candidate",
        "execution_mode": execution_mode,
        "chapter_range": "from_user_request",
        "candidate_only": True,
    }
    atomic_write_yaml(run_dir / "chapter_batch_plan.yml", plan)
    written.append("chapter_batch_plan.yml")

    chapters_dir = run_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    chapter_path = chapters_dir / "chapter_001.md"
    if not chapter_path.exists():
        chapter_path.write_text(
            "# Chapter 001 Candidate\n\nDry-run candidate chapter placeholder for batch contract validation.\n",
            encoding="utf-8",
        )
    written.append("chapters/chapter_001.md")

    for filename in (
        "batch_continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_batch_delivery_receipt.yml",
    ):
        atomic_write_yaml(run_dir / filename, {
            "schema_version": 1,
            "project": project,
            "task_id": task_id,
            "route_key": "narrative_batch_chapters",
            "status": "candidate",
            "execution_mode": execution_mode,
            "candidate_only": True,
            "items": [],
        })
        written.append(filename)
    return written


def _append_dry_run_cost_entry(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    node_id: str,
    agent: str | None,
    budget_mode: str | None,
    execution_mode: str,
) -> None:
    from cost_tracker import append_cost_ledgers

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "task_id": task_id,
        "node": node_id,
        "agent": agent or node_id,
        "budget_mode": budget_mode or "balanced",
        "execution_mode": execution_mode,
        "provider": "fake_provider",
        "model": "deterministic-dry-run",
        "dry_run": True,
        "usage_source": "no_llm_call",
        "exact_usage_available": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost": 0.0,
        "exact_cost_available": True,
        "pricing_confidence": "high",
        "notes": "No paid LLM API call was made; deterministic dry-run evidence only.",
    }
    append_cost_ledgers(agentlab_root / "projects" / project, run_dir, entry)


def _record_dry_run_command(run_dir: Path, node_id: str, agent: str | None) -> str:
    from execution_log import append_command_record

    return append_command_record(run_dir, {
        "node": node_id,
        "agent": agent or node_id,
        "command": f"dry-run lifecycle evidence for {node_id}",
        "cwd": str(run_dir),
        "exit_code": 0,
        "stdout": f"{node_id} completed in dry-run mode; no external process or API was invoked.\n",
        "stderr": "",
        "dry_run": True,
        "notes": "Synthetic command record used to make dry-run validation evidence explicit.",
    })


def _record_dry_run_node_evidence(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    *,
    node_id: str,
    agent: str | None,
    report_name: str | None,
    budget_mode: str | None,
    execution_mode: str,
) -> str:
    command_id = _record_dry_run_command(run_dir, node_id, agent)
    _append_dry_run_cost_entry(
        agentlab_root,
        run_dir,
        project,
        task_id,
        node_id=node_id,
        agent=agent,
        budget_mode=budget_mode,
        execution_mode=execution_mode,
    )
    if report_name:
        _write_artifact_alias(run_dir, report_name)
    return command_id


def _apply_archive_steward_if_needed(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
) -> list[str]:
    if node_id != "ARCHIVE":
        return []
    try:
        from agent_runtime.narrative_delivery import validate_narrative_delivery

        delivery = validate_narrative_delivery(run_dir)
        if not delivery.get("skipped") and not delivery.get("valid"):
            return [
                "Narrative delivery gate failed: "
                + "; ".join(
                    f"{issue.get('check')}: {issue.get('message')}"
                    for issue in delivery.get("issues", [])
                    if issue.get("severity") == "error"
                )
            ]
    except Exception as exc:
        return [f"Narrative delivery gate failed: {type(exc).__name__}: {exc}"]
    try:
        from project_artifact_steward import apply_archive_protocol

        receipt = apply_archive_protocol(agentlab_root, project, task_id)
    except Exception as exc:
        return [f"Project Artifact Steward failed: {type(exc).__name__}: {exc}"]
    return [f"archive_receipt error: {error}" for error in receipt.get("errors") or []]


def _report_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.exists() else None
    except OSError:
        return None


def _observation_report_content(
    task_id: str,
    raw_content: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    model_execution_receipt: str | None = None,
    model_execution_chain: str | None = None,
) -> str:
    """Normalize Observer output into a bounded, read-only YAML receipt."""
    expected_keys = {
        "status",
        "inputs_observed",
        "observations",
        "scientific_evidence",
        "inferences",
        "limitations",
        "uncertainties",
        "suggestions",
        "actionable_suggestions",
    }
    payloads: list[str] = []
    output_match = re.search(
        r"(?ms)^## Output\s*$\s*(.*?)(?=^## [^#]|\Z)",
        raw_content,
    )
    if output_match:
        payloads.append(output_match.group(1).strip())
    payloads.extend(
        match.strip()
        for match in re.findall(
            r"(?ms)```(?:yaml|yml)?\s*\n(.*?)```",
            raw_content,
        )
    )
    payloads.append(raw_content.strip())

    candidate: dict[str, Any] = {}
    parsed = False
    seen_payloads: set[str] = set()
    for payload in payloads:
        if not payload or payload in seen_payloads:
            continue
        seen_payloads.add(payload)
        unwrapped = re.sub(
            r"(?ms)^```(?:yaml|yml)?\s*\n(.*?)```\s*$",
            r"\1",
            payload,
        ).strip()
        try:
            loaded = yaml.safe_load(unwrapped)
        except yaml.YAMLError:
            continue
        if isinstance(loaded, dict) and expected_keys.intersection(loaded):
            candidate = loaded
            parsed = True
            break

    def _items(key: str) -> list:
        value = candidate.get(key, [])
        return value if isinstance(value, list) else []

    observations = _items("observations")
    deterministic_fixture = provider in {None, "", "fake_provider"}
    if not parsed and deterministic_fixture and raw_content.strip():
        observations = [
            {
                "summary": raw_content.strip(),
                "evidence_type": "observer_output",
            }
        ]
    limitations = _items("limitations")
    if not parsed and not deterministic_fixture:
        limitations = ["observer_output_unparseable"]
    actionable_suggestions = (
        _items("actionable_suggestions") or _items("suggestions")
    )
    receipt_path = model_execution_receipt
    candidate_status = str(candidate.get("status") or "complete").strip().lower()
    complete = (parsed and candidate_status in {"complete", "completed", "pass"}) or (
        deterministic_fixture and not parsed
    )
    report = {
        "schema_version": 1,
        "report_type": "observation_report",
        "task_id": task_id,
        "status": "complete" if complete else "blocked",
        "read_only": True,
        "candidate_only": True,
        "production_modified": False,
        "self_approved": False,
        "model_execution_receipt": receipt_path,
        "model_execution_chain": model_execution_chain,
        "inputs_observed": _items("inputs_observed"),
        "observations": observations,
        "scientific_evidence": _items("scientific_evidence"),
        "inferences": _items("inferences"),
        "limitations": limitations,
        "uncertainties": _items("uncertainties"),
        "actionable_suggestions": actionable_suggestions,
        "suggestions": actionable_suggestions,
        "runtime_provenance": {
            "provider": provider or "fake_provider",
            "model": model or "deterministic_observer_fixture",
            "model_execution_receipt_path": receipt_path,
            "model_execution_chain_path": model_execution_chain,
        },
        "safety_receipt": {
            "files_changed": [],
            "commands_run": [],
            "production_actions": [],
            "self_approved": False,
        },
    }
    return yaml.safe_dump(report, sort_keys=False, allow_unicode=True)


def _preserve_cli_native_report(
    result: object,
    report_path: Path,
    before: bytes | None,
    run_dir: Path,
    agent: str,
) -> str | None:
    """Keep a native CLI report and capture the worker's stdout separately."""
    if getattr(result, "provider", None) != "agentlab-cli-executor":
        return None
    after = _report_bytes(report_path)
    if after is None or after == before or not after.strip():
        return None
    capture_path = run_dir / f"{agent.lower()}_cli_result_capture.md"
    capture_path.write_text(str(getattr(result, "content", "") or ""), encoding="utf-8")
    return after.decode("utf-8", errors="replace")


def run_next_node(
    agentlab_root: Path, project: str, task_id: str, *,
    fake_provider: bool = False, simulate_quota_failure_at: Optional[str] = None,
    budget_mode: Optional[str] = None,
    allow_patches: bool = False,
    execution_mode: str | None = None,
) -> dict:
    """Execute exactly one lifecycle node and return.

    allow_patches: Whether to allow patch application. Controlled by execution mode.
    execution_mode: If provided, used in return dicts so direct callers see
                    correct mode. Defaults to inferring from fake_provider.

    This is a SINGLE-STEP function. It does NOT recurse.
    The caller (run_full_pipeline) handles the loop.
    """
    effective_execution_mode = execution_mode or ("mock_provider" if fake_provider else "execute")
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    state = load_state(run_dir, project, task_id)
    progress = load_progress(run_dir)
    if progress is None or "provider_status" not in progress:
        route_agents = []
        plan_path = run_dir / "workflow_plan.yml"
        if plan_path.exists():
            plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            route_agents = plan_data.get("route", {}).get("agents", [])
        progress = create_progress(run_dir, project, task_id, route_agents)

    if load_lifecycle(run_dir) is None:
        plan_path = run_dir / "workflow_plan.yml"
        workflow_plan = {}
        if plan_path.exists():
            workflow_plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        create_lifecycle(run_dir, workflow_plan)
    else:
        _ensure_lifecycle_shape(run_dir)
        _skip_stale_context_nodes(run_dir)

    nid = next_node(run_dir)
    if nid is None:
        lifecycle = load_lifecycle(run_dir)
        if lifecycle:
            all_done = all(
                lifecycle["nodes"].get(n, {}).get("status") in ("completed", "skipped")
                for n in LIFECYCLE_NODES
            )
            if all_done:
                return {
                    "status": "completed",
                    "node": None,
                    "message": "All nodes completed.",
                    "execution_mode": effective_execution_mode,
                }
        return {
            "status": "waiting",
            "node": None,
            "message": "No waiting nodes.",
            "execution_mode": effective_execution_mode,
        }

    # Skip optional nodes that are already skipped
    if nid in OPTIONAL_NODES:
        lc = load_lifecycle(run_dir)
        if lc and lc.get("nodes", {}).get(nid, {}).get("status") == "skipped":
            return {"status": "skipped", "node": nid, "message": "Already skipped."}

    # Quota failure simulation
    if simulate_quota_failure_at and nid == simulate_quota_failure_at:
        return _block_task(
            agentlab_root, run_dir, project, task_id, nid,
            agent=NODE_TO_AGENT.get(nid),
            reason="Simulated provider quota exhausted",
            stage="blocked_quota",
            user_action_required=True,
            block_type="quota_exhausted",
        )

    mark_node_started(run_dir, nid)
    state.status = "running"
    state.current_agent = NODE_TO_AGENT.get(nid)
    state.last_event = f"Running: {nid}"
    save_state(run_dir, state)

    progress["current_stage"] = NODE_TO_PROGRESS.get(nid, nid.lower())
    progress["percent_complete"] = NODE_TO_PCT.get(nid, 50)
    progress["current_agent"] = NODE_TO_AGENT.get(nid)
    progress["status"] = "running"
    save_progress(run_dir, progress)
    append_task_event(
        run_dir,
        "NODE_STARTED",
        stage=NODE_TO_PROGRESS.get(nid, nid.lower()),
        status="RUNNING",
        severity="INFO",
        message=f"{nid} started.",
        payload={"node": nid, "agent": NODE_TO_AGENT.get(nid)},
    )
    write_feedback_status(run_dir)

    # INIT and PREPARE are already done by init/prepare CLI — just mark
    if nid == "INIT_TASK":
        run_dir.mkdir(parents=True, exist_ok=True)
        if not (run_dir / "user_request.md").exists():
            (run_dir / "user_request.md").write_text(
                "# User Request\n\nDescribe the task here.\n", encoding="utf-8"
            )
        if not (run_dir / "brain_decisions.yml").exists():
            (run_dir / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
        if not (run_dir / "cost_ledger.yml").exists():
            (run_dir / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name=None,
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid == "PREPARE_PLAN":
        plan_path = run_dir / "workflow_plan.yml"
        mission_path = run_dir / "mission_contract.yml"
        request_path = run_dir / "user_request.md"
        task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
        if not plan_path.exists():
            from workflow_plan import (
                build_workflow_plan,
                write_mission_contract_artifacts,
            )
            plan = build_workflow_plan(
                agentlab_root, project, task_id,
                execution_backend="codex", budget_mode=budget_mode,
            )
            plan_data = plan.model_dump(mode="json")
            plan_path.write_text(
                yaml.safe_dump(plan_data, sort_keys=False),
                encoding="utf-8",
            )
            write_mission_contract_artifacts(
                agentlab_root,
                project,
                task_id,
                task_text,
                run_dir,
                mission_contract=plan.mission_contract,
            )
            route_agents = plan.route.agents
        else:
            plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            if "artifact_intent" not in plan_data:
                from project_artifact_steward import ensure_workflow_artifact_intent

                plan_data = ensure_workflow_artifact_intent(agentlab_root, project, task_id, plan_path)
            if not mission_path.exists():
                from workflow_plan import write_mission_contract_artifacts

                write_mission_contract_artifacts(
                    agentlab_root,
                    project,
                    task_id,
                    task_text,
                    run_dir,
                )
            route_agents = plan_data.get("route", {}).get("agents", [])
        active_nodes, pack_id = _production_pack_nodes(plan_data)
        from skill_injector import inject_skills_into_workflow_plan
        inject_skills_into_workflow_plan(
            agentlab_root,
            plan_path,
            project=project,
            task_id=task_id,
            task_text=task_text,
            record_usage=True,
        )
        lc = load_lifecycle(run_dir)
        if lc:
            optional_requirements = {
                node_id: agent_name
                for node_id, agent_name in NODE_TO_AGENT.items()
                if node_id in OPTIONAL_NODES
            }
            for node_id, agent_name in optional_requirements.items():
                node = lc.get("nodes", {}).get(node_id, {})
                skip_reason = _skip_reason_for_node(node_id, route_agents, active_nodes, pack_id)
                if skip_reason:
                    if node.get("status") != "completed":
                        node["status"] = "skipped"
                        node["skip_reason"] = skip_reason
                    continue
                if agent_name in route_agents and node.get("status") == "skipped":
                    node["status"] = "waiting"
                    node["skip_reason"] = None
            save_lifecycle(run_dir, lc)
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="workflow_plan.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    if nid in {"CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK"}:
        from context_governance import write_context_artifacts

        written = write_context_artifacts(agentlab_root, project, task_id)
        report_name = {
            "CONTEXT_PROFILE": "context_profile.yml",
            "CONTEXT_BUDGET": "context_budget.yml",
            "CONTEXT_PACK": "context_pack.yml",
        }[nid]
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name=report_name,
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid, str(run_dir / report_name))
        return {"status": "completed", "node": nid, "message": f"{nid} done.", "artifacts": written}

    if nid == "SELF_CHECK":
        result = validate_artifacts(run_dir)
        (run_dir / "self_check_report.yml").write_text(
            yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="self_check_report.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Self-check done."}

    if nid == "SYNC_OPTIONAL":
        (run_dir / "sync_report.yml").write_text(
            "# Sync Report\n\nStatus: skipped (dry-run)\n", encoding="utf-8")
        _record_dry_run_node_evidence(
            agentlab_root,
            run_dir,
            project,
            task_id,
            node_id=nid,
            agent=None,
            report_name="sync_report.yml",
            budget_mode=budget_mode,
            execution_mode=effective_execution_mode,
        )
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": "Sync skipped (dry-run)."}

    if nid == "FINALIZE":
        from task_index import build_task_record
        record = build_task_record(agentlab_root, project, run_dir)
        card = {
            "version": 1, "project": project, "task_id": task_id,
            "title": record["title"], "status": "finalizing",
        }
        atomic_write_yaml(run_dir / "task_card.yml", card)

        preliminary = validate_artifacts(run_dir)
        write_artifact_manifest(run_dir, preliminary)
        result = validate_artifacts(run_dir)
        final_status = "completed" if result.get("valid") else "blocked"
        card["status"] = final_status
        card["artifact_check"] = {
            "valid": bool(result.get("valid")),
            "pass_rate": result.get("pass_rate"),
            "issues_count": result.get("issues_count", 0),
        }
        atomic_write_yaml(run_dir / "task_card.yml", card)
        result = validate_artifacts(run_dir)
        write_artifact_manifest(run_dir, result)
        if not result.get("valid"):
            issues = [f"{i.get('file')}: {i.get('issue')}" for i in result.get("issues", [])]
            return _block_on_artifact_gate(
                agentlab_root, run_dir, project, task_id, nid, "ArtifactContract", issues,
                report_path=run_dir / "artifact_manifest.yml",
            )
        _mark_node_completed(run_dir, nid)
        state.status = "completed"
        state.last_event = f"Task completed via {effective_execution_mode} pipeline"
        save_state(run_dir, state)
        progress = load_progress(run_dir) or {}
        if progress:
            progress["status"] = "completed"
            progress["current_agent"] = None
            progress["current_stage"] = "completed"
            progress["percent_complete"] = 100
            progress["last_event"] = state.last_event
            save_progress(run_dir, progress)
        append_task_event(
            run_dir,
            "TASK_COMPLETED",
            stage="completed",
            status="COMPLETED_PASS",
            severity="COMPLETED",
            message=state.last_event,
            payload={"artifact_check": result},
        )
        try:
            from webhook_dispatcher import dispatch_event

            dispatch_event(
                agentlab_root,
                event="COMPLETED",
                project=project,
                task_id=task_id,
                stage="completed",
                severity="COMPLETED",
                summary=state.last_event,
                reason="Pipeline finalized successfully.",
            )
        except Exception:
            pass
        try:
            from post_task_learning import run_learning_review
            run_learning_review(agentlab_root, project, task_id)
        except Exception as exc:
            (run_dir / "learning_review_warning.log").write_text(
                f"Post-task learning failed: {type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
        write_feedback_status(run_dir)
        return {
            "status": "completed", "node": nid,
            "message": "Lifecycle complete.",
            "artifact_check": result, "success": True,
        }

    # Agent output nodes
    agent = NODE_TO_AGENT.get(nid)
    report_file = NODE_TO_REPORT.get(nid)
    workflow_plan_data = _workflow_plan_for_run(run_dir)
    route_data = workflow_plan_data.get("route", {})
    route_key = route_data.get("route_key") if isinstance(route_data, dict) else None
    narrative_heavy_audit = route_key == "narrative_heavy_audit"
    media_visual_route = route_key == "media_generation_task"
    if media_visual_route and nid == "VERIFY":
        report_file = "visual_verification_report.yml"

    # ── Supervisor gate ──
    if nid == "SUPERVISOR_PLAN" and not fake_provider and (run_dir / "USER_DECISION_REQUIRED.md").exists():
        return _block_task(
            agentlab_root, run_dir, project, task_id, nid,
            agent=agent,
            reason="Supervisor produced split plan — user decision required before next agent",
            stage="blocked_user_decision",
            user_action_required=True,
            block_type="user_decision",
        )

    if fake_provider and agent:
        if nid in {"VISUAL_OBSERVATION", "VISUAL_REVIEW"} or (
            media_visual_route and nid == "VERIFY"
        ):
            from agent_runtime.visual_acceptance_workflow import (
                fake_visual_stage_report,
                materialize_visual_acceptance,
                write_media_qc_report,
            )

            report = fake_visual_stage_report(run_dir, role=agent)
            report_path = run_dir / str(report_file)
            atomic_write_yaml(report_path, report)
            if nid == "VISUAL_REVIEW":
                write_media_qc_report(run_dir, report)
            acceptance = None
            if nid == "VERIFY":
                acceptance = materialize_visual_acceptance(
                    run_dir,
                    task_id=task_id,
                )
                (run_dir / "verification_report.md").write_text(
                    "# Media Visual Verification\n\n"
                    f"- status: {acceptance.get('status')}\n"
                    f"- candidate_count: {acceptance.get('candidate_count')}\n"
                    "- candidate_only: true\n"
                    "- production_modified: false\n",
                    encoding="utf-8",
                )
                if acceptance.get("status") == "blocked":
                    return _block_on_artifact_gate(
                        agentlab_root,
                        run_dir,
                        project,
                        task_id,
                        nid,
                        agent,
                        [str(issue) for issue in acceptance.get("issues", [])],
                        report_path=run_dir / "visual_acceptance_decision.yml",
                    )
            _mark_node_completed(run_dir, nid, str(report_path))
            payload = {
                "status": "completed",
                "node": nid,
                "report": str(report_path),
            }
            if acceptance is not None:
                payload["visual_acceptance"] = acceptance
            return payload
        if narrative_heavy_audit and agent in {"Reviewer", "Scribe", "Verifier"}:
            from agent_runtime.narrative_heavy_audit import (
                HEAVY_AUDIT_OUTPUTS_BY_AGENT,
                fake_narrative_heavy_audit_content,
                heavy_audit_primary_output,
                materialize_narrative_heavy_audit_content,
            )

            content = fake_narrative_heavy_audit_content(agent)
            if not materialize_narrative_heavy_audit_content(
                content,
                run_dir,
                task_id,
                agent,
            ):
                contract_path = run_dir / f"narrative_heavy_audit_{agent.lower()}_output_contract.yml"
                contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    [str(issue) for issue in contract.get("issues", [])],
                    report_path=contract_path,
                )
            primary = heavy_audit_primary_output(agent)
            report_path = run_dir / str(primary)
            command_id = _record_dry_run_node_evidence(
                agentlab_root,
                run_dir,
                project,
                task_id,
                node_id=nid,
                agent=agent,
                report_name=report_path.name,
                budget_mode=budget_mode,
                execution_mode=effective_execution_mode,
            )
            gate_issues: list[str] = []
            for name in HEAVY_AUDIT_OUTPUTS_BY_AGENT[agent]:
                path = run_dir / name
                gate_issues.extend(
                    artifact_content_issues(
                        name,
                        path.read_text(encoding="utf-8", errors="replace"),
                        run_dir,
                    )
                )
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            return {
                "status": "completed",
                "node": nid,
                "report": str(report_path),
                "command_id": command_id,
                "heavy_audit_outputs": list(HEAVY_AUDIT_OUTPUTS_BY_AGENT[agent]),
            }
        output = fake_output_for_agent(agent)
        if agent == "Observer":
            output = _observation_report_content(task_id, output)
        pack_outputs: list[str] = []
        media_backend_outputs: list[str] = []
        batch_outputs: list[str] = []
        synthesis_research_output: str | None = None
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            if agent == "Researcher":
                synthesis_research_output = _write_synthesis_domain_research_brief(
                    run_dir,
                    source_report=report_path,
                    execution_mode=effective_execution_mode,
                )
            if agent == "ArtifactProducer":
                pack_outputs = _write_pack_candidate_outputs(
                    run_dir,
                    project,
                    task_id,
                    execution_mode=effective_execution_mode,
                )
                media_backend_outputs = _write_media_backend_dry_run_outputs(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                )
            if agent == "Writer":
                batch_outputs = _write_narrative_batch_candidate_outputs(
                    run_dir,
                    project,
                    task_id,
                    execution_mode=effective_execution_mode,
                )
            command_id = _record_dry_run_node_evidence(
                agentlab_root,
                run_dir,
                project,
                task_id,
                node_id=nid,
                agent=agent,
                report_name=report_file,
                budget_mode=budget_mode,
                execution_mode=effective_execution_mode,
            )
            if report_file in {"07_validation_report.md", "08_audit_report.md", "verification_report.md"}:
                output = output.rstrip() + f"\n\nEvidence: command_id {command_id}\n"
                report_path.write_text(output, encoding="utf-8")
                _write_artifact_alias(run_dir, report_file)
            gate_issues = _apply_archive_steward_if_needed(
                agentlab_root, run_dir, project, task_id, nid
            )
            gate_issues.extend(artifact_content_issues(report_path.name, output, run_dir))
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root, run_dir, project, task_id, nid, agent, gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            result = {"status": "completed", "node": nid, "report": str(report_path)}
            if pack_outputs:
                result["pack_outputs"] = pack_outputs
            if media_backend_outputs:
                result["media_backend_outputs"] = media_backend_outputs
            if batch_outputs:
                result["batch_outputs"] = batch_outputs
            if synthesis_research_output:
                result["synthesis_research_output"] = synthesis_research_output
            return result
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done."}

    elif agent and not fake_provider:
        # ─── execute mode: call real LLM API via agent_runner ───
        from agent_runner import run_agent_model, report_path_for_agent
        from workflow_plan import build_workflow_plan

        plan = build_workflow_plan(agentlab_root, project, task_id, budget_mode=budget_mode)
        plan_route = getattr(plan, "route", None)
        narrative_heavy_audit = (
            getattr(plan_route, "route_key", route_key) == "narrative_heavy_audit"
        )
        production_pack = getattr(plan, "production_pack", {}) or {}
        pack_synthesis = (
            isinstance(production_pack, dict)
            and production_pack.get("status") == "synthesis_candidate"
            and production_pack.get("pack_id") == "pack_synthesis_candidate"
        )
        report_path = run_dir / report_file if report_file else report_path_for_agent(plan, agent)
        visual_stage = nid in {"VISUAL_OBSERVATION", "VISUAL_REVIEW"} or (
            media_visual_route and nid == "VERIFY"
        )
        visual_acceptance = None
        if agent == "Writer":
            report_path = run_dir / "writer_role_session_capture.md"
        elif narrative_heavy_audit and agent in {"Reviewer", "Scribe", "Verifier"}:
            report_path = run_dir / f"{agent.lower()}_role_session_capture.md"

        if agent == "ArtifactProducer" and media_visual_route:
            try:
                media_backend_execution = _execute_media_backend_role_outputs(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    pack_id=str(
                        production_pack.get("pack_id") or "media_generation"
                    ),
                )
            except Exception as exc:
                media_backend_execution = {
                    "status": "blocked",
                    "issues": [
                        f"media_backend_exception:{type(exc).__name__}:{exc}"
                    ],
                    "outputs": [],
                }
            report_path = run_dir / "artifact_producer_report.md"
            receipt_path = run_dir / "generation_receipt.yml"
            receipt = (
                yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
                if receipt_path.is_file()
                else {}
            )
            manifest_path = run_dir / "generated_assets_manifest.yml"
            manifest = (
                yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                if manifest_path.is_file()
                else {}
            )
            assets = manifest.get("assets") if isinstance(manifest, dict) else []
            report_content = (
                "# ArtifactProducer Media Backend Report\n\n"
                "- execution_authority: media_backend_adapter\n"
                "- generic_cli_invocation_performed: false\n"
                f"- status: {media_backend_execution.get('status')}\n"
                f"- backend: {receipt.get('backend') or 'unknown'}\n"
                f"- actual_generation_model: {receipt.get('model') or 'unknown'}\n"
                f"- producer_execution_id: {(receipt.get('producer') or {}).get('id') if isinstance(receipt.get('producer'), dict) else 'unknown'}\n"
                f"- verified_asset_count: {len(assets) if isinstance(assets, list) else 0}\n"
                "- candidate_only: true\n"
                "- production_modified: false\n"
                "- downstream_acceptance: Observer -> Reviewer -> TesterAuditor -> Verifier\n"
            )
            report_path.write_text(report_content, encoding="utf-8")
            if media_backend_execution.get("status") != "complete":
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    [
                        str(issue)
                        for issue in media_backend_execution.get("issues", [])
                    ],
                    report_path=report_path,
                )

            from cost_tracker import append_cost_ledgers, usage_entry

            append_cost_ledgers(
                agentlab_root / "projects" / project,
                run_dir,
                usage_entry(
                    project,
                    task_id,
                    agent,
                    "agentlab-media-backend",
                    str(receipt.get("model") or "unknown"),
                    "completed",
                    None,
                    None,
                    None,
                    "Media provider usage/cost was not reported by the CLI; kept unknown.",
                    agentlab_root=agentlab_root,
                    usage_source="external_cli_unreported",
                    exact_usage_available=False,
                    raw_usage={
                        "provider_reported_session_id": (
                            (receipt.get("producer") or {}).get("id")
                            if isinstance(receipt.get("producer"), dict)
                            else None
                        ),
                        "provider_reported_model_id": receipt.get("model"),
                    },
                ),
            )
            gate_issues = _apply_archive_steward_if_needed(
                agentlab_root, run_dir, project, task_id, nid
            )
            gate_issues.extend(
                artifact_content_issues(report_path.name, report_content, run_dir)
            )
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            return {
                "status": "completed",
                "node": nid,
                "report": str(report_path),
                "media_backend_execution": media_backend_execution,
                "success": True,
            }
        report_before = _report_bytes(report_path)

        try:
            result = run_agent_model(
                agentlab_root, plan, agent, report_path,
                apply_patches=(
                    agent in {"Coder", "ArtifactProducer", "Writer", "Scribe"}
                    and allow_patches
                    and not (agent == "ArtifactProducer" and pack_synthesis)
                    and not narrative_heavy_audit
                ),
                allow_cli_api_fallback=not (
                    narrative_heavy_audit
                    and agent in {"Reviewer", "Scribe", "Verifier"}
                ),
            )
        except Exception as exc:
            blocked_path = run_dir / f"blocked_{agent or nid}_exception.md"
            blocked_content = (
                f"# Pipeline Blocked by Exception\n\n"
                f"- Project: {project}\n"
                f"- Task: {task_id}\n"
                f"- Node: {nid}\n"
                f"- Agent: {agent}\n"
                f"- Exception type: {type(exc).__name__}\n"
                f"- Exception message: {exc}\n\n"
                f"## Recovery Suggestions\n\n"
                f"1. Check provider API key / quota / network.\n"
                f"2. Resume with fake provider if debugging pipeline.\n"
                f"3. Resume with another provider if provider failed.\n"
                f"4. Inspect progress.yml and lifecycle.yml.\n"
            )
            blocked_path.write_text(blocked_content, encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=f"{type(exc).__name__}: {exc}",
                stage="blocked_exception",
                report_path=blocked_path,
                user_action_required=True,
                block_type="exception",
            )

        if result.status == "blocked_user_decision":
            blocked_path = run_dir / f"blocked_{agent}.md"
            blocked_path.write_text(result.content or "", encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=result.error or "User decision required",
                stage="blocked_user_decision",
                report_path=blocked_path,
                user_action_required=True,
                block_type="user_decision",
            )

        if result.status == "fallback_handoff":
            fallback_path = run_dir / f"codex_fallback_{agent}.md"
            fallback_path.write_text(result.content or "", encoding="utf-8")
            return _block_task(
                agentlab_root, run_dir, project, task_id, nid,
                agent=agent,
                reason=result.error or "Provider unavailable — handoff required",
                stage="handoff_required",
                report_path=fallback_path,
                user_action_required=True,
                block_type="fallback_handoff",
            )

        native_report_content = _preserve_cli_native_report(
            result,
            report_path,
            report_before,
            run_dir,
            agent,
        )
        production_pack_output_contract = None
        heavy_audit_outputs: list[str] = []
        if visual_stage:
            from agent_runtime.visual_acceptance_workflow import (
                materialize_visual_acceptance,
                normalize_visual_stage_report,
                visual_stage_report_issues,
                write_media_qc_report,
            )

            raw_usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
            trusted_backend = str(raw_usage.get("cli_agent") or result.provider or "unknown")
            trusted_model = str(
                raw_usage.get("cli_model_id")
                or raw_usage.get("resolved_model_key")
                or result.model
                or "unknown"
            )
            execution_id = str(
                raw_usage.get("provider_session_id")
                or raw_usage.get("session_id")
                or raw_usage.get("command_id")
                or ""
            ) or None
            report = normalize_visual_stage_report(
                native_report_content or result.content or "",
                role=agent,
                provider=trusted_backend,
                model=trusted_model,
                execution_id=execution_id,
            )
            report_content = yaml.safe_dump(
                report,
                sort_keys=False,
                allow_unicode=True,
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")
            stage_issues = visual_stage_report_issues(report, role=agent)
            if stage_issues:
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    stage_issues,
                    report_path=report_path,
                )
            if nid == "VISUAL_REVIEW":
                write_media_qc_report(run_dir, report)
            if nid == "VERIFY":
                visual_acceptance = materialize_visual_acceptance(
                    run_dir,
                    task_id=task_id,
                )
                (run_dir / "verification_report.md").write_text(
                    "# Media Visual Verification\n\n"
                    f"- status: {visual_acceptance.get('status')}\n"
                    f"- candidate_count: {visual_acceptance.get('candidate_count')}\n"
                    f"- structured_report: {report_path.name}\n"
                    "- candidate_only: true\n"
                    "- production_modified: false\n",
                    encoding="utf-8",
                )
                if visual_acceptance.get("status") == "blocked":
                    return _block_on_artifact_gate(
                        agentlab_root,
                        run_dir,
                        project,
                        task_id,
                        nid,
                        agent,
                        [
                            str(issue)
                            for issue in visual_acceptance.get("issues", [])
                        ],
                        report_path=run_dir / "visual_acceptance_decision.yml",
                    )
        elif agent == "Writer":
            try:
                from agent_runtime.writer_output_materializer import materialize_writer_candidate_result
            except ModuleNotFoundError:  # pragma: no cover - direct script path
                from writer_output_materializer import materialize_writer_candidate_result

            if not materialize_writer_candidate_result(result, run_dir, task_id):
                contract_path = run_dir / "writer_output_contract.yml"
                contract = (
                    yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
                    if contract_path.exists()
                    else {}
                )
                issues = [str(issue) for issue in contract.get("issues", [])] or [
                    "Writer did not return the four required candidate output blocks"
                ]
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    issues,
                    report_path=contract_path,
                )
            report_path = run_dir / "fiction_draft.md"
            report_content = report_path.read_text(encoding="utf-8", errors="replace")
        elif narrative_heavy_audit and agent in {"Reviewer", "Scribe", "Verifier"}:
            from agent_runtime.narrative_heavy_audit import (
                HEAVY_AUDIT_OUTPUTS_BY_AGENT,
                heavy_audit_primary_output,
                materialize_narrative_heavy_audit_result,
            )

            if not materialize_narrative_heavy_audit_result(
                result,
                run_dir,
                task_id,
                agent,
            ):
                contract_path = run_dir / f"narrative_heavy_audit_{agent.lower()}_output_contract.yml"
                contract = (
                    yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
                    if contract_path.exists()
                    else {}
                )
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    [str(issue) for issue in contract.get("issues", [])]
                    or ["Narrative heavy-audit role did not return its required candidate blocks"],
                    report_path=contract_path,
                )
            heavy_audit_outputs = list(HEAVY_AUDIT_OUTPUTS_BY_AGENT[agent])
            report_path = run_dir / str(heavy_audit_primary_output(agent))
            report_content = report_path.read_text(encoding="utf-8", errors="replace")
        elif agent == "ArtifactProducer" and pack_synthesis:
            try:
                from agent_runtime.production_pack_output_materializer import (
                    artifact_producer_report_content,
                    materialize_production_pack_candidate_result,
                )
            except ModuleNotFoundError:  # pragma: no cover - direct script path
                from production_pack_output_materializer import (
                    artifact_producer_report_content,
                    materialize_production_pack_candidate_result,
                )

            required_outputs = tuple(
                str(item) for item in production_pack.get("required_outputs") or []
            )
            materialized = materialize_production_pack_candidate_result(
                result,
                run_dir,
                task_id,
                agentlab_root / "config" / "production_packs.yml",
                execution_mode=effective_execution_mode,
                required_outputs=required_outputs,
            )
            contract_path = run_dir / "production_pack_output_contract.yml"
            if not materialized:
                contract = (
                    yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
                    if contract_path.exists()
                    else {}
                )
                issues = [str(issue) for issue in contract.get("issues", [])] or [
                    "ArtifactProducer did not return a complete production-pack candidate"
                ]
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    issues,
                    report_path=contract_path,
                )
            production_pack_output_contract = contract_path.name
            report_path = run_dir / "artifact_producer_report.md"
            report_content = native_report_content or artifact_producer_report_content(result)
            if native_report_content is None:
                report_path.write_text(
                    report_content.rstrip() + "\n",
                    encoding="utf-8",
                )
        elif agent == "Observer":
            observer_usage = (
                result.raw_usage if isinstance(result.raw_usage, dict) else {}
            )
            report_content = _observation_report_content(
                task_id,
                native_report_content or result.content or "",
                provider=str(
                    observer_usage.get("cli_runtime_provider")
                    or observer_usage.get("cli_agent")
                    or result.provider
                    or ""
                ),
                model=str(
                    observer_usage.get("cli_model_id") or result.model or ""
                ),
                model_execution_receipt=(
                    str(observer_usage["model_execution_receipt"])
                    if observer_usage.get("model_execution_receipt")
                    else None
                ),
                model_execution_chain=(
                    str(observer_usage["model_execution_chain"])
                    if observer_usage.get("model_execution_chain")
                    else None
                ),
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")
            normalized_observation = yaml.safe_load(report_content) or {}
            if normalized_observation.get("status") != "complete":
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    [
                        "Observer output was blocked or could not be normalized "
                        "into structured evidence"
                    ],
                    report_path=report_path,
                )
        else:
            report_content = native_report_content or result.content or ""
            if native_report_content is None:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(result.content or "", encoding="utf-8")

        production_pack_verification_receipt = None
        if agent == "Verifier" and pack_synthesis:
            try:
                from agent_runtime.production_pack_output_materializer import (
                    write_production_pack_verification_receipt,
                )
            except ModuleNotFoundError:  # pragma: no cover - direct script path
                from production_pack_output_materializer import (
                    write_production_pack_verification_receipt,
                )

            receipt = write_production_pack_verification_receipt(
                result,
                run_dir,
                agentlab_root / "config" / "production_packs.yml",
                execution_mode=effective_execution_mode,
            )
            production_pack_verification_receipt = (
                "production_pack_verification_receipt.yml"
            )
            if receipt.get("status") != "pass":
                return _block_on_artifact_gate(
                    agentlab_root,
                    run_dir,
                    project,
                    task_id,
                    nid,
                    agent,
                    [str(issue) for issue in receipt.get("issues", [])],
                    report_path=run_dir / production_pack_verification_receipt,
                )

        if nid == "VALIDATION" and effective_execution_mode == "execute":
            command_result = run_validation_commands_if_present(
                agentlab_root=agentlab_root,
                run_dir=run_dir,
                workspace_root=agentlab_root,
                node=nid,
                agent=agent or "TesterAuditor",
            )
            if command_result.get("ran"):
                report_content = report_content.rstrip() + "\n" + command_result["summary_markdown"]
                report_path.write_text(report_content, encoding="utf-8")
                if not command_result.get("all_required_passed", True):
                    return _block_task(
                        agentlab_root,
                        run_dir,
                        project,
                        task_id,
                        nid,
                        agent=agent,
                        reason="Required validation command failed",
                        stage="blocked_validation_command",
                        report_path=report_path,
                        user_action_required=True,
                        block_type="validation_command_failed",
                        execution_mode=effective_execution_mode,
                    )

        # Record token usage to cost_ledger
        from cost_tracker import append_cost_ledgers, usage_entry
        raw_usage = result.raw_usage or {}
        append_cost_ledgers(
            agentlab_root / "projects" / project,
            run_dir,
            usage_entry(
                project, task_id, agent,
                result.provider, result.model, result.status,
                result.input_tokens, result.output_tokens, result.total_tokens,
                "API usage from pipeline executor.",
                agentlab_root=agentlab_root,
                usage_source=raw_usage.get("usage_source"),
                token_estimation_method=raw_usage.get("token_estimation_method"),
                exact_usage_available=raw_usage.get("exact_usage_available"),
                raw_usage=raw_usage,
            ),
        )
        gate_issues = _apply_archive_steward_if_needed(
            agentlab_root, run_dir, project, task_id, nid
        )
        synthesis_research_output = None
        if agent == "Researcher":
            synthesis_research_output = _write_synthesis_domain_research_brief(
                run_dir,
                source_report=report_path,
                execution_mode=effective_execution_mode,
                source_provider=result.provider,
                source_model=result.model,
                source_status=result.status,
            )
        gate_issues.extend(artifact_content_issues(report_path.name, report_content, run_dir))
        for name in heavy_audit_outputs[1:]:
            path = run_dir / name
            gate_issues.extend(
                artifact_content_issues(
                    name,
                    path.read_text(encoding="utf-8", errors="replace"),
                    run_dir,
                )
            )
        if gate_issues:
            return _block_on_artifact_gate(
                agentlab_root, run_dir, project, task_id, nid, agent, gate_issues,
                report_path=report_path,
            )
        _mark_node_completed(run_dir, nid, str(report_path))
        result_payload = {"status": "completed", "node": nid, "report": str(report_path), "success": True}
        if synthesis_research_output:
            result_payload["synthesis_research_output"] = synthesis_research_output
        if production_pack_output_contract:
            result_payload["production_pack_output_contract"] = production_pack_output_contract
        if production_pack_verification_receipt:
            result_payload["production_pack_verification_receipt"] = (
                production_pack_verification_receipt
            )
        if heavy_audit_outputs:
            result_payload["heavy_audit_outputs"] = heavy_audit_outputs
        if visual_acceptance is not None:
            result_payload["visual_acceptance"] = visual_acceptance
        return result_payload
    else:
        output = f"# {nid} Report\n\nDry-run output.\n"
        if report_file:
            report_path = run_dir / report_file
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            command_id = _record_dry_run_node_evidence(
                agentlab_root,
                run_dir,
                project,
                task_id,
                node_id=nid,
                agent=agent or nid,
                report_name=report_file,
                budget_mode=budget_mode,
                execution_mode=effective_execution_mode,
            )
            if report_file in {"07_validation_report.md", "08_audit_report.md", "verification_report.md"}:
                output = output.rstrip() + f"\n\nEvidence: command_id {command_id}\n"
                report_path.write_text(output, encoding="utf-8")
                _write_artifact_alias(run_dir, report_file)
            gate_issues = _apply_archive_steward_if_needed(
                agentlab_root, run_dir, project, task_id, nid
            )
            gate_issues.extend(artifact_content_issues(report_path.name, output, run_dir))
            if gate_issues:
                return _block_on_artifact_gate(
                    agentlab_root, run_dir, project, task_id, nid, agent or nid, gate_issues,
                    report_path=report_path,
                )
            _mark_node_completed(run_dir, nid, str(report_path))
            return {"status": "completed", "node": nid, "report": str(report_path), "success": True}
        _mark_node_completed(run_dir, nid)
        return {"status": "completed", "node": nid, "message": f"{nid} done.", "success": True}


def _block_on_artifact_gate(
    agentlab_root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    node_id: str,
    agent: str,
    issues: list[str],
    *,
    report_path: Path | None = None,
) -> dict:
    """Pause the pipeline when an artifact exists but fails semantic checks.

    Delegates to _block_task for unified state/progress/lifecycle sync.
    """
    reason = "; ".join(issues[:5]) or "Artifact semantic validation failed"
    if len(issues) > 5:
        reason += f"; and {len(issues) - 5} more"
    block_path = run_dir / f"blocked_{agent}_artifact_gate.md"
    lines = [
        "# Artifact Gate Blocked",
        "",
        f"- Project: {project}",
        f"- Task: {task_id}",
        f"- Node: {node_id}",
        f"- Agent: {agent}",
    ]
    if report_path and report_path != block_path:
        lines.append(f"- Evidence: {report_path}")
    lines.extend(["", "## Issues"])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend([
        "",
        "## Required Action",
        "Regenerate or repair the artifact with executable evidence before resuming the lifecycle.",
        "",
    ])
    block_path.write_text("\n".join(lines), encoding="utf-8")

    result = _block_task(
        agentlab_root, run_dir, project, task_id, node_id,
        agent=agent,
        reason=reason,
        stage="blocked_artifact_gate",
        report_path=block_path,
        user_action_required=True,
        block_type="artifact_gate",
    )
    result["artifact_gate"] = issues
    result["artifact_block_report"] = str(block_path)
    return result


def _state_signature(agentlab_root: Path, project: str, task_id: str) -> str:
    """Return a compact string representing the current lifecycle state."""
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    lc = load_lifecycle(run_dir)
    if not lc:
        return "no_lifecycle"
    sig = []
    for nid in LIFECYCLE_NODES:
        status = lc.get("nodes", {}).get(nid, {}).get("status", "?")
        sig.append(f"{nid[:4]}={status[:3]}")
    return "|".join(sig)


def run_full_pipeline(
    agentlab_root: Path, project: str, task_id: str, *,
    dry_run: bool = True, fake_provider: bool = True,
    simulate_quota_failure_at: Optional[str] = None, max_steps: int = 30,
    budget_mode: Optional[str] = None,
) -> dict:
    """Run full lifecycle pipeline with safety guards.

    Uses explicit while loop — no recursion.
    Detects loops via state signature. Detects stalls via no-progress check.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    history = []
    seen_signatures = set()
    mode = _resolve_execution_mode(dry_run, fake_provider)
    ensure_repo_manifest_for_run(agentlab_root, project, task_id)
    if mode["execution_mode"] == "execute":
        from agent_runtime.revision_governance import revision_dispatch_status

        dispatch = revision_dispatch_status(agentlab_root, project, task_id)
        if dispatch.get("blocked"):
            reason = f"Revision governance blocks execution: {dispatch.get('reason')}"
            incident_path = _write_pipeline_incident(
                run_dir,
                incident_type="revision_governance_blocked",
                reason=reason,
                node_id="PIPELINE",
                max_steps=max_steps,
            )
            blocked = _block_task(
                agentlab_root,
                run_dir,
                project,
                task_id,
                "PIPELINE",
                agent=None,
                reason=reason,
                stage="blocked_revision_governance",
                report_path=incident_path,
                user_action_required=True,
                block_type="revision_governance",
                execution_mode=mode["execution_mode"],
                mark_lifecycle=False,
            )
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": 0,
                "history": history,
                "blocked_reason": blocked.get("message"),
                "blocked_type": blocked.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
    effective_max_steps = max_steps
    if simulate_quota_failure_at:
        effective_max_steps += len([n for n in LIFECYCLE_NODES if n.startswith("CONTEXT_")])

    for step in range(effective_max_steps):
        sig = _state_signature(agentlab_root, project, task_id)
        if sig in seen_signatures:
            err = f"Lifecycle loop detected at step {step}: cycle in state"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            _write_pipeline_incident(
                run_dir, incident_type="loop_detected",
                reason=err, node_id="PIPELINE", max_steps=max_steps,
            )
            blocked = _block_task(
                agentlab_root, run_dir, project, task_id,
                "PIPELINE", agent=None, reason=err,
                stage="pipeline_error",
                report_path=run_dir / "pipeline_error.log",
                user_action_required=True,
                block_type="pipeline_error",
                execution_mode=mode["execution_mode"],
                mark_lifecycle=False,
            )
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "blocked_reason": blocked.get("message"),
                "blocked_type": blocked.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        seen_signatures.add(sig)

        # Check terminal
        if "FINALIZE=com" in sig or all(
            lc.get("nodes", {}).get(n, {}).get("status") in ("completed", "skipped")
            for n in LIFECYCLE_NODES
            if (lc := (load_lifecycle(run_dir) or {"nodes": {}}))
        ):
            artifact_result = validate_artifacts(run_dir)
            write_artifact_manifest(run_dir, artifact_result)
            if not artifact_result.get("valid"):
                # ── P0.5-1: terminal artifact invalid must go through _block_task ──
                incident_path = _write_pipeline_incident(
                    run_dir,
                    incident_type="artifact_validation_failed",
                    reason="Artifact validation failed at pipeline completion",
                    node_id="FINALIZE",
                    max_steps=max_steps,
                )
                block_result = _block_task(
                    agentlab_root, run_dir, project, task_id,
                    "FINALIZE",
                    agent="ArtifactContract",
                    reason="Artifact validation failed at pipeline completion",
                    stage="blocked_artifact_validation",
                    report_path=incident_path,
                    user_action_required=True,
                    block_type="artifact_validation",
                    execution_mode=mode["execution_mode"],
                )
                return {
                    "success": False,
                    "final_status": "paused",
                    "terminal": False,
                    "requires_user_action": True,
                    "execution_mode": mode["execution_mode"],
                    "step": step,
                    "history": history,
                    "artifact_completeness": artifact_result,
                    "blocked_reason": block_result.get("message"),
                    "blocked_type": block_result.get("block_type"),
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            state = load_state(run_dir, project, task_id)
            state.status = "completed"
            state.last_event = f"Task completed via {mode['execution_mode']} pipeline"
            save_state(run_dir, state)
            progress = load_progress(run_dir) or {}
            if progress:
                progress["status"] = "completed"
                progress["current_agent"] = None
                progress["current_stage"] = "completed"
                progress["percent_complete"] = 100
                progress["last_event"] = state.last_event
                save_progress(run_dir, progress)
            append_task_event(
                run_dir,
                "TASK_COMPLETED",
                stage="completed",
                status="COMPLETED_PASS",
                severity="COMPLETED",
                message=state.last_event,
                payload={"artifact_check": artifact_result},
            )
            try:
                from webhook_dispatcher import dispatch_event

                dispatch_event(
                    agentlab_root,
                    event="COMPLETED",
                    project=project,
                    task_id=task_id,
                    stage="completed",
                    severity="COMPLETED",
                    summary=state.last_event,
                    reason="Pipeline finalized successfully.",
                )
            except Exception:
                pass
            try:
                from post_task_learning import run_learning_review
                run_learning_review(agentlab_root, project, task_id)
            except Exception as exc:
                (run_dir / "learning_review_warning.log").write_text(
                    f"Post-task learning failed: {type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
            write_feedback_status(run_dir)
            return {
                "success": True,
                "final_status": "completed",
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "artifact_completeness": artifact_result,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        result = run_next_node(
            agentlab_root, project, task_id,
            fake_provider=mode["effective_fake_provider"],
            simulate_quota_failure_at=simulate_quota_failure_at,
            budget_mode=budget_mode,
            allow_patches=mode["allow_patches"],
            execution_mode=mode["execution_mode"],
        )
        result["execution_mode"] = mode["execution_mode"]

        history.append({
            "step": step, "node": result.get("node"),
            "status": result.get("status"),
            "message": result.get("message", ""),
        })

        if result.get("status") == "paused":
            artifact_result = validate_artifacts(run_dir)
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "artifact_completeness": artifact_result,
                "blocked_reason": result.get("message"),
                "blocked_type": result.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        if result.get("status") == "error":
            return {
                "success": False,
                "final_status": "failed",
                "terminal": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "error": result.get("message"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

        # Snapshot after, check no-progress
        sig_after = _state_signature(agentlab_root, project, task_id)
        if sig_after == sig:
            err = f"No progress at step {step}: state unchanged"
            (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
            _write_pipeline_incident(
                run_dir, incident_type="no_progress",
                reason=err, node_id="PIPELINE", max_steps=max_steps,
            )
            blocked = _block_task(
                agentlab_root, run_dir, project, task_id,
                "PIPELINE", agent=None, reason=err,
                stage="pipeline_error",
                report_path=run_dir / "pipeline_error.log",
                user_action_required=True,
                block_type="pipeline_error",
                execution_mode=mode["execution_mode"],
                mark_lifecycle=False,
            )
            return {
                "success": False,
                "final_status": "paused",
                "terminal": False,
                "requires_user_action": True,
                "execution_mode": mode["execution_mode"],
                "step": step,
                "history": history,
                "blocked_reason": blocked.get("message"),
                "blocked_type": blocked.get("block_type"),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

    err = f"Exceeded max_steps={max_steps}"
    (run_dir / "pipeline_error.log").write_text(err, encoding="utf-8")
    _write_pipeline_incident(
        run_dir, incident_type="max_steps_exceeded",
        reason=err, node_id="PIPELINE", max_steps=max_steps,
    )
    blocked = _block_task(
        agentlab_root, run_dir, project, task_id,
        "PIPELINE", agent=None, reason=err,
        stage="pipeline_error",
        report_path=run_dir / "pipeline_error.log",
        user_action_required=True,
        block_type="pipeline_error",
        execution_mode=mode["execution_mode"],
        mark_lifecycle=False,
    )
    return {
        "success": False,
        "final_status": "paused",
        "terminal": False,
        "requires_user_action": True,
        "execution_mode": mode["execution_mode"],
        "step": max_steps,
        "history": history,
        "blocked_reason": blocked.get("message"),
        "blocked_type": blocked.get("block_type"),
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def resume_pipeline(
    agentlab_root: Path, project: str, task_id: str, *,
    dry_run: bool = True, fake_provider: bool = True,
    simulate_provider_recovered: bool = False,
    simulate_quota_failure_at: Optional[str] = None,
    max_steps: int = 30,
    budget_mode: Optional[str] = None,
) -> dict:
    """Resume paused pipeline.

    Guarantees a dict return for every branch — never implicitly returns None.
    """
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    state = load_state(run_dir, project, task_id)

    if state.status == "completed":
        return {
            "success": True,
            "final_status": "completed",
            "terminal": True,
            "requires_user_action": False,
            "message": "Task already completed.",
        }

    if simulate_provider_recovered:
        rp = run_dir / "resume_plan.yml"
        if rp.exists():
            rp.unlink()

    if state.status in {"blocked", "paused", "recoverable", "failed_recoverable"}:
        return run_full_pipeline(
            agentlab_root, project, task_id,
            dry_run=dry_run, fake_provider=fake_provider,
            simulate_quota_failure_at=simulate_quota_failure_at,
            max_steps=max_steps,
            budget_mode=budget_mode,
        )

    if state.status in {"failed", "cancelled", "archived"}:
        return {
            "success": False,
            "final_status": state.status,
            "terminal": True,
            "requires_user_action": False,
            "message": f"Task is not resumable from status={state.status}.",
        }

    return {
        "success": False,
        "final_status": state.status,
        "terminal": False,
        "requires_user_action": True,
        "message": f"Task status is not recognized for resume: {state.status}",
    }


def _ensure_lifecycle_shape(run_dir: Path) -> None:
    """Add newly introduced lifecycle nodes to older lifecycle.yml files."""
    lc = load_lifecycle(run_dir)
    if not lc:
        return
    plan_path = run_dir / "workflow_plan.yml"
    plan_data = {}
    route = []
    if plan_path.exists():
        plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        route = plan_data.get("route", {}).get("agents", [])
    active_nodes, pack_id = _production_pack_nodes(plan_data)
    nodes = lc.setdefault("nodes", {})
    changed = False
    for node_id in LIFECYCLE_NODES:
        if node_id in nodes:
            continue
        skip_reason = _skip_reason_for_node(node_id, route, active_nodes, pack_id)
        nodes[node_id] = {
            "status": "skipped" if skip_reason else "waiting",
            "started_at": None,
            "completed_at": None,
            "checkpoint_id": None,
            "report_path": None,
            "error": None,
            "optional": node_id in OPTIONAL_NODES,
            "skip_reason": skip_reason,
        }
        changed = True
    if changed:
        save_lifecycle(run_dir, lc)
    if not (run_dir / "workflow_plan.yml").exists():
        prepare = nodes.get("PREPARE_PLAN", {})
        if prepare.get("status") == "completed":
            prepare["status"] = "waiting"
            prepare["completed_at"] = None
            save_lifecycle(run_dir, lc)
    if not (run_dir / "brain_decisions.yml").exists():
        (run_dir / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
    if not (run_dir / "cost_ledger.yml").exists():
        (run_dir / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")


def _skip_stale_context_nodes(run_dir: Path) -> None:
    """Skip P2-G nodes when a lifecycle has already advanced past them."""
    lc = load_lifecycle(run_dir)
    if not lc:
        return
    nodes = lc.get("nodes", {})
    downstream_started = any(
        nodes.get(node_id, {}).get("status") in {"completed", "started", "failed", "paused"}
        for node_id in LIFECYCLE_NODES
        if not node_id.startswith("CONTEXT_") and node_id != "INIT_TASK"
    )
    if not downstream_started:
        return
    changed = False
    for node_id in ("CONTEXT_PROFILE", "CONTEXT_BUDGET", "CONTEXT_PACK"):
        node = nodes.get(node_id, {})
        if node.get("status") == "waiting":
            node["status"] = "skipped"
            node["skip_reason"] = "Lifecycle had already advanced before context governance nodes were introduced"
            changed = True
    if changed:
        save_lifecycle(run_dir, lc)
