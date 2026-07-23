from __future__ import annotations

from pathlib import Path
import hashlib
from unittest.mock import patch

import yaml

from agent_runtime.background_job_controller import (
    consume_process_receipt,
    create_crown_delivery_job,
    load_job_state,
    schedule_next_attempt,
    write_process_receipt,
)
from agent_runtime.background_job_worker import execute_action
from agent_runtime.narrative.audit.gate import SealDecision
from agent_runtime.narrative.jobs.crown_adapter import create_crown_audit_job_from_contract
from agent_runtime.narrative.jobs.lifecycle import next_after_heavy_audit


NOW = "2026-07-19T10:00:00+00:00"
AUDIT_HASH = "candidate-hash-001"
AUDIT_CONTRACT = {
    "project_id": "Crown_of_Ash",
    "narrative_job_identity": {
        "job_kind": "narrative_audit",
        "run_mode": "audit_only",
    },
}


def _passing_quality_scorecard(start: int = 1, end: int = 10) -> dict:
    return {
        "status": "pass",
        "candidate_sha256": AUDIT_HASH,
        "chapters": [
            {
                "chapter_id": chapter,
                "status": "pass",
                "dimensions": {
                    name: {
                        "score": 5,
                        "severity": "pass",
                        "evidence": {
                            "chapter": chapter,
                            "scene": "opening",
                            "excerpt_or_locator": "paragraph 1",
                        },
                        "reason": "specific evidence",
                        "revision_target": "none",
                    }
                    for name in (
                        "causal_reasoning",
                        "strategic_competence",
                        "character_agency",
                        "dramatic_tension",
                        "reader_curiosity",
                        "non_formulaic_progression",
                    )
                },
            }
            for chapter in range(start, end + 1)
        ],
    }


def _audit_result(
    *,
    blocked: bool = False,
    independent: bool = False,
    findings: list[dict] | None = None,
) -> dict:
    result = {
        "status": "pass",
        "task_id": "reaudit-1" if independent else "audit-1",
        "run_dir": "/candidate/audit/run",
        "candidate_sha256": AUDIT_HASH,
        "audit_source_integrity": {
            "status": "pass",
            "candidate_sha256": AUDIT_HASH,
            "issues": [],
        },
        "fiction_review": {
            "status": "blocked" if blocked else "warn" if findings else "pass",
            "candidate_sha256": AUDIT_HASH,
            "findings": findings or [],
        },
        "continuity_failure_report_data": {
            "status": "pass",
            "candidate_sha256": AUDIT_HASH,
            "blocking_issue_count": 0,
        },
        "narrative_quality_scorecard": _passing_quality_scorecard(),
    }
    if independent:
        result["independent_reaudit"] = {
            "status": "pass",
            "independent_context": True,
            "audit_task_id": "reaudit-1",
            "source_audit_task_id": "audit-1",
            "candidate_sha256": AUDIT_HASH,
        }
    return result


def _complete(root: Path, job_id: str, result: dict) -> dict:
    state = load_job_state(root, "Crown_of_Ash", job_id)
    if isinstance(result.get("narrative_quality_scorecard"), dict):
        batch = state["current_batch"]
        result["narrative_quality_scorecard"] = _passing_quality_scorecard(
            int(batch["start"]), int(batch["end"])
        )
        result["tiered_audit"] = {
            "status": "pass",
            "chapters": [
                {"chapter_id": chapter, "status": "pass"}
                for chapter in range(int(batch["start"]), int(batch["end"]) + 1)
            ],
        }
    active = state["active_attempt"]
    write_process_receipt(
        root,
        project="Crown_of_Ash",
        job_id=job_id,
        attempt_id=active["attempt_id"],
        idempotency_key=active["idempotency_key"],
        lease_token=active["lease_token"],
        outcome="success",
        exit_code=0,
        result=result,
        now=NOW,
    )
    return consume_process_receipt(
        root, project="Crown_of_Ash", job_id=job_id, now=NOW
    )


def _complete_revision_support(root: Path, job_id: str = "candidate-v1") -> dict:
    scribe = schedule_next_attempt(
        root, project="Crown_of_Ash", job_id=job_id, now=NOW
    )
    assert scribe["action"] == "revision_support_scribe"
    state = _complete(root, job_id, {"status": "pass", "role": "Scribe"})
    assert state["status"] == "awaiting_revision_verifier"
    verifier = schedule_next_attempt(
        root, project="Crown_of_Ash", job_id=job_id, now=NOW
    )
    assert verifier["action"] == "revision_support_verifier"
    return _complete(root, job_id, {"status": "pass", "role": "Verifier"})


def _create_generation_job(root: Path, *, end_chapter: int = 10) -> None:
    (root / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        root,
        project="Crown_of_Ash",
        job_id="candidate-v1",
        eval_id="candidate-v1",
        start_chapter=1,
        end_chapter=end_chapter,
        writer_worker="fake-writer",
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
        now=NOW,
    )
    for expected_action in ("preflight", "generate_batch", "deterministic_check"):
        attempt = schedule_next_attempt(
            root, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        assert attempt["action"] == expected_action
        _complete(root, "candidate-v1", {"status": "pass"})


def test_audit_only_completes_clean_or_with_findings_without_starting_rewrite() -> None:
    clean = next_after_heavy_audit(
        job_kind="narrative_audit",
        decision=SealDecision("pass", True, False, ()),
        automatic_rewrite_count=0,
    )
    findings = next_after_heavy_audit(
        job_kind="narrative_audit",
        decision=SealDecision(
            "revision_required",
            False,
            True,
            ("fiction_review_blocked",),
        ),
        automatic_rewrite_count=0,
    )

    assert clean.status == "completed_clean"
    assert findings.status == "completed_with_findings"
    assert findings.schedule_rewrite is False


def test_generation_stops_after_two_unsuccessful_automatic_rewrites() -> None:
    blocked = SealDecision(
        "revision_required",
        False,
        True,
        ("fiction_review_blocked",),
    )

    first = next_after_heavy_audit(
        job_kind="narrative_generation",
        decision=blocked,
        automatic_rewrite_count=0,
    )
    second = next_after_heavy_audit(
        job_kind="narrative_generation",
        decision=blocked,
        automatic_rewrite_count=1,
    )
    exhausted = next_after_heavy_audit(
        job_kind="narrative_generation",
        decision=blocked,
        automatic_rewrite_count=2,
    )

    assert first.status == second.status == "rewrite_required"
    assert exhausted.status == "decision_required"
    assert exhausted.automatic_rewrite_exhausted is True
    assert exhausted.reason == "insufficient_revision_uplift"


def test_audit_only_job_checks_all_batches_and_completes_with_findings(
    tmp_path: Path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_audit_job_from_contract(
        tmp_path,
        mission_contract=AUDIT_CONTRACT,
        job_id="audit-v1",
        eval_id="audit-v1",
        start_chapter=1,
        end_chapter=20,
        batch_size=10,
        now=NOW,
    )

    first = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="audit-v1", now=NOW
    )
    assert first["action"] == "heavy_audit"
    state = _complete(tmp_path, "audit-v1", _audit_result(blocked=True))
    assert state["status"] == "awaiting_heavy_audit"
    assert state["current_batch"] == {"number": 2, "start": 11, "end": 20}

    second = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="audit-v1", now=NOW
    )
    assert second["action"] == "heavy_audit"
    state = _complete(tmp_path, "audit-v1", _audit_result())

    assert state["status"] == "completed_with_findings"
    assert [batch["status"] for batch in state["audited_batches"]] == [
        "completed_with_findings",
        "completed_clean",
    ]
    assert state["automatic_rewrite_count"] == 0
    receipt = yaml.safe_load(
        (
            tmp_path
            / "projects/Crown_of_Ash/background_jobs/audit-v1/completion_receipt.yml"
        ).read_text()
    )
    assert receipt["status"] == "completed_with_findings"
    assert receipt["sealed_batches"] == []
    assert len(receipt["audited_batches"]) == 2


def test_nonblocking_findings_are_not_mislabeled_clean(tmp_path: Path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_audit_job_from_contract(
        tmp_path,
        mission_contract=AUDIT_CONTRACT,
        job_id="audit-warn-v1",
        eval_id="audit-warn-v1",
        start_chapter=1,
        end_chapter=10,
        now=NOW,
    )
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="audit-warn-v1", now=NOW
    )

    state = _complete(
        tmp_path,
        "audit-warn-v1",
        _audit_result(findings=[{"chapter": 3, "severity": "warn"}]),
    )

    assert state["status"] == "completed_with_findings"
    assert state["audited_batches"][0]["finding_count"] == 1
    assert state["findings"][0]["audit"] == "fiction_review"


def test_two_failed_revision_cycles_stop_for_user_decision(tmp_path: Path) -> None:
    _create_generation_job(tmp_path)

    for expected_count in (1, 2):
        schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        state = _complete(
            tmp_path,
            "candidate-v1",
            _audit_result(blocked=True, independent=expected_count > 1),
        )
        assert state["status"] == "awaiting_revision_scribe"
        state = _complete_revision_support(tmp_path)
        assert state["status"] == "rewrite_required"
        rewrite = schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        if expected_count == 1:
            request = yaml.safe_load(Path(rewrite["action_request_path"]).read_text())
            assert request["job_kind"] == "narrative_revision"
            assert request["run_mode"] == "targeted_rewrite"
            assert request["source_job_id"] == "candidate-v1"
            assert request["triggered_by_audit_id"] == "audit-1"
        _complete(tmp_path, "candidate-v1", {"status": "pass"})
        schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        state = _complete(tmp_path, "candidate-v1", {"status": "pass"})
        assert state["automatic_rewrite_count"] == expected_count

    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    state = _complete(
        tmp_path,
        "candidate-v1",
        _audit_result(blocked=True, independent=True),
    )

    assert state["status"] == "decision_required"
    assert state["automatic_rewrite_exhausted"] is True
    assert state["decision_reason"] == "insufficient_revision_uplift"


def test_rewritten_batch_requires_hash_bound_independent_reaudit(tmp_path: Path) -> None:
    _create_generation_job(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    _complete(tmp_path, "candidate-v1", _audit_result(blocked=True))
    _complete_revision_support(tmp_path)
    for _ in range(2):
        schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        _complete(tmp_path, "candidate-v1", {"status": "pass"})
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )

    state = _complete(tmp_path, "candidate-v1", _audit_result())

    assert state["status"] == "blocked"
    assert state["last_error"] == "missing_independent_reaudit"
    assert state["sealed_batches"] == []


def test_controller_recomputes_false_green_worker_decision(tmp_path: Path) -> None:
    _create_generation_job(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    result = _audit_result(blocked=True)
    result["seal_decision"] = {
        "status": "pass",
        "allow_seal": True,
        "requires_revision": False,
        "blocking_reasons": [],
    }

    state = _complete(tmp_path, "candidate-v1", result)

    assert state["status"] == "awaiting_revision_scribe"
    state = _complete_revision_support(tmp_path)
    assert state["status"] == "rewrite_required"
    assert state["sealed_batches"] == []


def test_automatic_rewrite_allowance_resets_for_each_batch(tmp_path: Path) -> None:
    _create_generation_job(tmp_path, end_chapter=20)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    _complete(tmp_path, "candidate-v1", _audit_result(blocked=True))
    _complete_revision_support(tmp_path)
    for _ in range(2):
        schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
        )
        _complete(tmp_path, "candidate-v1", {"status": "pass"})
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    state = _complete(
        tmp_path,
        "candidate-v1",
        _audit_result(independent=True),
    )
    assert state["status"] == "batch_sealed"
    assert state["automatic_rewrite_count"] == 1

    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="candidate-v1", now=NOW
    )
    state = load_job_state(tmp_path, "Crown_of_Ash", "candidate-v1")

    assert attempt["action"] == "generate_batch"
    assert state["current_batch"] == {"number": 2, "start": 11, "end": 20}
    assert state["automatic_rewrite_count"] == 0
    assert state["automatic_rewrite_exhausted"] is False


def test_worker_independent_reaudit_receipt_is_bound_to_fresh_run_and_hash(
    tmp_path: Path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    source = project / "runs" / "source-ch01" / "fiction_draft.md"
    source.parent.mkdir(parents=True)
    source.write_text("candidate body", encoding="utf-8")
    source_hash = hashlib.sha256(b"candidate body").hexdigest()
    task_id = "task_narrative_heavy_audit_ch001_ch010_attempt-1-heavy_audit"
    run_dir = project / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "fiction_review.yml").write_text("status: pass\n", encoding="utf-8")
    (run_dir / "continuity_failure_report.yml").write_text(
        "status: pass\nblocking_issue_count: 0\n",
        encoding="utf-8",
    )
    manifest_path = run_dir / "narrative_audit_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "chapter": 1,
                        "files": {
                            "fiction_draft.md": {
                                "path": "runs/source-ch01/fiction_draft.md",
                                "sha256": source_hash,
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    request = {
        "job_id": "audit-v1",
        "project": "Crown_of_Ash",
        "attempt_id": "attempt-1-heavy_audit",
        "action": "heavy_audit",
        "candidate_only": True,
        "production_allowed": False,
        "agentlab_root": str(tmp_path),
        "batch": {"number": 1, "start": 1, "end": 10},
        "config": {"narrative_adapter": "crown", "eval_id": "eval-v1"},
        "require_independent_reaudit": True,
        "prior_results": {"heavy_audit": {"task_id": "audit-before-rewrite"}},
    }
    with patch(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        return_value={
            "prepared": {
                "status": "ready",
                "manifest_path": str(manifest_path),
            },
            "precheck": {"status": "pass", "blocking_codes": []},
        },
    ), patch(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        return_value={
            "success": True,
            "judge_receipt": {
                "judge_id": "Reviewer",
                "context_id": task_id,
            },
        },
    ):
        result = execute_action(request)

    receipt = result["result"]["independent_reaudit"]
    assert result["outcome"] == "success"
    assert result["result"]["seal_decision"]["blocking_reasons"] == []
    assert result["result"]["seal_decision"]["allow_seal"] is True
    assert receipt["audit_task_id"] == task_id
    assert receipt["source_audit_task_id"] == "audit-before-rewrite"
    assert receipt["candidate_sha256"] == result["result"]["candidate_sha256"]
    assert receipt["independent_context"] is True


def test_heavy_audit_without_explicit_crown_adapter_fails_closed(
    tmp_path: Path,
) -> None:
    result = execute_action(
        {
            "job_id": "audit-v1",
            "project": "OtherNovel",
            "attempt_id": "attempt-1-heavy-audit",
            "action": "heavy_audit",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "batch": {"number": 1, "start": 1, "end": 10},
            "config": {},
        }
    )

    assert result["outcome"] == "failed"
    assert result["result"]["reason"] == "unsupported_narrative_audit_adapter"
