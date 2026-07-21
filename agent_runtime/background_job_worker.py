"""Isolated worker for one durable AgentLab background-job attempt."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.background_job_controller import (
    job_dir,
    load_job_state,
    process_receipt_path,
    write_process_receipt,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_root(request: dict[str, Any]) -> Path:
    root = Path(request["agentlab_root"]).resolve()
    project_root = (root / "projects" / request["project"]).resolve()
    project_root.relative_to(root)
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)
    return project_root


def _attempt_dir(request: dict[str, Any]) -> Path:
    return job_dir(
        Path(request["agentlab_root"]),
        request["project"],
        request["job_id"],
    ) / "attempts" / request["attempt_id"]


def _preflight(request: dict[str, Any]) -> dict[str, Any]:
    project_root = _project_root(request)
    config = request["config"]
    issues: list[str] = []
    if request.get("candidate_only") is not True:
        issues.append("candidate_only_not_sealed")
    if request.get("production_allowed") is not False:
        issues.append("production_write_not_forbidden")
    for required in (
        project_root / "project_brain" / "project_fact_snapshot.yml",
        project_root / "project_artifact_index.yml",
    ):
        if not required.is_file():
            issues.append(f"missing_required_memory:{required.name}")

    from agent_runtime.crown_candidate_audit import production_manuscript_files
    from agent_runtime.narrative_delivery import validate_chapter_state_plan

    production_files = production_manuscript_files(project_root)
    if production_files:
        issues.append("production_manuscript_not_empty")
    expected = list(
        range(int(config["start_chapter"]), int(config["end_chapter"]) + 1)
    )
    plan_validation = validate_chapter_state_plan(
        project_root,
        str(config["chapter_state_plan"]),
        expected_chapters=expected,
    )
    if plan_validation.get("status") != "pass":
        issues.append("chapter_state_plan_invalid")

    blueprint_seal: dict[str, Any] | None = None
    knowledge_snapshot: dict[str, Any] | None = None
    if config.get("knowledge_contract_required"):
        from agent_runtime.narrative.blueprint_validation import validate_blueprint_seal

        blueprint_seal = validate_blueprint_seal(
            Path(request["agentlab_root"]),
            project=str(request["project"]),
            chapter_start=int(config["start_chapter"]),
            chapter_end=int(config["end_chapter"]),
        )
        if blueprint_seal.get("status") != "pass":
            issues.append("blueprint_seal_invalid")
        snapshot_path = project_root / "project_brain" / "knowledge_index_snapshot.yml"
        knowledge_snapshot = safe_read_yaml(snapshot_path)
        if not isinstance(knowledge_snapshot, dict):
            issues.append("missing_knowledge_index_snapshot")
        elif (
            knowledge_snapshot.get("namespace")
            != f"project.{request['project']}"
            or knowledge_snapshot.get("formal_fact_roots")
            != ["production", "project_brain"]
            or not knowledge_snapshot.get("index_snapshot")
        ):
            issues.append("knowledge_index_snapshot_invalid")

    prior_chain = None
    if int(config["start_chapter"]) > 1:
        from agent_runtime.crown_candidate_audit import build_crown_completion_batch_audit

        prior_chain = build_crown_completion_batch_audit(
            Path(request["agentlab_root"]),
            eval_id=str(config["eval_id"]),
            through_chapter=int(config["start_chapter"]) - 1,
        )
        if prior_chain.get("status") != "pass":
            issues.append("prior_candidate_chain_invalid")
    result = {
        "status": "pass" if not issues else "blocked",
        "issues": issues,
        "plan_validation": plan_validation,
        "blueprint_seal": blueprint_seal,
        "knowledge_index_snapshot": knowledge_snapshot,
        "prior_chain_status": prior_chain.get("status") if prior_chain else "not_required",
        "production_manuscript_files": production_files,
    }
    return {"outcome": "success" if not issues else "failed", "result": result}


def _capacity_from_generation(report: dict[str, Any]) -> dict[str, Any] | None:
    l2 = (report.get("layers") or {}).get("L2_real_chapter_sample") or {}
    for chapter in reversed(l2.get("chapters") or []):
        error = chapter.get("live_generation_error") or {}
        reset_at = error.get("capacity_reset_at")
        failure_class = str(
            error.get("failure_class")
            or error.get("capacity_failure_class")
            or ""
        ).lower()
        capacity_status = str(error.get("capacity_status") or "").lower()
        if reset_at and (
            "capacity" in failure_class
            or "quota" in failure_class
            or capacity_status in {"exhausted", "blocked", "depleted"}
        ):
            return {
                "capacity_reset_at": str(reset_at),
                "reason": error.get("error") or failure_class or capacity_status,
            }
    return None


def _generate_batch(request: dict[str, Any]) -> dict[str, Any]:
    from agent_runtime.narrative_eval import run_narrative_eval

    root = Path(request["agentlab_root"])
    config = request["config"]
    if config.get("narrative_adapter") != "crown":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "unsupported_narrative_generation_adapter",
            },
        }
    batch = request["batch"]
    report = run_narrative_eval(
        root,
        request["project"],
        suite=str(config["suite"]),
        mode="live",
        chapters=list(range(int(batch["start"]), int(batch["end"]) + 1)),
        timestamp=str(config["eval_id"]),
        writer_worker=str(config["writer_worker"]),
        resume_valid=True,
        stop_on_block=True,
        allow_writer_cli_fallback=False,
        chapter_state_plan=str(config["chapter_state_plan"]),
        writer_budget_mode=str(config["writer_budget"]),
        require_knowledge_contract=bool(config.get("knowledge_contract_required")),
    )
    l2 = (report.get("layers") or {}).get("L2_real_chapter_sample") or {}
    result = {
        "status": "pass" if l2.get("status") == "pass" else "blocked",
        "eval_status": report.get("status"),
        "generation_status": l2.get("status"),
        "completed_chapter_count": l2.get("completed_chapter_count", 0),
        "selected_chapter_count": l2.get("selected_chapter_count", 0),
        "acceptance_run_dir": report.get("acceptance_run_dir"),
        "production_modified": report.get("production_modified", False),
    }
    if result["status"] == "pass":
        return {"outcome": "success", "result": result}
    capacity = _capacity_from_generation(report)
    if capacity:
        result["reason"] = capacity["reason"]
        return {
            "outcome": "capacity_wait",
            "capacity_reset_at": capacity["capacity_reset_at"],
            "result": result,
        }
    result["reason"] = l2.get("reason") or "chapter_generation_blocked"
    return {"outcome": "failed_recoverable", "result": result}


def _continuity_checkpoint(request: dict[str, Any]) -> dict[str, Any]:
    """Freeze candidate and evidence identities without running a literary review."""
    from agent_runtime.narrative_eval import _safe_eval_task_id

    root = Path(request["agentlab_root"]).resolve()
    project_root = _project_root(request)
    batch = request["batch"]
    config = request["config"]
    start = int(batch["start"])
    end = int(batch["end"])
    previous_hash: str | None = None
    if start > int(config.get("start_chapter") or 1):
        previous_task = _safe_eval_task_id(start - 1, str(config["eval_id"]))
        previous_path = project_root / "runs" / previous_task / "fiction_draft.md"
        if not previous_path.is_file():
            return {
                "outcome": "failed",
                "result": {
                    "status": "blocked",
                    "reason": f"missing checkpoint predecessor chapter {start - 1}",
                },
            }
        previous_hash = _sha256(previous_path)

    chapters: list[dict[str, Any]] = []
    for chapter in range(start, end + 1):
        task_id = _safe_eval_task_id(chapter, str(config["eval_id"]))
        run_dir = project_root / "runs" / task_id
        draft = run_dir / "fiction_draft.md"
        packet_path = run_dir / "chapter_packet.yml"
        packet = safe_read_yaml(packet_path)
        contract = packet.get("knowledge_contract") if isinstance(packet, dict) else None
        if (
            not draft.is_file()
            or not packet_path.is_file()
            or not isinstance(contract, dict)
            or contract.get("status") != "pass"
            or not contract.get("evidence_version")
        ):
            return {
                "outcome": "failed",
                "result": {
                    "status": "blocked",
                    "reason": f"chapter {chapter} lacks a complete knowledge-bound candidate",
                },
            }
        draft_hash = _sha256(draft)
        chapters.append(
            {
                "chapter": chapter,
                "task_id": task_id,
                "fiction_draft_sha256": draft_hash,
                "chapter_packet_sha256": _sha256(packet_path),
                "knowledge_evidence_version": str(contract["evidence_version"]),
                "predecessor_sha256": previous_hash,
            }
        )
        previous_hash = draft_hash

    checkpoint = {
        "schema_version": 1,
        "status": "frozen",
        "project": request["project"],
        "job_id": request["job_id"],
        "candidate_only": True,
        "chapter_range": [start, end],
        "chapters": chapters,
    }
    path = job_dir(root, request["project"], request["job_id"]) / "checkpoints" / (
        f"ch{start:03d}-ch{end:03d}.yml"
    )
    atomic_write_yaml(path, checkpoint)
    return {
        "outcome": "success",
        "result": {
            "status": "pass",
            "checkpoint_path": path.relative_to(root).as_posix(),
            "checkpoint_sha256": _sha256(path),
            "chapter_count": len(chapters),
        },
    }


def _deterministic_check(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("action") == "deterministic_reaudit" and isinstance(
        request.get("audit_window"), dict
    ):
        from agent_runtime.narrative.audit.background import prepare_and_precheck_audit

        clean_attempt = re.sub(r"[^A-Za-z0-9_-]+", "_", request["attempt_id"])
        preparation = prepare_and_precheck_audit(
            request,
            task_id=f"task_narrative_deterministic_reaudit_{clean_attempt}"[:120],
        )
        precheck = preparation.get("precheck")
        output = _attempt_dir(request) / "deterministic_batch_audit.yml"
        atomic_write_yaml(
            output,
            precheck
            if isinstance(precheck, dict)
            else {
                "status": "blocked",
                "blocking_codes": ["incremental_precheck_unavailable"],
            },
        )
        status = (
            "pass"
            if isinstance(precheck, dict) and precheck.get("status") == "pass"
            else "blocked"
        )
        return {
            "outcome": "success" if status == "pass" else "failed",
            "result": {
                "status": status,
                "report_path": str(output),
                "issues": (
                    precheck.get("findings", [])
                    if isinstance(precheck, dict)
                    else ["incremental_precheck_unavailable"]
                ),
                "audit_window": dict(request["audit_window"]),
            },
        }
    from agent_runtime.crown_candidate_audit import write_crown_completion_batch_audit

    output = _attempt_dir(request) / "deterministic_batch_audit.yml"
    report = write_crown_completion_batch_audit(
        Path(request["agentlab_root"]),
        output,
        eval_id=str(request["config"]["eval_id"]),
        through_chapter=int(request["batch"]["end"]),
    )
    status = "pass" if report.get("status") == "pass" else "blocked"
    return {
        "outcome": "success" if status == "pass" else "failed",
        "result": {
            "status": status,
            "report_path": str(output),
            "issues": report.get("issues", []),
        },
    }


def _read_capacity_reset(run_dir: Path) -> str | None:
    for path in sorted(run_dir.glob("*.yml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in ("capacity_reset_at", "reset_at"):
            value = payload.get(key)
            if value:
                return str(value)
        raw = payload.get("raw_usage")
        if isinstance(raw, dict) and raw.get("capacity_reset_at"):
            return str(raw["capacity_reset_at"])
    return None


_TRANSIENT_FAILURE_CLASSES = {"network_required", "provider_error", "timeout"}


def _model_failure_classes(run_dir: Path) -> set[str]:
    classes: set[str] = set()
    for path in sorted(run_dir.glob("model_execution_chain_*.yml")):
        payload = safe_read_yaml(path, default={}) or {}
        if not isinstance(payload, dict):
            continue
        records = [payload.get("final"), *(payload.get("attempts") or [])]
        for record in records:
            if not isinstance(record, dict):
                continue
            for issue in record.get("failure_issues") or []:
                prefix, separator, value = str(issue).partition(":")
                if separator and prefix == "failure_class" and value:
                    classes.add(value)
    return classes


def _transient_pipeline_failure(
    pipeline: dict[str, Any], run_dir: Path
) -> str | None:
    classes = _model_failure_classes(run_dir)
    reason = " ".join(
        str(pipeline.get(key) or "") for key in ("blocked_reason", "error")
    ).lower()
    classes.update(
        failure_class
        for failure_class in _TRANSIENT_FAILURE_CLASSES
        if failure_class in reason
    )
    return next(
        (
            failure_class
            for failure_class in sorted(classes)
            if failure_class in _TRANSIENT_FAILURE_CLASSES
        ),
        None,
    )


def _retry_timestamp(seconds: int) -> str:
    now = datetime.fromisoformat(_utc_now().replace("Z", "+00:00"))
    return (now + timedelta(seconds=max(1, seconds))).isoformat()


def _validate_audit_knowledge_contracts(request: dict[str, Any]) -> dict[str, Any]:
    """Prove audit inputs still match the evidence packets used by Writer."""
    config = request.get("config") or {}
    audit_window = request.get("audit_window")
    batch = request["batch"]
    chapters = (
        [int(item) for item in audit_window.get("audit_chapters") or []]
        if isinstance(audit_window, dict)
        else list(range(int(batch["start"]), int(batch["end"]) + 1))
    )
    if not config.get("knowledge_contract_required"):
        return {
            "schema_version": 1,
            "status": "not_required",
            "audit_chapters": chapters,
            "chapters": [],
            "issues": [],
        }

    from agent_runtime.narrative.knowledge_contract import REQUIRED_EVIDENCE_GROUPS
    from agent_runtime.narrative_eval import _safe_eval_task_id

    project_root = _project_root(request)
    project_namespace = f"project.{request['project']}"
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for chapter in chapters:
        task_id = _safe_eval_task_id(chapter, str(config["eval_id"]))
        packet_path = project_root / "runs" / task_id / "chapter_packet.yml"
        packet = safe_read_yaml(packet_path, default={}) or {}
        contract = packet.get("knowledge_contract") if isinstance(packet, dict) else None
        if not isinstance(contract, dict) or contract.get("status") != "pass":
            issues.append(f"chapter_{chapter}:missing_knowledge_contract")
            continue
        if str(contract.get("namespace") or "") != project_namespace:
            issues.append(f"chapter_{chapter}:namespace_mismatch")
        evidence_groups = contract.get("evidence_groups")
        if not isinstance(evidence_groups, dict):
            issues.append(f"chapter_{chapter}:missing_evidence_groups")
            evidence_groups = {}
        for group in REQUIRED_EVIDENCE_GROUPS:
            if not isinstance(evidence_groups.get(group), list) or not evidence_groups[group]:
                issues.append(f"chapter_{chapter}:missing_group:{group}")

        expected_hashes = contract.get("source_hashes")
        if not isinstance(expected_hashes, dict) or not expected_hashes:
            issues.append(f"chapter_{chapter}:missing_source_hashes")
            expected_hashes = {}
        current_hashes: dict[str, str] = {}
        for relative, expected_hash in sorted(expected_hashes.items()):
            pure = PurePosixPath(str(relative))
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                issues.append(f"chapter_{chapter}:unsafe_source:{relative}")
                continue
            source = (project_root / Path(*pure.parts)).resolve()
            if project_root not in source.parents or not source.is_file():
                issues.append(f"chapter_{chapter}:missing_source:{relative}")
                continue
            current_hash = _sha256(source)
            current_hashes[pure.as_posix()] = current_hash
            if current_hash != str(expected_hash):
                issues.append(f"chapter_{chapter}:source_hash_drift:{relative}")

        version_payload = json.dumps(
            {
                "index_snapshot": contract.get("index_snapshot"),
                "source_hashes": expected_hashes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected_version = hashlib.sha256(version_payload.encode("utf-8")).hexdigest()
        if str(contract.get("evidence_version") or "") != expected_version:
            issues.append(f"chapter_{chapter}:evidence_version_mismatch")
        records.append(
            {
                "chapter": chapter,
                "task_id": task_id,
                "chapter_packet_sha256": _sha256(packet_path),
                "knowledge_evidence_version": contract.get("evidence_version"),
                "source_hashes": current_hashes,
            }
        )
    return {
        "schema_version": 1,
        "status": "pass" if not issues else "blocked",
        "audit_chapters": chapters,
        "chapters": records,
        "issues": issues,
    }


def _heavy_audit(request: dict[str, Any]) -> dict[str, Any]:
    config = request["config"]
    if config.get("narrative_adapter") != "crown":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "unsupported_narrative_audit_adapter",
            },
        }
    knowledge_validation = _validate_audit_knowledge_contracts(request)
    if knowledge_validation["status"] == "blocked":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "knowledge_contract_drift",
                "knowledge_contract_validation": knowledge_validation,
            },
        }

    from agent_runtime.narrative.audit.gate import evaluate_narrative_seal
    from agent_runtime.narrative.audit.integrity import verify_audit_source_integrity
    from agent_runtime.narrative.audit.background import (
        prepare_and_precheck_audit,
        run_tiered_followup,
    )

    root = Path(request["agentlab_root"])
    batch = request["batch"]
    clean_attempt = re.sub(r"[^A-Za-z0-9_-]+", "_", request["attempt_id"])
    task_id = (
        f"task_narrative_heavy_audit_ch{int(batch['start']):03d}_"
        f"ch{int(batch['end']):03d}_{clean_attempt}"
    )[:85]
    preparation = prepare_and_precheck_audit(request, task_id=task_id)
    prepared = preparation["prepared"]
    if prepared.get("status") != "ready":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "heavy_audit_prepare_blocked",
                "issues": prepared.get("issues", []),
            },
        }
    precheck = preparation.get("precheck")
    if not isinstance(precheck, dict) or precheck.get("status") != "pass":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "deterministic_precheck_blocked",
                "blocking_codes": (
                    precheck.get("blocking_codes", [])
                    if isinstance(precheck, dict)
                    else ["missing_deterministic_precheck"]
                ),
                "deterministic_precheck": precheck,
            },
        }
    execution_plan = request.get("narrative_execution_plan")
    chapter_plans = (
        execution_plan.get("chapters")
        if isinstance(execution_plan, dict)
        else None
    )
    from agent_runtime.narrative.audit.runtime import run_single_judge_pipeline

    pipeline = run_single_judge_pipeline(
        root,
        project=request["project"],
        task_id=task_id,
        budget_mode=(
            "max-quality"
            if any(
                isinstance(item, dict) and int(item.get("judge_count") or 1) > 1
                for item in (chapter_plans or [])
            )
            else "balanced"
        ),
    )
    run_dir = root / "projects" / request["project"] / "runs" / task_id
    if not pipeline.get("success"):
        reset_at = _read_capacity_reset(run_dir)
        result = {
            "status": "blocked",
            "reason": pipeline.get("blocked_reason") or "heavy_audit_pipeline_failed",
            "task_id": task_id,
            "run_dir": str(run_dir),
        }
        if reset_at:
            return {
                "outcome": "capacity_wait",
                "capacity_reset_at": reset_at,
                "result": result,
            }
        transient_failure = _transient_pipeline_failure(pipeline, run_dir)
        if transient_failure:
            retry_seconds = int(config.get("transient_retry_seconds") or 900)
            result["reason"] = transient_failure
            result["provider_failure_reason"] = pipeline.get("blocked_reason")
            return {
                "outcome": "retry_wait",
                "retry_at": _retry_timestamp(retry_seconds),
                "result": result,
            }
        return {"outcome": "failed_recoverable", "result": result}

    continuity_path = run_dir / "continuity_failure_report.yml"
    continuity = safe_read_yaml(continuity_path, default={}) or {}
    fiction_path = run_dir / "fiction_review.yml"
    fiction = safe_read_yaml(fiction_path, default=None)
    quality_path = run_dir / "narrative_quality_scorecard.yml"
    quality = safe_read_yaml(quality_path, default=None) if quality_path.is_file() else None
    audit_source_manifest_path = Path(str(prepared["manifest_path"]))
    manifest = safe_read_yaml(audit_source_manifest_path, default={}) or {}
    integrity = verify_audit_source_integrity(
        manifest if isinstance(manifest, dict) else {},
        project_root=root / "projects" / request["project"],
    )
    candidate_sha256 = integrity.get("candidate_sha256")
    fiction_evidence = dict(fiction) if isinstance(fiction, dict) else None
    continuity_evidence = dict(continuity) if isinstance(continuity, dict) else None
    quality_evidence = dict(quality) if isinstance(quality, dict) else None
    for evidence in (fiction_evidence, continuity_evidence, quality_evidence):
        if evidence is not None and candidate_sha256:
            evidence["candidate_sha256"] = candidate_sha256
    tiered_audit = run_tiered_followup(
        request,
        primary_task_id=task_id,
        primary_pipeline=pipeline,
    )
    if tiered_audit.get("status") == "execution_failed":
        return {
            "outcome": "failed_recoverable",
            "result": {
                "status": "blocked",
                "reason": tiered_audit.get("reason"),
                "tiered_audit": tiered_audit,
            },
        }
    prior_audit = (request.get("prior_results") or {}).get("heavy_audit") or {}
    independent_reaudit = None
    if request.get("require_independent_reaudit"):
        independent_reaudit = {
            "schema_version": 1,
            "status": "pass",
            "independent_context": True,
            "audit_task_id": task_id,
            "source_audit_task_id": prior_audit.get("task_id"),
            "candidate_sha256": candidate_sha256,
            "audit_source_manifest_path": str(audit_source_manifest_path),
            "audit_source_manifest_sha256": _sha256(audit_source_manifest_path),
            "run_dir": str(run_dir),
        }
    configured_audits = tuple(
        str(item)
        for item in config.get(
            "required_audits",
            ["fiction_review", "continuity_failure_report"],
        )
    )
    audit_window = request.get("audit_window")
    required_quality_chapters = (
        tuple(int(item) for item in audit_window.get("audit_chapters") or [])
        if isinstance(audit_window, dict)
        else tuple(range(int(batch["start"]), int(batch["end"]) + 1))
    )
    if "narrative_quality_scorecard" not in configured_audits:
        required_quality_chapters = ()
    decision = evaluate_narrative_seal(
        fiction_review=fiction_evidence,
        continuity_failure_report=continuity_evidence,
        narrative_quality_scorecard=quality_evidence,
        candidate_sha256=str(candidate_sha256) if candidate_sha256 else None,
        audit_source_integrity=integrity,
        required_audits=configured_audits,
        require_independent_reaudit=bool(request.get("require_independent_reaudit")),
        independent_reaudit=independent_reaudit,
        tiered_audit=tiered_audit,
        required_quality_chapters=required_quality_chapters,
    )
    proposal_path = run_dir / "revision_or_rewrite_proposal.yml"
    return {
        "outcome": "success",
        "result": {
            "status": "pass",
            "task_id": task_id,
            "run_dir": str(run_dir),
            "requires_rewrite": decision.requires_revision,
            "seal_decision": decision.to_dict(),
            "candidate_sha256": candidate_sha256,
            "audit_source_manifest_path": str(audit_source_manifest_path),
            "audit_source_manifest_sha256": _sha256(audit_source_manifest_path),
            "audit_source_integrity": integrity,
            "fiction_review": fiction_evidence,
            "continuity_failure_report_data": continuity_evidence,
            "narrative_quality_scorecard": quality_evidence,
            "independent_reaudit": independent_reaudit,
            "tiered_audit": tiered_audit,
            "audit_chapters": knowledge_validation["audit_chapters"],
            "knowledge_contract_validation": knowledge_validation,
            "knowledge_evidence_versions": {
                str(item["chapter"]): item["knowledge_evidence_version"]
                for item in knowledge_validation["chapters"]
            },
            "fiction_review_path": str(fiction_path),
            "continuity_failure_report": str(continuity_path),
            "rewrite_proposal": str(proposal_path) if proposal_path.is_file() else None,
            "rewrite_proposal_sha256": (
                _sha256(proposal_path) if proposal_path.is_file() else None
            ),
        },
    }


def _revision_support(request: dict[str, Any], *, role: str) -> dict[str, Any]:
    """Run one post-finding role so retries never repeat successful audit nodes."""
    from agent_runtime.narrative.audit.runtime import run_revision_support_role

    heavy = (request.get("prior_results") or {}).get("heavy_audit") or {}
    task_id = str(heavy.get("task_id") or "")
    run_dir = Path(str(heavy.get("run_dir") or ""))
    if not task_id or not run_dir.is_dir():
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "missing_heavy_audit_run_for_revision_support",
            },
        }
    execution = run_revision_support_role(
        Path(request["agentlab_root"]),
        project=request["project"],
        task_id=task_id,
        role=role,
        budget_mode="balanced",
    )
    if not execution.get("success"):
        transient = _transient_pipeline_failure(
            {"blocked_reason": execution.get("blocked_reason")},
            run_dir,
        )
        result = {
            "status": "blocked",
            "reason": transient or execution.get("blocked_reason"),
            "task_id": task_id,
            "run_dir": str(run_dir),
        }
        if transient:
            return {
                "outcome": "retry_wait",
                "retry_at": _retry_timestamp(
                    int(request["config"].get("transient_retry_seconds") or 900)
                ),
                "result": result,
            }
        return {"outcome": "failed_recoverable", "result": result}
    output_name = (
        "state_transition_proposal.yml"
        if role == "Scribe"
        else "revision_or_rewrite_proposal.yml"
    )
    output_path = run_dir / output_name
    return {
        "outcome": "success",
        "result": {
            "status": "pass",
            "role": role,
            "task_id": task_id,
            "run_dir": str(run_dir),
            "output_path": str(output_path),
            "output_sha256": _sha256(output_path),
            "role_receipt": execution.get("role_receipt"),
        },
    }


def _rewrite_handoff(request: dict[str, Any]) -> dict[str, Any]:
    """Execute the scene-level revision adapter without reclassifying prose."""
    from agent_runtime.narrative.quality.background import run_background_revision

    revision_request = {
        **request,
        "job_kind": "narrative_revision",
        "run_mode": "targeted_rewrite",
    }
    result = run_background_revision(revision_request)
    return {
        "outcome": "success" if result.get("status") == "pass" else "failed",
        "result": dict(result),
    }


def _continuous_audit_manifest(
    request: dict[str, Any],
    chapter_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind final candidates to the one heavy review that covered the full window."""
    config = request.get("config") or {}
    start = int(config.get("start_chapter") or 0)
    end = int(config.get("end_chapter") or 0)
    expected = list(range(start, end + 1))
    heavy = (request.get("prior_results") or {}).get("heavy_audit") or {}
    issues: list[str] = []
    if [int(item.get("chapter") or 0) for item in chapter_records] != expected:
        issues.append("candidate_records_not_exact_chapter_range")
    if [int(item) for item in heavy.get("audit_chapters") or []] != expected:
        issues.append("heavy_audit_did_not_cover_exact_chapter_range")
    decision = heavy.get("seal_decision") or {}
    if decision.get("status") != "pass" or decision.get("allow_seal") is not True:
        issues.append("heavy_audit_seal_not_passed")
    if (heavy.get("tiered_audit") or {}).get("status") != "pass":
        issues.append("tiered_audit_not_passed")
    knowledge = heavy.get("knowledge_contract_validation") or {}
    knowledge_records = knowledge.get("chapters") or []
    if config.get("knowledge_contract_required"):
        if knowledge.get("status") != "pass":
            issues.append("knowledge_contract_validation_not_passed")
        if [int(item.get("chapter") or 0) for item in knowledge_records] != expected:
            issues.append("knowledge_contract_validation_not_exact_chapter_range")
    audit_source_integrity: dict[str, Any] | None = None
    audit_manifest_path = Path(str(heavy.get("audit_source_manifest_path") or ""))
    root = Path(str(request.get("agentlab_root") or "")).resolve()
    project_root = (root / "projects" / str(request.get("project") or "")).resolve()
    try:
        resolved_manifest = audit_manifest_path.resolve()
        resolved_manifest.relative_to(project_root)
    except (OSError, ValueError):
        resolved_manifest = audit_manifest_path
        issues.append("heavy_audit_source_manifest_unsafe")
    if not resolved_manifest.is_file():
        issues.append("heavy_audit_source_manifest_missing")
    elif _sha256(resolved_manifest) != str(
        heavy.get("audit_source_manifest_sha256") or ""
    ):
        issues.append("heavy_audit_source_manifest_hash_drift")
    else:
        from agent_runtime.narrative.audit.integrity import verify_audit_source_integrity

        audit_manifest = safe_read_yaml(resolved_manifest, default={}) or {}
        if not isinstance(audit_manifest, dict):
            audit_manifest = {}
        audit_source_integrity = verify_audit_source_integrity(
            audit_manifest,
            project_root=project_root,
        )
        if audit_source_integrity.get("status") != "pass":
            issues.append("heavy_audit_source_integrity_drift")
        if not heavy.get("candidate_sha256") or heavy.get("candidate_sha256") != (
            audit_source_integrity.get("candidate_sha256")
        ):
            issues.append("heavy_audit_candidate_snapshot_mismatch")
        audited_drafts: dict[int, tuple[str, str]] = {}
        for source in audit_manifest.get("sources") or []:
            if not isinstance(source, dict):
                continue
            files = source.get("files")
            draft = files.get("fiction_draft.md") if isinstance(files, dict) else None
            if not isinstance(draft, dict):
                continue
            audited_drafts[int(source.get("chapter") or 0)] = (
                str(draft.get("path") or ""),
                str(draft.get("sha256") or ""),
            )
        for record in chapter_records:
            chapter = int(record.get("chapter") or 0)
            audited_path, audited_hash = audited_drafts.get(chapter, ("", ""))
            current_project_path = str(record.get("path") or "")
            project_prefix = f"projects/{request.get('project')}/"
            if current_project_path.startswith(project_prefix):
                current_project_path = current_project_path[len(project_prefix) :]
            if (
                audited_path != current_project_path
                or audited_hash != str(record.get("sha256") or "")
            ):
                issues.append(f"audited_candidate_binding_mismatch:{chapter}")
    return {
        "schema_version": 1,
        "status": "pass" if not issues else "blocked",
        "project": request.get("project"),
        "job_id": request.get("job_id"),
        "candidate_only": True,
        "continuous_review": True,
        "chapter_range": [start, end],
        "heavy_audit_task_id": heavy.get("task_id"),
        "heavy_audit_run_dir": heavy.get("run_dir"),
        "candidate_sha256": heavy.get("candidate_sha256"),
        "audit_source_manifest": str(resolved_manifest),
        "audit_source_manifest_sha256": heavy.get("audit_source_manifest_sha256"),
        "audit_source_integrity": audit_source_integrity,
        "knowledge_evidence_versions": {
            str(item["chapter"]): item.get("knowledge_evidence_version")
            for item in knowledge_records
            if isinstance(item, dict) and item.get("chapter") is not None
        },
        "chapters": chapter_records,
        "issues": issues,
    }


def _candidate_package(request: dict[str, Any]) -> dict[str, Any]:
    from agent_runtime.crown_candidate_audit import write_crown_completion_batch_audit
    from agent_runtime.crown_candidate_audit import production_manuscript_files
    from agent_runtime.narrative_delivery import validate_narrative_delivery
    from agent_runtime.narrative_eval import _safe_eval_task_id
    from agent_runtime.narrative_heavy_audit import validate_revision_draft_binding

    root = Path(request["agentlab_root"])
    project_root = _project_root(request)
    config = request["config"]
    attempt_dir = _attempt_dir(request)
    final_audit_path = attempt_dir / "final_deterministic_audit.yml"
    audit = write_crown_completion_batch_audit(
        root,
        final_audit_path,
        eval_id=str(config["eval_id"]),
        through_chapter=int(config["end_chapter"]),
    )
    issues: list[str] = []
    if audit.get("status") != "pass":
        issues.append("final_deterministic_audit_failed")
    if production_manuscript_files(project_root):
        issues.append("production_manuscript_not_empty")

    chapter_records: list[dict[str, Any]] = []
    chapter_texts: list[str] = []
    try:
        from agent_runtime.narrative.quality.selection import (
            load_selected_revision_records,
        )

        revision_bindings = load_selected_revision_records(request)
    except ValueError as exc:
        return {
            "outcome": "failed",
            "result": {"status": "blocked", "issues": [str(exc)]},
        }
    for chapter in range(
        int(config["start_chapter"]), int(config["end_chapter"]) + 1
    ):
        task_id = _safe_eval_task_id(chapter, str(config["eval_id"]))
        run_dir = project_root / "runs" / task_id
        validation = validate_narrative_delivery(run_dir)
        revision_binding = revision_bindings.get(chapter)
        draft_task_id = (
            str(revision_binding["task_id"])
            if revision_binding is not None
            else task_id
        )
        draft_run = project_root / "runs" / draft_task_id
        draft = draft_run / "fiction_draft.md"
        if draft_task_id != task_id:
            binding = validate_revision_draft_binding(
                project_root,
                chapter=chapter,
                source_task_id=task_id,
                revision_task_id=draft_task_id,
                expected_binding=revision_binding,
            )
            if binding.get("status") != "pass":
                issues.extend(
                    f"invalid_revision_candidate:{chapter}:{item}"
                    for item in binding.get("issues") or []
                )
                continue
        if not validation.get("valid") or not draft.is_file():
            issues.append(f"invalid_candidate_chapter:{chapter}")
            continue
        chapter_records.append(
            {
                "chapter": chapter,
                "task_id": draft_task_id,
                "source_task_id": task_id,
                "source": str(draft),
                "path": draft.relative_to(root).as_posix(),
                "sha256": _sha256(draft),
                "byte_count": draft.stat().st_size,
            }
        )
        chapter_texts.append(
            f"<!-- AGENTLAB_CHAPTER_BOUNDARY chapter={chapter} "
            f"sha256={chapter_records[-1]['sha256']} -->\n"
            + draft.read_text(encoding="utf-8").rstrip()
            + "\n"
        )
    if issues:
        return {
            "outcome": "failed",
            "result": {"status": "blocked", "issues": issues},
        }

    rag_delivery = bool(config.get("knowledge_contract_required"))
    continuous_audit = (
        _continuous_audit_manifest(request, chapter_records) if rag_delivery else None
    )
    if continuous_audit is not None and continuous_audit["status"] != "pass":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "issues": continuous_audit["issues"],
                "continuous_audit": continuous_audit,
            },
        }

    artifacts = job_dir(root, request["project"], request["job_id"]) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    continuous_audit_path = artifacts / "continuous_audit_manifest.yml"
    if continuous_audit is not None:
        atomic_write_yaml(continuous_audit_path, continuous_audit)
    package = artifacts / (
        f"Crown_of_Ash_Chapter_{int(config['start_chapter']):03d}-"
        f"{int(config['end_chapter']):03d}_CANDIDATE.md"
    )
    package.write_text(
        "# Crown of Ash - Candidate Manuscript\n\n"
        "> Candidate-only package. Not production and not promoted canon.\n\n"
        + "\n".join(chapter_texts),
        encoding="utf-8",
    )
    manifest = artifacts / "candidate_package_manifest.yml"
    delivery_fields: dict[str, Any] = {}
    if rag_delivery:
        from agent_runtime.narrative.assembly import assemble_candidate_chapters

        omnibus = artifacts / (
            f"Crown_of_Ash_Ch{int(config['start_chapter']):02d}-"
            f"Ch{int(config['end_chapter']):02d}_合订本.txt"
        )
        delivery_manifest = artifacts / "omnibus_delivery_manifest.yml"
        assembly = assemble_candidate_chapters(
            root,
            project=request["project"],
            audit_manifest=continuous_audit_path,
            output_path=omnibus,
            delivery_manifest=delivery_manifest,
        )
        delivery_fields = {
            "continuous_audit_manifest": str(continuous_audit_path),
            "omnibus": str(omnibus),
            "omnibus_sha256": assembly["sha256"],
            "omnibus_delivery_manifest": str(delivery_manifest),
        }
    atomic_write_yaml(
        manifest,
        {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "production_modified": False,
            "chapter_count": len(chapter_records),
            "chapter_range": [config["start_chapter"], config["end_chapter"]],
            "package": str(package),
            "package_sha256": _sha256(package),
            "chapters": chapter_records,
            "final_deterministic_audit": str(final_audit_path),
            **delivery_fields,
        },
    )
    return {
        "outcome": "success",
        "result": {
            "status": "pass",
            "candidate_package": str(package),
            "candidate_package_manifest": str(manifest),
            **delivery_fields,
            "chapter_count": len(chapter_records),
            "production_modified": False,
        },
    }


def execute_action(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("candidate_only") is not True or request.get("production_allowed") is not False:
        return {
            "outcome": "failed",
            "result": {"status": "blocked", "reason": "candidate_boundary_not_sealed"},
        }
    action = request.get("action")
    if action == "preflight":
        return _preflight(request)
    if action == "generate_batch":
        return _generate_batch(request)
    if action == "continuity_checkpoint":
        return _continuity_checkpoint(request)
    if action in {"deterministic_check", "deterministic_reaudit"}:
        return _deterministic_check(request)
    if action == "heavy_audit":
        return _heavy_audit(request)
    if action == "revision_support_scribe":
        return _revision_support(request, role="Scribe")
    if action == "revision_support_verifier":
        return _revision_support(request, role="Verifier")
    if action == "rewrite_batch":
        return _rewrite_handoff(request)
    if action == "final_acceptance":
        return _candidate_package(request)
    raise ValueError(f"unsupported background action: {action}")


def run_attempt(
    root: Path,
    *,
    project: str,
    job_id: str,
    attempt_id: str,
) -> int:
    request_path = (
        job_dir(root, project, job_id)
        / "attempts"
        / attempt_id
        / "action_request.yml"
    )
    request = safe_read_yaml(request_path)
    if not isinstance(request, dict):
        raise FileNotFoundError(request_path)
    if not request.get("lease_token") or not request.get("lease_expires_at"):
        state = load_job_state(root, project, job_id)
        active = state.get("active_attempt") or {}
        if active.get("attempt_id") == attempt_id:
            request["lease_token"] = active.get("lease_token")
            request["lease_expires_at"] = active.get("lease_expires_at")
    receipt_path = process_receipt_path(root, project, job_id, attempt_id)
    if receipt_path.exists():
        return 0
    try:
        execution = execute_action(request)
        outcome = str(execution.get("outcome") or "failed")
        result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
        capacity_reset_at = execution.get("capacity_reset_at")
        retry_at = execution.get("retry_at")
        exit_code = (
            0
            if outcome == "success"
            else 75
            if outcome in {"capacity_wait", "retry_wait"}
            else 1
        )
    except Exception as exc:  # receipt must survive action-level failures
        outcome = "failed_recoverable"
        exit_code = 1
        capacity_reset_at = None
        retry_at = None
        result = {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
    write_process_receipt(
        root,
        project=project,
        job_id=job_id,
        attempt_id=attempt_id,
        idempotency_key=str(request["idempotency_key"]),
        lease_token=str(request["lease_token"]),
        outcome=outcome,
        exit_code=exit_code,
        result=result,
        capacity_reset_at=str(capacity_reset_at) if capacity_reset_at else None,
        retry_at=str(retry_at) if retry_at else None,
        now=_utc_now(),
    )
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    return run_attempt(
        args.root.resolve(),
        project=args.project,
        job_id=args.job_id,
        attempt_id=args.attempt_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
