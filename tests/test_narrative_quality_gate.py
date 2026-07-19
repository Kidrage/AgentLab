from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_runtime.background_job_controller import create_crown_delivery_job
from agent_runtime.narrative.audit.gate import evaluate_narrative_seal
from agent_runtime.narrative.audit.integrity import verify_audit_source_integrity
from agent_runtime.narrative.quality.scorecard import validate_quality_scorecard
from agent_runtime.narrative.quality.revision import compile_scene_revision_contract
from agent_runtime.narrative.quality.blind_review import select_candidate_after_blind_review
from agent_runtime.narrative.quality.uplift import build_revision_uplift_receipt
from agent_runtime.narrative.quality.calibration import evaluate_calibration_gate
from agent_runtime.narrative.quality.workflow import run_local_revision_closure


HASH = "current-body"
PASS_FICTION = {"status": "pass", "candidate_sha256": HASH, "findings": []}
PASS_CONTINUITY = {
    "status": "pass",
    "candidate_sha256": HASH,
    "blocking_issue_count": 0,
    "failures": [],
}
SOURCE_INTEGRITY = {"status": "pass", "candidate_sha256": HASH, "issues": []}


def _quality_scorecard(
    *,
    blocking_dimension: str | None = None,
) -> dict:
    dimensions = {}
    for name in (
        "causal_reasoning",
        "strategic_competence",
        "character_agency",
        "dramatic_tension",
        "reader_curiosity",
        "non_formulaic_progression",
    ):
        is_blocking = name == blocking_dimension
        dimensions[name] = {
            "score": 2 if is_blocking else 5,
            "severity": "blocking" if is_blocking else "pass",
            "evidence": {
                "chapter": 26,
                "scene": "council",
                "excerpt_or_locator": "paragraph 12",
            },
            "reason": "specific evidence",
            "revision_target": "specific scene target" if is_blocking else "none",
        }
    return {
        "schema_version": 1,
        "status": "blocked" if blocking_dimension else "pass",
        "candidate_sha256": HASH,
        "dimensions": dimensions,
    }


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
            _quality_scorecard(blocking_dimension="character_agency"),
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
        narrative_quality_scorecard=_quality_scorecard(),
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


def test_veto_dimension_blocking_cannot_be_averaged_away() -> None:
    dimensions = {
        name: {
            "score": 5,
            "severity": "pass",
            "evidence": {
                "chapter": 26,
                "scene": "council",
                "excerpt_or_locator": "paragraph 12",
            },
            "reason": "clear evidence",
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
    }
    dimensions["strategic_competence"] = {
        "score": 2,
        "severity": "blocking",
        "evidence": {
            "chapter": 26,
            "scene": "council",
            "excerpt_or_locator": "paragraph 12",
        },
        "reason": "the protagonist ignores information already established",
        "revision_target": "make the decision use known constraints",
    }

    result = validate_quality_scorecard(
        {
            "schema_version": 1,
            "status": "blocked",
            "candidate_sha256": HASH,
            "dimensions": dimensions,
        },
        candidate_sha256=HASH,
    )

    assert result["valid"] is True
    assert result["status"] == "blocked"
    assert result["blocking_dimensions"] == ["strategic_competence"]
    assert result["allow_seal"] is False


def test_malformed_literary_scorecard_fails_seal_closed() -> None:
    decision = evaluate_narrative_seal(
        fiction_review=PASS_FICTION,
        continuity_failure_report=PASS_CONTINUITY,
        narrative_quality_scorecard={
            "status": "pass",
            "candidate_sha256": HASH,
            "dimensions": {
                "causal_reasoning": {
                    "score": 5,
                    "severity": "pass",
                    "evidence": {},
                    "reason": "",
                    "revision_target": "",
                }
            },
        },
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
        required_audits=(
            "fiction_review",
            "continuity_failure_report",
            "narrative_quality_scorecard",
        ),
    )

    assert decision.allow_seal is False
    assert decision.requires_revision is False
    assert "invalid_narrative_quality_scorecard" in decision.blocking_reasons


def test_finding_compiles_to_local_scene_revision_contract() -> None:
    contract = compile_scene_revision_contract(
        {
            "chapter_id": 26,
            "target_scene": "council",
            "problem_type": "strategic_competence",
            "evidence": "paragraph 12: protagonist ignores the sealed route",
            "revision_target": "decision must account for the sealed route",
        },
        must_preserve=["the envoy remains missing", "the route stays sealed"],
        allowed_freedom="dialogue and tactical sequencing",
        causal_requirements=["the revised choice follows known route constraints"],
        character_knowledge_before=["the eastern route is sealed"],
        character_knowledge_after=["the council learns the western cost"],
        decision_cost="lose the neutral guild's support",
        new_information="the western crossing requires a hostage",
        forbidden_regressions=["no new route", "no omniscient knowledge"],
    )

    assert contract["rewrite_scope"] == "scene"
    assert contract["chapter_id"] == 26
    assert contract["must_change"] == [
        "decision must account for the sealed route"
    ]
    assert contract["character_knowledge_before"] == [
        "the eastern route is sealed"
    ]
    assert contract["forbidden_regressions"] == [
        "no new route",
        "no omniscient knowledge",
    ]


def test_revised_candidate_replaces_original_only_after_clean_blind_win() -> None:
    result = select_candidate_after_blind_review(
        original_sha256="original-sha",
        revised_sha256="revised-sha",
        blind_mapping={"A": "original-sha", "B": "revised-sha"},
        blind_receipt={
            "status": "completed",
            "pair_id": "pair-26",
            "judge_id": "judge-independent",
            "preferred_version": "B",
            "preference_strength": "strong",
            "reason": "B preserves canon while making the decision causal",
            "remaining_blocking": [],
            "new_regressions": [],
        },
    )

    assert result == {
        "status": "accepted_revision",
        "replace_current_candidate": True,
        "selected_sha256": "revised-sha",
        "rejected_sha256": "original-sha",
        "reason": "revised_candidate_won_blind_review_without_regression",
    }


def test_blind_winner_with_new_blocking_regression_cannot_replace_original() -> None:
    result = select_candidate_after_blind_review(
        original_sha256="original-sha",
        revised_sha256="revised-sha",
        blind_mapping={"A": "revised-sha", "B": "original-sha"},
        blind_receipt={
            "status": "completed",
            "pair_id": "pair-26",
            "judge_id": "judge-independent",
            "preferred_version": "A",
            "preference_strength": "weak",
            "reason": "A is tenser but breaks established knowledge",
            "remaining_blocking": [],
            "new_regressions": ["omniscient_knowledge"],
        },
    )

    assert result["status"] == "retained_original"
    assert result["replace_current_candidate"] is False
    assert result["selected_sha256"] == "original-sha"
    assert result["reason"] == "revision_introduced_or_retained_blocking"


def test_revision_uplift_receipt_records_dimension_delta_and_accepted_cost() -> None:
    original = _quality_scorecard(blocking_dimension="strategic_competence")
    revised = _quality_scorecard()
    selection = {
        "status": "accepted_revision",
        "replace_current_candidate": True,
        "selected_sha256": "revised-sha",
    }

    receipt = build_revision_uplift_receipt(
        original_scorecard=original,
        revised_scorecard=revised,
        selection=selection,
        revision_cost_usd=0.5,
        revision_wall_seconds=10.0,
    )

    assert receipt["accepted_improvement"] is True
    assert receipt["score_delta_by_dimension"]["strategic_competence"] == 3
    assert receipt["resolved_blocking"] == ["strategic_competence"]
    assert receipt["new_blocking"] == []
    assert receipt["cost_per_accepted_improvement_usd"] == 0.5
    assert receipt["time_per_accepted_improvement_seconds"] == 10.0


def test_quality_claim_stays_blocked_without_user_positives_and_human_pairs() -> None:
    result = evaluate_calibration_gate(
        negative_chapters=[26, 30],
        positive_chapters=[],
        replay_findings={
            26: ["strategic_competence"],
            30: ["dramatic_tension"],
        },
        human_blind_receipts=[],
    )

    assert result["negative_detection"] == {26: True, 30: True}
    assert result["status"] == "blocked"
    assert result["quality_uplift_claim_allowed"] is False
    assert result["blocking_reasons"] == [
        "missing_user_positive_samples",
        "insufficient_human_blind_pairs",
    ]


def test_revision_closure_changes_only_target_scene_and_requires_blind_win() -> None:
    observed: dict[str, object] = {}
    contract = {
        "revision_contract_id": "rev-26",
        "chapter_id": 26,
        "target_scene": "council",
        "rewrite_scope": "scene",
        "must_preserve": ["the envoy remains missing"],
        "must_change": ["the decision uses the sealed route constraint"],
    }

    def writer(scene: str, received_contract: dict) -> str:
        observed["writer_scene"] = scene
        observed["writer_contract"] = received_contract
        return "She rejects the sealed route and pays for the western crossing."

    def deterministic(candidate: dict[str, str]) -> dict[str, object]:
        observed["deterministic_candidate"] = candidate
        return {"status": "pass", "blocking_codes": []}

    def reaudit(candidate: dict[str, str]) -> dict[str, object]:
        observed["reaudit_candidate"] = candidate
        return {"status": "pass", "remaining_blocking": [], "new_regressions": []}

    def blind_judge(packet: dict[str, dict[str, str]]) -> dict[str, object]:
        observed["blind_packet"] = packet
        preferred = next(
            label
            for label, candidate in packet.items()
            if "pays for the western crossing" in candidate["council"]
        )
        return {
            "status": "completed",
            "pair_id": "pair-26",
            "judge_id": "judge-independent",
            "preferred_version": preferred,
            "preference_strength": "strong",
            "reason": "the decision now follows known constraints",
            "remaining_blocking": [],
            "new_regressions": [],
        }

    result = run_local_revision_closure(
        original_scenes={
            "arrival": "The envoy remains missing.",
            "council": "She chooses the sealed eastern route anyway.",
            "aftermath": "The guild waits.",
        },
        revision_contract=contract,
        writer=writer,
        deterministic_check=deterministic,
        independent_reaudit=reaudit,
        blind_judge=blind_judge,
    )

    assert observed["writer_scene"] == (
        "She chooses the sealed eastern route anyway."
    )
    assert observed["writer_contract"] == contract
    assert result["status"] == "accepted_revision"
    assert result["selected_scenes"]["arrival"] == "The envoy remains missing."
    assert result["selected_scenes"]["aftermath"] == "The guild waits."
    assert "western crossing" in result["selected_scenes"]["council"]


def test_new_narrative_jobs_require_literary_scorecard_before_seal(tmp_path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    state = create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-quality-required",
        eval_id="eval-quality",
        start_chapter=1,
        end_chapter=1,
        writer_worker="claude_code",
        chapter_state_plan="plan.yml",
        now="2026-01-01T00:00:00+00:00",
    )

    assert state["config"]["required_audits"] == [
        "fiction_review",
        "continuity_failure_report",
        "narrative_quality_scorecard",
    ]
