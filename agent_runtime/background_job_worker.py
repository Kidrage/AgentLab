"""Isolated worker for one durable AgentLab background-job attempt."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
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


def _deterministic_check(request: dict[str, Any]) -> dict[str, Any]:
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
    from agent_runtime.narrative_heavy_audit import prepare_crown_narrative_heavy_audit
    from agent_runtime.narrative.audit.gate import evaluate_narrative_seal
    from agent_runtime.narrative.audit.integrity import verify_audit_source_integrity
    from agent_runtime.pipeline_runner import run_full_pipeline

    root = Path(request["agentlab_root"])
    batch = request["batch"]
    clean_attempt = re.sub(r"[^A-Za-z0-9_-]+", "_", request["attempt_id"])
    task_id = (
        f"task_narrative_heavy_audit_ch{int(batch['start']):03d}_"
        f"ch{int(batch['end']):03d}_{clean_attempt}"
    )[:85]
    prepared = prepare_crown_narrative_heavy_audit(
        root,
        eval_id=str(request["config"]["eval_id"]),
        start_chapter=int(batch["start"]),
        end_chapter=int(batch["end"]),
        task_id=task_id,
    )
    if prepared.get("status") != "ready":
        return {
            "outcome": "failed",
            "result": {
                "status": "blocked",
                "reason": "heavy_audit_prepare_blocked",
                "issues": prepared.get("issues", []),
            },
        }
    pipeline = run_full_pipeline(
        root,
        request["project"],
        task_id,
        dry_run=False,
        fake_provider=False,
        budget_mode="max-quality",
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
    manifest = safe_read_yaml(Path(str(prepared["manifest_path"])), default={}) or {}
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
            "run_dir": str(run_dir),
        }
    decision = evaluate_narrative_seal(
        fiction_review=fiction_evidence,
        continuity_failure_report=continuity_evidence,
        narrative_quality_scorecard=quality_evidence,
        candidate_sha256=str(candidate_sha256) if candidate_sha256 else None,
        audit_source_integrity=integrity,
        required_audits=tuple(
            str(item)
            for item in config.get(
                "required_audits",
                ["fiction_review", "continuity_failure_report"],
            )
        ),
        require_independent_reaudit=bool(request.get("require_independent_reaudit")),
        independent_reaudit=independent_reaudit,
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
            "audit_source_integrity": integrity,
            "fiction_review": fiction_evidence,
            "continuity_failure_report_data": continuity_evidence,
            "narrative_quality_scorecard": quality_evidence,
            "independent_reaudit": independent_reaudit,
            "fiction_review_path": str(fiction_path),
            "continuity_failure_report": str(continuity_path),
            "rewrite_proposal": str(proposal_path) if proposal_path.is_file() else None,
        },
    }


def _rewrite_handoff(request: dict[str, Any]) -> dict[str, Any]:
    """Fail closed after preserving the heavy-audit rewrite proposal."""
    heavy = (request.get("prior_results") or {}).get("heavy_audit") or {}
    output = _attempt_dir(request) / "rewrite_handoff.yml"
    handoff = {
        "schema_version": 1,
        "status": "blocked",
        "candidate_only": True,
        "production_modified": False,
        "chapter_range": [request["batch"]["start"], request["batch"]["end"]],
        "heavy_audit_task_id": heavy.get("task_id"),
        "continuity_failure_report": heavy.get("continuity_failure_report"),
        "rewrite_proposal": heavy.get("rewrite_proposal"),
        "reason": "automatic_rewrite_requires_a_validated_correction_state_plan",
    }
    atomic_write_yaml(output, handoff)
    return {
        "outcome": "success",
        "result": {
            "status": "blocked",
            "reason": handoff["reason"],
            "rewrite_handoff": str(output),
        },
    }


def _candidate_package(request: dict[str, Any]) -> dict[str, Any]:
    from agent_runtime.crown_candidate_audit import write_crown_completion_batch_audit
    from agent_runtime.crown_candidate_audit import production_manuscript_files
    from agent_runtime.narrative_delivery import validate_narrative_delivery
    from agent_runtime.narrative_eval import _safe_eval_task_id

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
    for chapter in range(
        int(config["start_chapter"]), int(config["end_chapter"]) + 1
    ):
        task_id = _safe_eval_task_id(chapter, str(config["eval_id"]))
        run_dir = project_root / "runs" / task_id
        validation = validate_narrative_delivery(run_dir)
        draft = run_dir / "fiction_draft.md"
        if not validation.get("valid") or not draft.is_file():
            issues.append(f"invalid_candidate_chapter:{chapter}")
            continue
        chapter_records.append(
            {
                "chapter": chapter,
                "task_id": task_id,
                "source": str(draft),
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

    artifacts = job_dir(root, request["project"], request["job_id"]) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
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
        },
    )
    return {
        "outcome": "success",
        "result": {
            "status": "pass",
            "candidate_package": str(package),
            "candidate_package_manifest": str(manifest),
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
    if action in {"deterministic_check", "deterministic_reaudit"}:
        return _deterministic_check(request)
    if action == "heavy_audit":
        return _heavy_audit(request)
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
