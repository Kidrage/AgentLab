"""One-call governed literary Editor runtime for an exact anonymous A/B packet."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.production.live_writer_preflight import (
    _tree_digest,
    _verified_ref,
)
from agent_runtime.narrative.quality.live_editor import (
    finalize_literary_ab_review,
    find_literary_ab_payload_in_output,
)


def _mapping(path: Path, issue: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(issue) from exc
    if not isinstance(value, dict):
        raise ValueError(issue)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_exact_preflight(
    root: Path,
    *,
    project: str,
    task_id: str,
    deterministic_audit_rebuilder: Callable[[Path, str], Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    run_dir = root / "projects" / project / "runs" / task_id
    manifest = _mapping(
        run_dir / "narrative_audit_manifest.yml",
        "literary_ab_manifest_invalid",
    )
    expected = {
        "schema_version": 1,
        "report_type": "agentlab_narrative_literary_ab_preflight",
        "status": "ready",
        "job_kind": "narrative_audit",
        "run_mode": "independent_reaudit",
        "project": project,
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
        "review_model_route": "NarrativeEditor",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("literary_ab_manifest_identity_mismatch")
    chapter_id = manifest.get("chapter_id")
    if isinstance(chapter_id, bool) or not isinstance(chapter_id, int) or chapter_id < 1:
        raise ValueError("literary_ab_manifest_chapter_invalid")
    for ref in (
        manifest.get("preflight_spec"),
        manifest.get("deterministic_audit"),
        *(manifest.get("context_sources") or []),
    ):
        _verified_ref(root, ref)
    context_path = run_dir / "narrative_audit_context.md"
    if _sha256(context_path) != manifest.get("context_sha256"):
        raise ValueError("literary_ab_context_stale")
    production_digest = _tree_digest(root / "projects" / project / "production")
    if production_digest != manifest.get("production_digest"):
        raise ValueError("literary_ab_production_stale")

    original_run_id = str(manifest.get("original_run_id") or "")
    revised_run_id = str(manifest.get("revised_run_id") or "")
    original_path = root / "projects" / project / "runs" / original_run_id / "fiction_draft.md"
    revised_path = root / "projects" / project / "runs" / revised_run_id / "fiction_draft.md"
    if (
        _sha256(original_path) != manifest.get("original_sha256")
        or _sha256(revised_path) != manifest.get("revised_sha256")
    ):
        raise ValueError("literary_ab_candidate_stale")
    audit_path = _verified_ref(root, manifest.get("deterministic_audit"))
    if deterministic_audit_rebuilder is not None:
        rebuilt = deterministic_audit_rebuilder(root, revised_run_id)
        current = _mapping(audit_path, "literary_ab_deterministic_audit_invalid")
        if not isinstance(rebuilt, Mapping) or dict(rebuilt) != current:
            raise ValueError("literary_ab_deterministic_audit_stale")

    mapping_payload = _mapping(
        run_dir / "blind_mapping.yml",
        "literary_ab_blind_mapping_invalid",
    )
    if (
        mapping_payload.get("schema_version") != 1
        or mapping_payload.get("status") != "sealed_until_judge_completed"
        or mapping_payload.get("pair_id") != manifest.get("pair_id")
    ):
        raise ValueError("literary_ab_blind_mapping_invalid")
    raw_mapping = mapping_payload.get("mapping")
    if not isinstance(raw_mapping, Mapping) or set(raw_mapping) != {"A", "B"}:
        raise ValueError("literary_ab_blind_mapping_invalid")
    mapping: dict[str, str] = {}
    for label in ("A", "B"):
        item = raw_mapping[label]
        if not isinstance(item, Mapping):
            raise ValueError("literary_ab_blind_mapping_invalid")
        digest = str(item.get("candidate_sha256") or "")
        expected_run = (
            original_run_id
            if digest == manifest.get("original_sha256")
            else revised_run_id
            if digest == manifest.get("revised_sha256")
            else ""
        )
        if not expected_run or item.get("source_run_id") != expected_run:
            raise ValueError("literary_ab_blind_mapping_invalid")
        mapping[label] = digest
    mapping_sha256 = hashlib.sha256(
        json.dumps(mapping, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if mapping_sha256 != manifest.get("blind_mapping_sha256"):
        raise ValueError("literary_ab_blind_mapping_hash_mismatch")
    revised_request = _mapping(
        root
        / "projects"
        / project
        / "runs"
        / revised_run_id
        / "narrative_v2_writer_request.yml",
        "literary_ab_revised_request_invalid",
    )
    if (
        revised_request.get("candidate_set_id") is None
        or revised_request.get("source_run_id") != original_run_id
        or revised_request.get("automatic_rewrite_number")
        != manifest.get("automatic_rewrite_number")
    ):
        raise ValueError("literary_ab_revision_lineage_mismatch")
    return manifest, mapping, revised_request


def run_literary_ab_review(
    root: Path,
    *,
    project: str,
    task_id: str,
    deterministic_audit_rebuilder: Callable[[Path, str], Mapping[str, Any]] | None = None,
    agent_runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run exactly one Qwen 3.7 Max Editor call and never apply its selection."""
    root = Path(root).resolve()
    manifest, mapping, revised_request = _load_exact_preflight(
        root,
        project=project,
        task_id=task_id,
        deterministic_audit_rebuilder=deterministic_audit_rebuilder,
    )
    run_dir = root / "projects" / project / "runs" / task_id
    from agent_runtime.workflow_plan import build_workflow_plan

    plan = build_workflow_plan(
        root,
        project,
        task_id,
        budget_mode="max-quality",
    )
    if plan.route.route_key != "narrative_heavy_audit" or "Reviewer" not in plan.route.agents:
        raise ValueError("literary_ab_workflow_route_mismatch")
    plan.execution_policy = {
        **dict(plan.execution_policy or {}),
        "external_context_approval_required": True,
    }
    plan_data = plan.model_dump(mode="json")
    atomic_write_yaml(run_dir / "workflow_plan.yml", plan_data)
    plan_sha256 = _sha256(run_dir / "workflow_plan.yml")
    production_before = _tree_digest(root / "projects" / project / "production")
    if production_before != manifest["production_digest"]:
        raise ValueError("literary_ab_production_stale")

    if agent_runner is None:
        from agent_runtime.agent_runner import run_agent_model

        agent_runner = run_agent_model
    result = agent_runner(
        root,
        plan,
        "Reviewer",
        run_dir / "reviewer_role_session_capture.md",
        apply_patches=False,
        capacity_route_override="NarrativeEditor",
    )
    atomic_write_text(run_dir / "reviewer_role_session_capture.md", str(result.content))
    if result.status != "completed":
        receipt = {
            "schema_version": 1,
            "status": "blocked",
            "reason": result.error or "literary_editor_provider_failed",
            "candidate_only": True,
            "production_modified": False,
            "provider_process_started": bool(
                (result.raw_usage or {}).get("provider_process_started", True)
            ),
            "workflow_plan_sha256": plan_sha256,
        }
        atomic_write_yaml(run_dir / "narrative_literary_ab_review_receipt.yml", receipt)
        return receipt

    payload = find_literary_ab_payload_in_output(str(result.content))
    if payload is None:
        receipt = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "literary_editor_structured_output_missing",
            "candidate_only": True,
            "production_modified": False,
            "workflow_plan_sha256": plan_sha256,
        }
        atomic_write_yaml(run_dir / "narrative_literary_ab_review_receipt.yml", receipt)
        return receipt

    production_after = _tree_digest(root / "projects" / project / "production")
    if production_after != production_before:
        raise ValueError("production_changed_during_literary_review")
    original_path = (
        root
        / "projects"
        / project
        / "runs"
        / str(manifest["original_run_id"])
        / "fiction_draft.md"
    )
    revised_path = (
        root
        / "projects"
        / project
        / "runs"
        / str(manifest["revised_run_id"])
        / "fiction_draft.md"
    )
    if (
        _sha256(original_path) != manifest["original_sha256"]
        or _sha256(revised_path) != manifest["revised_sha256"]
    ):
        raise ValueError("candidate_changed_during_literary_review")
    usage = dict(result.raw_usage or {})
    judge_receipt = {
        "schema_version": 1,
        "judge_id": "Reviewer",
        "provider": result.provider,
        "model": usage.get("cli_model_id"),
        "model_key": usage.get("cli_model_key"),
        "context_id": task_id,
        "status": result.status,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "duration_seconds": usage.get("duration_s"),
        "capacity_route": usage.get("capacity_route_id"),
        "model_execution_receipt": usage.get("model_execution_receipt"),
    }
    final = finalize_literary_ab_review(
        payload,
        chapter_id=int(manifest["chapter_id"]),
        expected_pair_id=str(manifest["pair_id"]),
        blind_mapping=mapping,
        original_sha256=str(manifest["original_sha256"]),
        revised_sha256=str(manifest["revised_sha256"]),
        automatic_rewrite_number=int(manifest["automatic_rewrite_number"]),
        judge_receipt=judge_receipt,
        production_digest_before=production_before,
        production_digest_after=production_after,
    )
    final.update(
        {
            "selection_applied": False,
            "user_acceptance_required": True,
            "workflow_plan_sha256": plan_sha256,
            "original_run_id": manifest["original_run_id"],
            "revised_run_id": manifest["revised_run_id"],
        }
    )
    atomic_write_yaml(run_dir / "narrative_literary_ab_raw.yml", payload)
    atomic_write_yaml(
        run_dir / "narrative_quality_scorecard_original.yml",
        final["original_scorecard"],
    )
    atomic_write_yaml(
        run_dir / "narrative_quality_scorecard_revised.yml",
        final["revised_scorecard"],
    )
    atomic_write_yaml(run_dir / "blind_review_receipt.yml", final["blind_receipt"])
    atomic_write_yaml(
        run_dir / "revision_selection_receipt.yml",
        {
            key: final[key]
            for key in (
                "schema_version",
                "status",
                "reason",
                "candidate_only",
                "production_modified",
                "replace_current_candidate",
                "selection_applied",
                "user_acceptance_required",
                "selected_sha256",
                "rejected_sha256",
                "automatic_rewrite_exhausted",
            )
        },
    )
    atomic_write_yaml(run_dir / "narrative_literary_ab_review_receipt.yml", final)
    revealed = _mapping(run_dir / "blind_mapping.yml", "literary_ab_blind_mapping_invalid")
    revealed["status"] = "revealed_after_judge_completed"
    revealed["judge_context_id"] = task_id
    atomic_write_yaml(run_dir / "blind_mapping.yml", revealed)
    if final["status"] == "decision_required":
        from agent_runtime.narrative.production.revision_attempts import (
            persist_insufficient_revision_uplift,
        )

        decision_path = persist_insufficient_revision_uplift(
            root=root,
            project=project,
            source_run_id=str(revised_request["source_run_id"]),
            candidate_set_id=str(revised_request["candidate_set_id"]),
            automatic_rewrite_number=int(revised_request["automatic_rewrite_number"]),
        )
        final["decision_required_path"] = str(decision_path)
        atomic_write_yaml(run_dir / "narrative_literary_ab_review_receipt.yml", final)
    return final
