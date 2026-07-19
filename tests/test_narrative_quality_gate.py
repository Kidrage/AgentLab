from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_runtime.narrative.audit.gate import evaluate_narrative_seal
from agent_runtime.narrative.audit.integrity import verify_audit_source_integrity


HASH = "current-body"
PASS_FICTION = {"status": "pass", "candidate_sha256": HASH, "findings": []}
PASS_CONTINUITY = {
    "status": "pass",
    "candidate_sha256": HASH,
    "blocking_issue_count": 0,
    "failures": [],
}
SOURCE_INTEGRITY = {"status": "pass", "candidate_sha256": HASH, "issues": []}


@pytest.mark.parametrize(
    ("fiction", "continuity", "quality", "reason"),
    [
        (
            {"status": "blocked", "candidate_sha256": HASH, "findings": ["flat causality"]},
            PASS_CONTINUITY,
            None,
            "fiction_review_blocked",
        ),
        (
            {"status": "pass", "verdict": "fail", "blocking": True, "candidate_sha256": HASH},
            PASS_CONTINUITY,
            None,
            "fiction_review_blocked",
        ),
        (
            PASS_FICTION,
            {"status": "blocked", "candidate_sha256": HASH, "blocking_issue_count": 1},
            None,
            "continuity_blocked",
        ),
        (
            PASS_FICTION,
            PASS_CONTINUITY,
            {
                "status": "blocked",
                "candidate_sha256": HASH,
                "dimensions": {"character_agency": {"severity": "blocking"}},
            },
            "literary_quality_blocked",
        ),
    ],
)
def test_any_content_blocking_vetoes_seal_and_requests_revision(
    fiction: dict,
    continuity: dict,
    quality: dict | None,
    reason: str,
) -> None:
    decision = evaluate_narrative_seal(
        fiction_review=fiction,
        continuity_failure_report=continuity,
        narrative_quality_scorecard=quality,
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
    )

    assert decision.allow_seal is False
    assert decision.requires_revision is True
    assert reason in decision.blocking_reasons


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"fiction_review": None}, "missing_fiction_review"),
        ({"continuity_failure_report": None}, "missing_continuity_failure_report"),
        (
            {
                "required_audits": (
                    "fiction_review",
                    "continuity_failure_report",
                    "narrative_quality_scorecard",
                )
            },
            "missing_narrative_quality_scorecard",
        ),
        (
            {"promotion_requested": True, "user_acceptance_receipt": None},
            "missing_user_acceptance_receipt",
        ),
        (
            {
                "candidate_sha256": "new-body",
                "fiction_review": {"status": "pass", "candidate_sha256": "old-body"},
                "continuity_failure_report": {"status": "pass", "candidate_sha256": "old-body"},
            },
            "fiction_review_candidate_hash_mismatch",
        ),
        (
            {"require_independent_reaudit": True, "independent_reaudit": None},
            "missing_independent_reaudit",
        ),
        (
            {
                "require_independent_reaudit": True,
                "independent_reaudit": {
                    "status": "pass",
                    "independent_context": True,
                    "audit_task_id": "reaudit-2",
                    "candidate_sha256": HASH,
                },
            },
            "independent_reaudit_source_task_missing",
        ),
        (
            {
                "promotion_requested": True,
                "candidate_sha256": "current-body",
                "user_acceptance_receipt": {"status": "accepted", "candidate_sha256": "old-body"},
            },
            "stale_user_acceptance_receipt",
        ),
        (
            {"expected_lease_token": "lease-new", "receipt_lease_token": "lease-expired"},
            "attempt_lease_expired",
        ),
    ],
)
def test_invalid_or_stale_evidence_fails_closed_without_requesting_rewrite(
    overrides: dict,
    reason: str,
) -> None:
    arguments = {
        "fiction_review": PASS_FICTION,
        "continuity_failure_report": PASS_CONTINUITY,
        "candidate_sha256": HASH,
        "audit_source_integrity": SOURCE_INTEGRITY,
    }
    arguments.update(overrides)

    decision = evaluate_narrative_seal(**arguments)

    assert decision.allow_seal is False
    assert decision.requires_revision is False
    assert reason in decision.blocking_reasons


def test_complete_current_evidence_allows_candidate_seal() -> None:
    decision = evaluate_narrative_seal(
        fiction_review=PASS_FICTION,
        continuity_failure_report=PASS_CONTINUITY,
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
    )

    assert decision.allow_seal is True
    assert decision.status == "pass"


def test_present_passing_required_literary_audit_can_seal() -> None:
    decision = evaluate_narrative_seal(
        fiction_review=PASS_FICTION,
        continuity_failure_report=PASS_CONTINUITY,
        narrative_quality_scorecard={
            "status": "pass",
            "candidate_sha256": HASH,
            "dimensions": {},
        },
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
        required_audits=(
            "fiction_review",
            "continuity_failure_report",
            "narrative_quality_scorecard",
        ),
    )

    assert decision.allow_seal is True


def test_audit_source_integrity_detects_body_change(tmp_path: Path) -> None:
    draft = tmp_path / "runs" / "task_ch01" / "fiction_draft.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("original", encoding="utf-8")
    original_hash = hashlib.sha256(b"original").hexdigest()
    manifest = {
        "sources": [
            {
                "chapter": 1,
                "files": {
                    "fiction_draft.md": {
                        "path": "runs/task_ch01/fiction_draft.md",
                        "sha256": original_hash,
                    }
                },
            }
        ]
    }
    draft.write_text("changed after audit preparation", encoding="utf-8")

    integrity = verify_audit_source_integrity(manifest, project_root=tmp_path)

    assert integrity["status"] == "blocked"
    assert integrity["issues"] == ["audited_artifact_hash_changed:1:fiction_draft.md"]
