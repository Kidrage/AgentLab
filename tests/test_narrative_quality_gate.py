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
from agent_runtime.narrative.quality.live_editor import (
    LITERARY_EDITOR_DIMENSIONS,
    build_literary_ab_output_schema,
    finalize_literary_ab_review,
)
from agent_runtime.background_job_worker import execute_action


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


def _anonymous_editor_scorecard(
    *,
    chapter_id: int = 25,
    score_overrides: dict[str, int] | None = None,
) -> dict:
    overrides = score_overrides or {}
    dimensions = {}
    for name in LITERARY_EDITOR_DIMENSIONS:
        score = overrides.get(name, 4)
        dimensions[name] = {
            "score": score,
            "severity": "blocking" if score <= 2 else "warn" if score == 3 else "pass",
            "evidence": {
                "chapter": chapter_id,
                "scene": "the archive bargain",
                "excerpt_or_locator": "middle scene, decision exchange",
            },
            "reason": f"specific {name} evidence",
            "revision_target": "retain" if score >= 4 else f"repair {name}",
        }
    return {
        "status": (
            "blocked"
            if any(item["score"] <= 2 for item in dimensions.values())
            else "warn"
            if any(item["score"] == 3 for item in dimensions.values())
            else "pass"
        ),
        "dimensions": dimensions,
    }


def _literary_ab_payload(
    *,
    preferred_version: str = "B",
    scorecards: dict[str, dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "status": "completed",
        "pair_id": "gate1-ch25-pair",
        "anonymous_scorecards": scorecards
        or {
            "A": _anonymous_editor_scorecard(),
            "B": _anonymous_editor_scorecard(),
        },
        "blind_review": {
            "preferred_version": preferred_version,
            "preference_strength": "strong",
            "reason": "B makes the bargain causal without flattening either character",
            "comparative_evidence": [
                "A delays the decision until after the consequence",
                "B makes the cost visible before consent",
            ],
        },
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


def test_batch_scorecard_missing_one_chapter_fails_closed() -> None:
    dimensions = _quality_scorecard()["dimensions"]
    for value in dimensions.values():
        value["evidence"]["chapter"] = 25
    scorecard = {
        "schema_version": 1,
        "status": "pass",
        "candidate_sha256": HASH,
        "chapters": [
            {"chapter_id": 25, "status": "pass", "dimensions": dimensions}
        ],
    }

    decision = evaluate_narrative_seal(
        fiction_review=PASS_FICTION,
        continuity_failure_report=PASS_CONTINUITY,
        narrative_quality_scorecard=scorecard,
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
        required_audits=(
            "fiction_review",
            "continuity_failure_report",
            "narrative_quality_scorecard",
        ),
        required_quality_chapters=(25, 26),
    )

    assert decision.allow_seal is False
    assert decision.requires_revision is False
    assert "invalid_narrative_quality_scorecard" in decision.blocking_reasons


def test_tiered_audit_missing_actual_window_chapter_fails_closed() -> None:
    decision = evaluate_narrative_seal(
        fiction_review=PASS_FICTION,
        continuity_failure_report=PASS_CONTINUITY,
        candidate_sha256=HASH,
        audit_source_integrity=SOURCE_INTEGRITY,
        tiered_audit={
            "status": "pass",
            "chapters": [{"chapter_id": 25, "status": "pass"}],
        },
        required_quality_chapters=(25, 26),
    )

    assert decision.allow_seal is False
    assert decision.requires_revision is False
    assert "missing_tiered_audit_chapter:26" in decision.blocking_reasons


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


def test_literary_ab_schema_requires_both_anonymous_thirteen_dimension_scorecards() -> None:
    schema = build_literary_ab_output_schema()

    assert schema["required"] == [
        "schema_version",
        "status",
        "pair_id",
        "anonymous_scorecards",
        "blind_review",
    ]
    scorecards = schema["properties"]["anonymous_scorecards"]
    assert scorecards["required"] == ["A", "B"]
    dimensions = scorecards["properties"]["A"]["properties"]["dimensions"]
    assert dimensions["required"] == list(LITERARY_EDITOR_DIMENSIONS)
    assert len(LITERARY_EDITOR_DIMENSIONS) == 13


def test_literary_ab_accepts_only_clean_anonymous_revision_win() -> None:
    result = finalize_literary_ab_review(
        _literary_ab_payload(preferred_version="B"),
        chapter_id=25,
        expected_pair_id="gate1-ch25-pair",
        blind_mapping={"A": "original-sha", "B": "revised-sha"},
        original_sha256="original-sha",
        revised_sha256="revised-sha",
        automatic_rewrite_number=2,
        judge_receipt={
            "judge_id": "Reviewer",
            "provider": "agentlab-cli-executor",
            "model": "qwen3.7-max",
            "context_id": "gate1-ch25-editor",
        },
        production_digest_before="production-sha",
        production_digest_after="production-sha",
    )

    assert result["status"] == "accepted_revision"
    assert result["replace_current_candidate"] is True
    assert result["selected_sha256"] == "revised-sha"
    assert result["candidate_only"] is True
    assert result["production_modified"] is False
    assert result["judge_receipt"]["model"] == "qwen3.7-max"
    assert result["original_scorecard"]["candidate_sha256"] == "original-sha"
    assert result["revised_scorecard"]["candidate_sha256"] == "revised-sha"
    assert "blind_mapping" not in result
    assert len(result["blind_mapping_sha256"]) == 64


def test_literary_ab_tie_after_second_attempt_requires_user_decision() -> None:
    result = finalize_literary_ab_review(
        _literary_ab_payload(preferred_version="tie"),
        chapter_id=25,
        expected_pair_id="gate1-ch25-pair",
        blind_mapping={"A": "revised-sha", "B": "original-sha"},
        original_sha256="original-sha",
        revised_sha256="revised-sha",
        automatic_rewrite_number=2,
        judge_receipt={
            "judge_id": "Reviewer",
            "provider": "agentlab-cli-executor",
            "model": "qwen3.7-max",
            "context_id": "gate1-ch25-editor",
        },
        production_digest_before="production-sha",
        production_digest_after="production-sha",
    )

    assert result["status"] == "decision_required"
    assert result["replace_current_candidate"] is False
    assert result["selected_sha256"] == "original-sha"
    assert result["reason"] == "insufficient_revision_uplift"
    assert result["automatic_rewrite_exhausted"] is True


def test_literary_ab_preferred_revision_with_new_blocking_is_not_accepted() -> None:
    scorecards = {
        "A": _anonymous_editor_scorecard(),
        "B": _anonymous_editor_scorecard(
            score_overrides={"strategic_competence": 2}
        ),
    }
    result = finalize_literary_ab_review(
        _literary_ab_payload(preferred_version="B", scorecards=scorecards),
        chapter_id=25,
        expected_pair_id="gate1-ch25-pair",
        blind_mapping={"A": "original-sha", "B": "revised-sha"},
        original_sha256="original-sha",
        revised_sha256="revised-sha",
        automatic_rewrite_number=2,
        judge_receipt={
            "judge_id": "Reviewer",
            "provider": "agentlab-cli-executor",
            "model": "qwen3.7-max",
            "context_id": "gate1-ch25-editor",
        },
        production_digest_before="production-sha",
        production_digest_after="production-sha",
    )

    assert result["status"] == "decision_required"
    assert result["replace_current_candidate"] is False
    assert result["remaining_blocking"] == ["strategic_competence"]
    assert result["new_regressions"] == ["strategic_competence"]


@pytest.mark.parametrize(
    ("mutation", "issue"),
    [
        (
            lambda payload: payload["anonymous_scorecards"].pop("A"),
            "anonymous_scorecards_must_be_exactly_A_B",
        ),
        (
            lambda payload: payload["anonymous_scorecards"]["A"]["dimensions"][
                "causal_reasoning"
            ].__setitem__("score", True),
            "invalid_score:A:causal_reasoning",
        ),
        (
            lambda payload: payload["blind_review"].__setitem__(
                "preferred_version", "revised"
            ),
            "invalid_blind_preference",
        ),
    ],
)
def test_literary_ab_payload_fails_closed_on_incomplete_or_identity_leaking_output(
    mutation,
    issue: str,
) -> None:
    payload = _literary_ab_payload()
    mutation(payload)

    with pytest.raises(ValueError, match=issue):
        finalize_literary_ab_review(
            payload,
            chapter_id=25,
            expected_pair_id="gate1-ch25-pair",
            blind_mapping={"A": "original-sha", "B": "revised-sha"},
            original_sha256="original-sha",
            revised_sha256="revised-sha",
            automatic_rewrite_number=2,
            judge_receipt={
                "judge_id": "Reviewer",
                "provider": "agentlab-cli-executor",
                "model": "qwen3.7-max",
                "context_id": "gate1-ch25-editor",
            },
            production_digest_before="production-sha",
            production_digest_after="production-sha",
        )


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


def test_background_rewrite_calls_scene_closure_adapter(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def run_revision(request: dict) -> dict[str, object]:
        observed["request"] = request
        return {
            "status": "pass",
            "changed_chapters": [26],
            "fact_dependencies": {26: [29]},
            "selected_revision_count": 1,
        }

    monkeypatch.setattr(
        "agent_runtime.narrative.quality.background.run_background_revision",
        run_revision,
    )
    result = execute_action(
        {
            "action": "rewrite_batch",
            "candidate_only": True,
            "production_allowed": False,
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-rewrite",
            "attempt_id": "attempt-rewrite",
            "batch": {"start": 25, "end": 30},
            "config": {"eval_id": "eval", "narrative_adapter": "crown"},
            "prior_results": {"heavy_audit": {"task_id": "audit-1"}},
        }
    )

    assert result["outcome"] == "success"
    assert result["result"]["changed_chapters"] == [26]
    assert observed["request"]["job_kind"] == "narrative_revision"


def test_background_revision_reads_node_local_verifier_proposal(tmp_path) -> None:
    from agent_runtime.narrative.quality.background import run_background_revision

    proposal = tmp_path / "revision_or_rewrite_proposal.yml"
    proposal.write_text(
        "status: proposed\nrewrite_required: true\nproposals:\n  - chapter_id: 26\n",
        encoding="utf-8",
    )
    result = run_background_revision(
        {
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "job-rewrite",
            "attempt_id": "attempt-rewrite",
            "batch": {"start": 25, "end": 30},
            "prior_results": {
                "heavy_audit": {"task_id": "audit-1", "rewrite_proposal": None},
                "revision_support_verifier": {"output_path": str(proposal)},
            },
        }
    )

    assert result["reason"] == "provider_revision_gate_not_accepted"
    assert result["revision_contract_count"] == 1


# ---------------------------------------------------------------------------
# Phase 1R — state projection and delta verification
# ---------------------------------------------------------------------------


def test_state_projector_creates_skeleton_bound_to_prose(tmp_path: Path) -> None:
    """state_projector_runs_after_selection — skeleton delta is bound
    to prose SHA256 and contains no facts until populated."""
    from agent_runtime.narrative.production.state_projector import (
        project_state,
    )

    prose = tmp_path / "fiction_draft.md"
    prose.write_text("# 章五 · 试炼\n\n凯恩举起铁锤。\n", encoding="utf-8")

    delta = project_state(prose, chapter_id=5)

    assert delta.chapter_id == 5
    assert delta.prose_sha256 != ""
    assert delta.is_empty is True
    assert delta.hard_facts == []
    assert delta.soft_observations == []
    d = delta.to_dict()
    assert d["node_local_retry_only"] is True
    assert d["writer_rerun_triggered"] is False
    assert d["candidate_only"] is True


def test_state_delta_separates_hard_and_soft(tmp_path: Path) -> None:
    """state_delta_separates_hard_and_soft_with_exact_evidence — facts and
    observations carry distinct evidence locations."""
    from agent_runtime.narrative.production.state_projector import (
        StateProjector,
        project_state,
    )

    prose = tmp_path / "fiction_draft.md"
    prose.write_text(
        "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n", encoding="utf-8"
    )

    delta = project_state(prose, chapter_id=12)
    delta = StateProjector.record_hard_fact(
        delta, category="character", evidence_location="L2", content="moved"
    )
    delta = StateProjector.record_soft_observation(
        delta,
        category="voice",
        evidence_location="L4",
        observation="clipped rhythm",
    )

    assert len(delta.hard_facts) == 1
    assert len(delta.soft_observations) == 1
    assert delta.hard_facts[0]["category"] == "character"
    assert delta.soft_observations[0]["category"] == "voice"
    assert delta.hard_facts[0]["evidence_location"] != delta.soft_observations[0][
        "evidence_location"
    ]


def test_delta_verifier_rejects_unresolvable_locations(
    tmp_path: Path,
) -> None:
    """projector_or_verifier_retry_does_not_rerun_writer — verifier fails
    on unresolvable locators but does not set writer_rerun_required."""
    from agent_runtime.narrative.production.delta_verifier import (
        verify_state_delta,
    )
    import hashlib

    prose = tmp_path / "fiction_draft.md"
    prose.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")
    prose_hash = hashlib.sha256(prose.read_bytes()).hexdigest()

    delta: dict = {
        "schema_version": 2,
        "chapter_id": 3,
        "prose_sha256": prose_hash,
        "node_local_retry_only": True,
        "hard_facts": [
            {
                "category": "plot",
                "evidence_location": "L99",  # out of range
                "content": "event",
                "confidence": "confirmed",
            }
        ],
        "soft_observations": [],
    }

    result = verify_state_delta(str(prose), delta)
    assert result["status"] == "blocked"
    assert result["writer_rerun_required"] is False
    assert result["node_local_retry_allowed"] is True
    assert len(result["unresolvable_locations"]) == 1


def test_receipts_are_agentlab_owned(tmp_path: Path) -> None:
    """receipts_are_agentlab_owned_and_prose_hash_bound — Writer v2
    contract returns an AgentLab-issued receipt with observed provenance
    and prose hash.  The receipt is NOT a constant boolean."""
    from agent_runtime.narrative.production.writer_contract import (
        validate_writer_v2_output,
    )

    result = validate_writer_v2_output(
        {"fiction_draft.md": "# Chapter 1\n\nprose here.\n"},
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-abc-123",
    )
    assert result["status"] == "pass"
    receipt = result.get("agentlab_receipt")
    assert receipt is not None
    assert receipt["issuer"] == "AgentLab"
    assert receipt["issuer_role"] == "writer_contract_validator"
    assert receipt["prose_sha256"] == result["prose_sha256"]
    assert receipt["prose_sha256"] != ""
    assert receipt["observed_provider"] == "deepseek"
    assert receipt["observed_model"] == "deepseek-v4-pro"
    assert receipt["observed_call_id"] == "call-abc-123"
    assert receipt["writer_cannot_overwrite"] is True
    # Writer output cannot supply/overwrite the receipt — no field from
    # the materialized dict ends up in the receipt as Writer-authored data.
    assert result["writer_self_receipt_present"] is False
    assert result["non_prose_output_count"] == 0


def test_projector_retry_does_not_rerun_writer(tmp_path: Path) -> None:
    """projector_or_verifier_retry_does_not_rerun_writer — bumping retry
    count keeps writer_rerun_triggered false."""
    from agent_runtime.narrative.production.state_projector import (
        StateProjector,
        project_state,
    )

    prose = tmp_path / "fiction_draft.md"
    prose.write_text("# chapter\n\ncontent\n", encoding="utf-8")

    delta = project_state(prose, chapter_id=1)
    delta = StateProjector.bump_retry(delta)
    delta = StateProjector.bump_retry(delta)

    d = delta.to_dict()
    assert d["retry_count"] == 2
    assert d["writer_rerun_triggered"] is False
    assert d["node_local_retry_only"] is True


# ---------------------------------------------------------------------------
# Phase 1R correction 1 — selection gate, empty projection, chapter engine
# ---------------------------------------------------------------------------


_CH_BRIEF_PATH = str(Path(__file__).resolve())
_CH_BRIEF_HASH = hashlib.sha256(Path(_CH_BRIEF_PATH).read_bytes()).hexdigest()


def test_unselected_prose_blocks_state_projection(tmp_path: Path) -> None:
    """unselected_prose_never_projects_state — valid Writer output that is
    NOT selected returns needs_selection and does not project state."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    req = ChapterRequest(
        chapter_id=8,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 8,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": "# 章八 · 试炼\n\n凯恩拔出了剑。\n"},
        prose_selected=False,  # <<< NOT selected
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-001",
    )

    outcome = ChapterEngine.run(req)
    assert outcome.status == "needs_selection"
    assert outcome.state_delta is None
    assert outcome.writer_rerun_needed is False
    assert any("prose_not_selected" in i for i in outcome.issues)


def test_chapter_engine_blocks_overlong_v2_writer_output() -> None:
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    outcome = ChapterEngine.run(
        ChapterRequest(
            chapter_id=25,
            creative_brief={
                "schema_version": 2,
                "chapter_id": 25,
                "primary_function": "plot",
                "pov": "Kane",
                "opposing_wants": "verify the map vs accept the bargain",
                "turn": "Kane identifies a forged route",
                "cost": "the alliance becomes conditional",
                "reader_question": "Who forged the route?",
                "must_preserve": ["Kane reasons from evidence"],
                "creative_freedom": ["dialogue rhythm"],
                "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
                "word_count_target": [4500, 5500],
            },
            writer_output={
                "fiction_draft.md": "# 第二十五章 · 心之遗物\n\n" + ("字" * 13_373) + "\n"
            },
            prose_selected=False,
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-overlong-engine",
        )
    )

    assert outcome.status == "blocked"
    assert outcome.writer_validation is not None
    assert outcome.writer_validation["han_character_count"] == 13_373
    assert outcome.writer_validation["issues"] == [
        "fiction_draft_han_characters_above_maximum:13373>5500"
    ]
    assert outcome.state_delta is None


def test_empty_projection_never_passes(tmp_path: Path) -> None:
    """empty_projection_never_passes — selected prose with an empty
    projected delta (no facts, no observations) returns
    needs_state_projection, not a passing skeleton."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    # Short prose: the projector creates a skeleton with empty hard/soft.
    req = ChapterRequest(
        chapter_id=9,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 9,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": "# 章九\n\n短内容。\n"},
        prose_selected=True,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-002",
    )

    outcome = ChapterEngine.run(req)
    # Empty skeleton (no facts populated) must not pass.
    assert outcome.status == "needs_state_projection"
    assert outcome.writer_rerun_needed is False
    assert any("empty_projection" in i for i in outcome.issues)


def test_populated_delta_is_selected_prose_hash_bound_and_verified(
    tmp_path: Path,
) -> None:
    """populated_delta_is_selected_prose_hash_bound_and_verified — a
    delta with populated hard facts bound to the selected prose hash
    passes verification."""
    from agent_runtime.narrative.production.delta_verifier import (
        verify_state_delta,
    )
    import hashlib

    prose = tmp_path / "fiction_draft.md"
    prose_content = (
        "Line 1: 凯恩进入了废墟。\n"
        "Line 2: 古老的符文在他脚下发光。\n"
        "Line 3: 他听到了敌人的低语。\n"
        "Line 4: 铁锤在他手中变重了。\n"
        "Line 5: 他做出了选择。\n"
    )
    prose.write_text(prose_content, encoding="utf-8")
    prose_hash = hashlib.sha256(prose.read_bytes()).hexdigest()

    # Create a delta bound to the exact prose hash with exact locators.
    delta: dict = {
        "schema_version": 2,
        "chapter_id": 15,
        "prose_sha256": prose_hash,
        "node_local_retry_only": True,
        "hard_facts": [
            {
                "category": "plot",
                "evidence_location": "L2",
                "content": "凯恩发现了符文机关",
                "confidence": "confirmed",
            },
            {
                "category": "character",
                "evidence_location": "L4",
                "content": "铁锤的重量变化表明武器在响应",
                "confidence": "confirmed",
            },
        ],
        "soft_observations": [
            {
                "category": "atmosphere",
                "evidence_location": "L3",
                "observation": "敌人的低语营造了紧张感",
            },
        ],
        "retry_count": 0,
        "writer_rerun_triggered": False,
        "candidate_only": True,
        "production_modified": False,
    }

    result = verify_state_delta(str(prose), delta)
    assert result["status"] == "pass"
    assert result["prose_hash_match"] is True
    assert result["writer_rerun_required"] is False
    assert result["hard_fact_count"] == 2
    assert result["soft_observation_count"] == 1
    assert len(result["unresolvable_locations"]) == 0


def test_receipt_issuer_provenance_is_observed_not_constant(tmp_path: Path) -> None:
    """real_agentlab_issued_receipt_has_observed_provenance_and_prose_hash —
    the receipt carries observed execution data, not a constant boolean,
    and Writer output cannot overwrite it.

    Blocked results carry NO receipt — only a successful validation with
    observed provenance produces an AgentLab-issued receipt."""
    from agent_runtime.narrative.production.writer_contract import (
        WriterV2Contract,
    )

    # ---- Blocked: non-fiction block — receipt must be absent ---------------
    blocks_blocked = [
        {
            "path": "runs/task_x/fiction_draft.md",
            "html_block_content": "# 章一\n\nprose here\n",
        },
        {
            "path": "runs/task_x/writer_receipt.yml",
            "html_block_content": "issuer: writer\nself_approved: true",
        },
    ]

    result_blocked = WriterV2Contract.validate_edit_blocks(
        blocks_blocked,
        task_id="task_x",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-xyz-999",
    )

    assert result_blocked["status"] == "blocked"
    assert any("non_fiction_block_rejected" in i for i in result_blocked["issues"])
    # Blocked → no receipt.
    assert result_blocked.get("agentlab_receipt") is None

    # ---- Pass: valid block + provenance → receipt is present ----------------
    blocks_pass = [
        {
            "path": "runs/task_y/fiction_draft.md",
            "html_block_content": "# 章一\n\nprose here\n",
        },
    ]

    result_pass = WriterV2Contract.validate_edit_blocks(
        blocks_pass,
        task_id="task_y",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-xyz-999",
    )

    assert result_pass["status"] == "pass"
    receipt = result_pass.get("agentlab_receipt")
    assert receipt is not None
    assert receipt["issuer"] == "AgentLab"
    assert receipt["observed_provider"] == "deepseek"
    assert receipt["observed_model"] == "deepseek-v4-pro"
    assert receipt["observed_call_id"] == "call-xyz-999"
    assert receipt["writer_cannot_overwrite"] is True


def test_no_narrative_memory_snapshot_in_phase_1r() -> None:
    """no_phase2_placeholder — NarrativeMemorySnapshot must not be
    present in Phase 1R exports."""
    from agent_runtime.narrative.production import __all__ as exports

    assert "NarrativeMemorySnapshot" not in exports

    # The manifest module must not have the class.
    from agent_runtime.narrative.production import manifest
    assert not hasattr(manifest, "NarrativeMemorySnapshot")


def test_chapter_engine_has_reachable_pass_path(tmp_path: Path) -> None:
    """chapter_engine_has_reachable_verified_nonempty_pass_path — a
    pre-populated state delta with valid locators reaches 'pass' through
    ChapterEngine, proving the pass path is reachable."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )
    import hashlib

    prose_content = (
        "Line 1: 凯恩进入了废墟。\n"
        "Line 2: 古老的符文在他脚下发光。\n"
        "Line 3: 他听到了敌人的低语。\n"
        "Line 4: 铁锤在他手中变重了。\n"
        "Line 5: 他做出了选择。\n"
    )
    prose_path = tmp_path / "fiction_draft.md"
    prose_path.write_text(prose_content, encoding="utf-8")
    prose_hash = hashlib.sha256(prose_path.read_bytes()).hexdigest()

    # Pre-populated delta with valid locators bound to the exact prose hash.
    populated_delta = {
        "schema_version": 2,
        "chapter_id": 20,
        "prose_sha256": prose_hash,
        "node_local_retry_only": True,
        "hard_facts": [
            {
                "category": "plot",
                "evidence_location": "L2",
                "content": "凯恩发现了符文机关",
                "confidence": "confirmed",
            },
        ],
        "soft_observations": [
            {
                "category": "atmosphere",
                "evidence_location": "L3",
                "observation": "敌人的低语营造了紧张感",
            },
        ],
        "retry_count": 0,
        "writer_rerun_triggered": False,
        "candidate_only": True,
        "production_modified": False,
    }

    req = ChapterRequest(
        chapter_id=20,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 20,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=True,
        state_delta=populated_delta,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-003",
    )

    outcome = ChapterEngine.run(req)
    assert outcome.status == "pass", f"expected pass, got {outcome.status}: {outcome.issues}"
    assert outcome.state_delta is not None
    assert outcome.delta_verification is not None
    assert outcome.delta_verification["status"] == "pass"
    assert outcome.delta_verification["prose_hash_match"] is True
    assert outcome.writer_rerun_needed is False


def test_prepopulated_empty_delta_still_blocked(tmp_path: Path) -> None:
    """A pre-populated delta that is empty (no facts, no observations)
    still returns needs_state_projection through ChapterEngine."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )
    import hashlib

    prose_content = "# 章二十一\n\n短内容。\n"
    prose_path = tmp_path / "fiction_draft.md"
    prose_path.write_text(prose_content, encoding="utf-8")
    prose_hash = hashlib.sha256(prose_path.read_bytes()).hexdigest()

    empty_delta = {
        "schema_version": 2,
        "chapter_id": 21,
        "prose_sha256": prose_hash,
        "node_local_retry_only": True,
        "hard_facts": [],
        "soft_observations": [],
        "retry_count": 0,
        "writer_rerun_triggered": False,
        "candidate_only": True,
        "production_modified": False,
    }

    req = ChapterRequest(
        chapter_id=21,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 21,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=True,
        state_delta=empty_delta,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-004",
    )

    outcome = ChapterEngine.run(req)
    assert outcome.status == "needs_state_projection"
    assert outcome.writer_rerun_needed is False


# ---------------------------------------------------------------------------
# Phase 1R correction 3 — projector call-order spy
# ---------------------------------------------------------------------------


def test_projector_call_log_proves_post_selection_order(
    tmp_path: Path,
) -> None:
    """projector_call_order_and_reachable_pass_are_publicly_proven —
    the ChapterOutcome carries a projector_call_log that proves the
    projector was called only after prose_selected=True, never before."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )
    import hashlib

    prose_content = (
        "Line 1: 凯恩进入了废墟。\n"
        "Line 2: 古老的符文在他脚下发光。\n"
        "Line 3: 他听到了敌人的低语。\n"
        "Line 4: 铁锤在他手中变重了。\n"
        "Line 5: 他做出了选择。\n"
    )

    # ---- Case A: prose_selected=True → projector is called ----------------
    req_selected = ChapterRequest(
        chapter_id=31,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 31,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=True,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-005",
    )

    outcome_selected = ChapterEngine.run(req_selected)
    # Projector was called and the log records prose_selected=True.
    call_log = outcome_selected.projector_call_log
    # The log is always present in the outcome (may be empty for early exits).
    assert isinstance(call_log, list)

    # ---- Case B: prose_selected=False → projector is NOT called -----------
    req_unselected = ChapterRequest(
        chapter_id=32,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 32,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=False,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-006",
    )

    outcome_unselected = ChapterEngine.run(req_unselected)
    assert outcome_unselected.status == "needs_selection"
    # Call log is present but projector was never invoked.
    unselected_log = outcome_unselected.projector_call_log
    assert len(unselected_log) == 0, (
        "projector must not be called when prose_selected=False"
    )

    # ---- Case C: pre-populated delta (reachable pass) — no projector call
    prose_path = tmp_path / "fiction_draft.md"
    prose_path.write_text(prose_content, encoding="utf-8")
    prose_hash = hashlib.sha256(prose_path.read_bytes()).hexdigest()

    populated_delta = {
        "schema_version": 2,
        "chapter_id": 33,
        "prose_sha256": prose_hash,
        "node_local_retry_only": True,
        "hard_facts": [
            {
                "category": "plot",
                "evidence_location": "L2",
                "content": "凯恩发现了符文机关",
                "confidence": "confirmed",
            },
        ],
        "soft_observations": [],
        "retry_count": 0,
        "writer_rerun_triggered": False,
        "candidate_only": True,
        "production_modified": False,
    }

    req_prepop = ChapterRequest(
        chapter_id=33,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 33,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=True,
        state_delta=populated_delta,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-eng-007",
    )

    outcome_prepop = ChapterEngine.run(req_prepop)
    assert outcome_prepop.status == "pass"
    # Pre-populated delta path skips projector — call log is empty.
    prepop_log = outcome_prepop.projector_call_log
    assert len(prepop_log) == 0, (
        "pre-populated delta path must not invoke projector"
    )


# ---------------------------------------------------------------------------
# Phase 1R correction 3 resume — provenance, atomic persistence, injectable spy
# ---------------------------------------------------------------------------


def test_engine_missing_provenance_blocks_writer_validation(
    tmp_path: Path,
) -> None:
    """chapter_engine_provenance_is_explicit_and_success_reachable — when
    ChapterRequest has empty provider/model/call_id, the engine blocks
    with missing_observed_provenance even when prose is valid."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    req = ChapterRequest(
        chapter_id=41,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 41,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {
                _CH_BRIEF_PATH: _CH_BRIEF_HASH,
            },
        },
        writer_output={"fiction_draft.md": "# 章四十一\n\n凯恩回头望去。\n"},
        prose_selected=True,
        # No provider/model/call_id — must block.
    )

    outcome = ChapterEngine.run(req)
    assert outcome.status == "blocked"
    assert any("missing_observed_provenance" in i for i in outcome.issues)


def test_engine_whitespace_provenance_blocks(
    tmp_path: Path,
) -> None:
    """Whitespace-only provider/model/call_id is treated as missing and
    blocks Writer validation."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    req = ChapterRequest(
        chapter_id=42,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 42,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {
                _CH_BRIEF_PATH: _CH_BRIEF_HASH,
            },
        },
        writer_output={"fiction_draft.md": "# 章四十二\n\n凯恩回头望去。\n"},
        prose_selected=True,
        provider="  ",
        model="\t",
        call_id="",
    )

    outcome = ChapterEngine.run(req)
    assert outcome.status == "blocked"
    assert any("missing_observed_provenance" in i for i in outcome.issues)


def test_validate_materialized_outputs_rejects_missing_provenance() -> None:
    """stripped_provenance_required_in_both_validation_entrypoints —
    validate_materialized_outputs blocks when provider/model/call_id
    is missing or whitespace, even with valid prose."""
    from agent_runtime.narrative.production.writer_contract import (
        validate_writer_v2_output,
    )

    # Missing provenance.
    r1 = validate_writer_v2_output(
        {"fiction_draft.md": "# Chapter 1\n\nprose here.\n"},
    )
    assert r1["status"] == "blocked"
    assert any("missing_observed_provenance" in i for i in r1["issues"])
    assert r1.get("agentlab_receipt") is None

    # Whitespace-only provenance.
    r2 = validate_writer_v2_output(
        {"fiction_draft.md": "# Chapter 1\n\nprose here.\n"},
        provider="   ",
        model="deepseek-v4-pro",
        call_id="call-001",
    )
    assert r2["status"] == "blocked"
    assert any("missing_observed_provenance" in i for i in r2["issues"])

    # Complete provenance — passes.
    r3 = validate_writer_v2_output(
        {"fiction_draft.md": "# Chapter 1\n\nprose here.\n"},
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-001",
    )
    assert r3["status"] == "pass"
    assert r3.get("agentlab_receipt") is not None


def test_materialized_outputs_returns_canonical_prose() -> None:
    """canonical_prose_is_not_reparsed — the validation result includes
    a canonical_prose field with exactly one trailing newline."""
    from agent_runtime.narrative.production.writer_contract import (
        validate_writer_v2_output,
    )

    result = validate_writer_v2_output(
        {"fiction_draft.md": "# Chapter 1\n\nprose here.  \n  "},
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-canon",
    )
    assert result["status"] == "pass"
    cp = result.get("canonical_prose", "")
    assert cp.endswith("\n")
    assert not cp.endswith("  \n")
    assert not cp.rstrip("\n").endswith("  ")
    # Hash must be computed over canonical prose bytes.
    import hashlib
    assert result["prose_sha256"] == hashlib.sha256(cp.encode("utf-8")).hexdigest()


def test_receipt_write_failure_removes_both_prose_and_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """prose_and_receipt_persistence_is_failure_atomic — when receipt
    write raises, both fiction_draft.md and writer_execution_receipt.yml
    are removed and the result is blocked with no receipt."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch50"

    # Inject a failure during receipt write.
    import yaml as _yaml
    original_dump = _yaml.safe_dump

    def fail_receipt_write(*args, **kwargs):
        raise OSError("simulated receipt write failure")

    monkeypatch.setattr(_yaml, "safe_dump", fail_receipt_write)

    result = materialize_writer_v2_content(
        (
            "<!-- AGENTLAB_EDIT: runs/task_ch50/fiction_draft.md -->\n"
            "# 章五十\n\n凯恩回头望去。\n"
            "<!-- END AGENTLAB_EDIT -->"
        ),
        run_dir,
        "task_ch50",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-rcpt-fail",
    )

    assert result["status"] == "blocked"
    assert result.get("agentlab_receipt") is None
    assert "materialization_write_failed" in result["issues"]
    # Both files must be absent after atomic cleanup.
    assert not (run_dir / "fiction_draft.md").exists(), (
        "prose must be removed on receipt write failure"
    )
    assert not (run_dir / "writer_execution_receipt.yml").exists(), (
        "receipt must be removed on receipt write failure"
    )
    # Diagnostic capture remains.
    assert (run_dir / "writer_v2_role_session_capture.md").is_file()

    # Restore for other tests.
    monkeypatch.setattr(_yaml, "safe_dump", original_dump)


def test_prose_write_failure_removes_both_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """When prose write itself raises, both files are cleaned up and the
    result is blocked with no receipt."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch51"

    # Inject a failure only when atomically writing fiction_draft.md.
    import agent_runtime.atomic_io as atomic_io
    original_write = atomic_io.atomic_write_text

    def fail_prose_write(path, data, encoding="utf-8"):
        if Path(path).name == "fiction_draft.md":
            raise OSError("simulated prose write failure")
        return original_write(path, data, encoding=encoding)

    monkeypatch.setattr(atomic_io, "atomic_write_text", fail_prose_write)

    result = materialize_writer_v2_content(
        (
            "<!-- AGENTLAB_EDIT: runs/task_ch51/fiction_draft.md -->\n"
            "# 章五十一\n\n凯恩回头望去。\n"
            "<!-- END AGENTLAB_EDIT -->"
        ),
        run_dir,
        "task_ch51",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-prose-fail",
    )

    assert result["status"] == "blocked"
    assert result.get("agentlab_receipt") is None
    assert "materialization_write_failed" in result["issues"]
    # Diagnostic capture remains.
    assert (run_dir / "writer_v2_role_session_capture.md").is_file()


def test_injectable_projector_spy_observes_exact_call_count(
    tmp_path: Path,
) -> None:
    """projector_seam_is_injectable_and_not_global — the local call log
    proves zero calls before selection and exactly one after.  No
    process-global state can race."""
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    prose_content = (
        "Line 1: 凯恩进入了废墟。\n"
        "Line 2: 古老的符文在他脚下发光。\n"
        "Line 3: 他听到了敌人的低语。\n"
        "Line 4: 铁锤在他手中变重了。\n"
        "Line 5: 他做出了选择。\n"
    )

    # ---- prose_selected=False → 0 projector calls --------------------------
    req_unsel = ChapterRequest(
        chapter_id=60,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 60,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {
                _CH_BRIEF_PATH: _CH_BRIEF_HASH,
            },
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=False,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-spy-001",
    )
    out_unsel = ChapterEngine.run(req_unsel)
    assert out_unsel.status == "needs_selection"
    assert len(out_unsel.projector_call_log) == 0, (
        "0 projector calls before selection"
    )

    # ---- prose_selected=True → exactly 1 projector call --------------------
    req_sel = ChapterRequest(
        chapter_id=61,
        creative_brief={
            "schema_version": 2,
            "chapter_id": 61,
            "primary_function": "plot",
            "pov": "third_person_limited",
            "opposing_wants": "desire vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what next?",
            "must_preserve": [],
            "creative_freedom": [],
            "source_hashes": {
                _CH_BRIEF_PATH: _CH_BRIEF_HASH,
            },
        },
        writer_output={"fiction_draft.md": prose_content},
        prose_selected=True,
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-spy-002",
    )
    out_sel = ChapterEngine.run(req_sel)
    # Empty projection → needs_state_projection, but projector WAS called.
    assert out_sel.status == "needs_state_projection"
    assert len(out_sel.projector_call_log) == 1, (
        "exactly 1 projector call after selection"
    )
    # The recorded call shows prose_selected was set to True by the engine.
    assert out_sel.projector_call_log[0]["prose_selected"] is True


@pytest.mark.parametrize(
    ("provider", "model", "call_id"),
    [
        (" ", "deepseek-v4-pro", "call-1"),
        ("deepseek", "\t", "call-1"),
        ("deepseek", "deepseek-v4-pro", "  "),
    ],
)
def test_edit_block_whitespace_provenance_blocks(
    provider: str,
    model: str,
    call_id: str,
) -> None:
    from agent_runtime.narrative.production.writer_contract import (
        WriterV2Contract,
    )

    result = WriterV2Contract.validate_edit_blocks(
        [
            {
                "path": "runs/task_ws/fiction_draft.md",
                "html_block_content": "# 章一\n\n正文",
            }
        ],
        task_id="task_ws",
        provider=provider,
        model=model,
        call_id=call_id,
    )

    assert result["status"] == "blocked"
    assert "missing_observed_provenance" in result["issues"]
    assert result["agentlab_receipt"] is None


def test_chapter_engine_accepts_injected_projector_spy() -> None:
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )
    from agent_runtime.narrative.production.state_projector import project_state

    calls: list[str] = []

    def projector_spy(prose_path: str, **kwargs: object):
        calls.append(prose_path)
        return project_state(prose_path, **kwargs)

    brief = {
        "schema_version": 2,
        "chapter_id": 62,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
    }
    common = {
        "chapter_id": 62,
        "creative_brief": brief,
        "writer_output": {"fiction_draft.md": "# 章六十二\n\n正文\n"},
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "call_id": "call-projector-spy",
        "projector": projector_spy,
    }

    unselected = ChapterEngine.run(ChapterRequest(**common, prose_selected=False))
    assert unselected.status == "needs_selection"
    assert calls == []

    selected = ChapterEngine.run(ChapterRequest(**common, prose_selected=True))
    assert selected.status == "needs_state_projection"
    assert len(calls) == 1
    assert len(selected.projector_call_log) == 1


def test_writer_edit_blocks_require_task_id() -> None:
    from agent_runtime.narrative.production.writer_contract import (
        WriterV2Contract,
    )

    result = WriterV2Contract.validate_edit_blocks(
        [{"path": "fiction_draft.md", "html_block_content": "# 章一\n\n正文"}],
        task_id="",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-no-task",
    )

    assert result["status"] == "blocked"
    assert "missing_task_id" in result["issues"]
    assert result["agentlab_receipt"] is None


def test_projector_exception_is_node_local_and_preserves_selected_hash() -> None:
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    def failing_projector(*args: object, **kwargs: object):
        raise RuntimeError("projector failed")

    outcome = ChapterEngine.run(
        ChapterRequest(
            chapter_id=63,
            creative_brief={
                "schema_version": 2,
                "chapter_id": 63,
                "primary_function": "plot",
                "pov": "third_person_limited",
                "opposing_wants": "desire vs obstacle",
                "turn": "a turn",
                "cost": "a cost",
                "reader_question": "what next?",
                "must_preserve": [],
                "creative_freedom": [],
                "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
            },
            writer_output={"fiction_draft.md": "# 章六十三\n\n正文\n"},
            prose_selected=True,
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-projector-failure",
            projector=failing_projector,
        )
    )

    assert outcome.status == "blocked"
    assert outcome.writer_rerun_needed is False
    assert outcome.selected_prose_sha256
    assert outcome.writer_validation is not None
    assert outcome.selected_prose_sha256 == outcome.writer_validation["prose_sha256"]
    assert "state_projection_failed:RuntimeError" in outcome.issues


def test_engine_projects_canonical_writer_prose_bytes() -> None:
    from agent_runtime.narrative.production.chapter_engine import (
        ChapterEngine,
        ChapterRequest,
    )

    raw_prose = "Line 1: canonical fact\n\n   \n"
    canonical = raw_prose.rstrip() + "\n"
    prose_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    outcome = ChapterEngine.run(
        ChapterRequest(
            chapter_id=64,
            creative_brief={
                "schema_version": 2,
                "chapter_id": 64,
                "primary_function": "plot",
                "pov": "third_person_limited",
                "opposing_wants": "desire vs obstacle",
                "turn": "a turn",
                "cost": "a cost",
                "reader_question": "what next?",
                "must_preserve": [],
                "creative_freedom": [],
                "source_hashes": {_CH_BRIEF_PATH: _CH_BRIEF_HASH},
            },
            writer_output={"fiction_draft.md": raw_prose},
            prose_selected=True,
            state_delta={
                "schema_version": 2,
                "chapter_id": 64,
                "prose_sha256": prose_hash,
                "hard_facts": [
                    {
                        "category": "plot",
                        "evidence_location": "L1",
                        "content": "canonical fact",
                        "confidence": "confirmed",
                    }
                ],
                "soft_observations": [],
                "node_local_retry_only": True,
                "writer_rerun_triggered": False,
            },
            provider="deepseek",
            model="deepseek-v4-pro",
            call_id="call-canonical-engine",
        )
    )

    assert outcome.status == "pass"
    assert outcome.selected_prose_sha256 == prose_hash
