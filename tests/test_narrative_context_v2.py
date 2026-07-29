from __future__ import annotations

from pathlib import Path
import hashlib

import yaml
from typer.testing import CliRunner

from agent_runtime.narrative.authorial_audit import (
    build_authorial_audit_plan,
    compile_senior_editor_revision_contracts,
    validate_authorial_review_finding,
)
from agent_runtime.narrative.craft_cards import validate_craft_card
from agent_runtime.narrative.production.live_revision import (
    revision_contract_issues,
)
from agent_runtime.narrative.role_context import compile_role_context_pack
from agent_runtime.run_task import app

ROOT = Path(__file__).resolve().parents[1]


def test_craft_card_accepts_traceable_technique_and_rejects_source_text() -> None:
    valid = {
        "device": "Delay an answer through a materially costly interruption.",
        "preconditions": ["The reader already understands the open question."],
        "mechanism": "Interrupt the answer with a consequence-bearing choice.",
        "reader_effect": "Sustained tension without erasing forward motion.",
        "failure_modes": ["The interruption feels unrelated or consequence-free."],
        "applicable_scenes": ["interrogation", "negotiation"],
        "originality_constraints": [
            "Rebuild the device from Crown-specific motives and causality."
        ],
        "source_rights": "criticism_research",
        "source_locator": "Example Essay, section 3",
    }

    assert validate_craft_card(valid) == []

    copied = {
        **valid,
        "source_rights": "unlicensed_contemporary_fiction",
        "source_text": "A copied passage.",
    }
    assert validate_craft_card(copied) == [
        "source_rights_not_allowed:unlicensed_contemporary_fiction",
        "source_text_storage_forbidden:source_text",
    ]


def test_role_context_pack_is_namespace_scoped_budgeted_and_hash_bound(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "context_bundle_id": "ctx-test",
                "shared_files": [],
                "role_specific_files": {},
            }
        ),
        encoding="utf-8",
    )
    evidence = []
    for name, namespace, stage in (
        ("canon.yml", "canon", "hard_fact"),
        ("timeline.yml", "timeline", "graph_adjacent"),
        ("names.yml", "exact_name_index", "semantic"),
        ("knowledge.yml", "character_knowledge", "reflective"),
    ):
        path = source_root / name
        path.write_text("12345678", encoding="utf-8")
        evidence.append(
            {
                "path": path,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": 1.0,
            }
        )

    first = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
        output_dir=source_root / "role_context",
    )
    second = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
        output_dir=source_root / "role_context",
    )

    assert first["status"] == "pass"
    assert second["status"] == "current"
    assert first["retrieval_order"] == [
        "hard_fact",
        "graph_adjacent",
        "semantic",
        "reflective",
    ]
    assert [item["retrieval_stage"] for item in first["selected_evidence"]] == [
        "hard_fact",
        "graph_adjacent",
    ]
    assert first["omitted_evidence"] == [
        {
            "path": "names.yml",
            "namespace": "exact_name_index",
            "retrieval_stage": "semantic",
            "reason": "token_budget_exceeded",
        },
        {
            "path": "knowledge.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "token_budget_exceeded",
        },
    ]
    assert first["token_usage"]["used"] == 4
    assert len(first["pack_sha256"]) == 64


def test_role_context_pack_blocks_cross_role_namespace_leak(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    private_memory = source_root / "private_memory.yml"
    private_memory.write_text("secret: true\n", encoding="utf-8")

    result = compile_role_context_pack(
        ROOT,
        role_id="writer",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": private_memory,
                "namespace": "character_private_memory",
                "retrieval_stage": "hard_fact",
            }
        ],
        token_budget=100,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        "namespace_not_allowed:writer:character_private_memory"
    ]
    assert not (source_root / "role_context").exists()


def test_role_context_pack_rejects_unlicensed_craft_card_payload(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    craft_card = source_root / "craft_card.yml"
    craft_card.write_text(
        yaml.safe_dump(
            {
                "device": "Borrowed mannerism",
                "preconditions": ["A source novel exists."],
                "mechanism": "Copy it.",
                "reader_effect": "Imitation.",
                "failure_modes": ["Copyright violation."],
                "applicable_scenes": ["all"],
                "originality_constraints": ["none"],
                "source_rights": "unlicensed_contemporary_fiction",
                "source_locator": "Novel, chapter 4",
                "source_text": "Copied prose.",
            }
        ),
        encoding="utf-8",
    )

    result = compile_role_context_pack(
        ROOT,
        role_id="research_style_curator",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": craft_card,
                "namespace": "craft_cards",
                "retrieval_stage": "semantic",
            }
        ],
        token_budget=1000,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        (
            f"craft_card_invalid:{craft_card}:0:"
            "source_rights_not_allowed:unlicensed_contemporary_fiction"
        ),
        f"craft_card_invalid:{craft_card}:0:source_text_storage_forbidden:source_text",
    ]


def test_reflective_retrieval_is_skipped_when_prior_evidence_is_sufficient(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-test\n",
        encoding="utf-8",
    )
    hard_fact = source_root / "canon.yml"
    reflection = source_root / "reflection.yml"
    hard_fact.write_text("fact", encoding="utf-8")
    reflection.write_text("reflection", encoding="utf-8")

    result = compile_role_context_pack(
        ROOT,
        role_id="canon_timeline_steward",
        source_root=source_root,
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": reflection,
                "namespace": "character_knowledge",
                "retrieval_stage": "reflective",
            },
            {
                "path": hard_fact,
                "namespace": "canon",
                "retrieval_stage": "hard_fact",
            },
        ],
        token_budget=100,
        minimum_evidence_items=1,
        output_dir=source_root / "role_context",
    )

    assert [item["path"] for item in result["selected_evidence"]] == ["canon.yml"]
    assert result["omitted_evidence"] == [
        {
            "path": "reflection.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "reflective_retrieval_not_needed",
        }
    ]


def test_narrative_context_compile_cli_uses_request_contract(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    source_root.mkdir()
    bundle = source_root / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-cli\n",
        encoding="utf-8",
    )
    canon = source_root / "canon.yml"
    canon.write_text("fact: true\n", encoding="utf-8")
    request = tmp_path / "request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "role-context-compile-request/v1",
                "role_id": "canon_timeline_steward",
                "source_root": str(source_root),
                "context_bundle_manifest": "context_bundle.yml",
                "evidence_candidates": [
                    {
                        "path": "canon.yml",
                        "namespace": "canon",
                        "retrieval_stage": "hard_fact",
                    }
                ],
                "token_budget": 100,
                "minimum_evidence_items": 1,
                "output_dir": "role_context",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "context", "compile", "--request", str(request)],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "role-context-pack/v1"
    assert payload["status"] == "pass"
    assert Path(payload["pack_path"]).is_file()


def test_authorial_audit_plan_always_runs_hard_gates_and_risk_reviewers(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")

    plan = build_authorial_audit_plan(
        ROOT,
        chapter_id=1,
        candidate_path=candidate,
        risk_flags=["relationship_progression"],
    )

    assert plan["status"] == "pass"
    assert plan["candidate"]["sha256"]
    assert plan["hard_audit"]["reviewer_role"] == "canon_timeline_steward"
    assert plan["revision_attempt_limit"] == 2
    assert plan["escalation_role"] == "authorial_director"
    assert plan["blind_review"] == {
        "required_after_revision": True,
        "anonymous": True,
        "order": "hash_randomized",
        "reviewer_role": "reader_simulation_panel",
    }
    assert set(plan["hard_audit"]["checks"]) == {
        "timeline",
        "age",
        "life_status",
        "location",
        "item",
        "ability_source",
        "character_knowledge_boundary",
        "canon_source_hash",
        "adult_consent_exit_right",
        "promise_payoff_state",
        "state_commit_idempotency",
    }
    assert plan["soft_reviews"] == [
        {
            "reviewer_role": "relationship_director",
            "dimensions": ["relationship_progression", "consent_and_agency"],
        },
        {
            "reviewer_role": "reader_simulation_panel",
            "dimensions": ["reader_promise", "emotional_effect", "position_bias_check"],
        },
    ]


def test_authorial_review_finding_requires_evidence_and_counterinterpretation() -> None:
    finding = {
        "schema_version": "authorial-review-finding/v1",
        "finding_id": "finding-relationship-001",
        "reviewer_role": "relationship_director",
        "chapter_id": 1,
        "target_scene": "scene-2",
        "classification": "aesthetic_disagreement",
        "problem_type": "unearned_trust",
        "evidence_locator": "chapter-001.md:L42",
        "evidence": "Trust rises without an intervening costly choice.",
        "confidence": 0.82,
        "counterinterpretation": (
            "Shared danger could explain a temporary tactical alignment."
        ),
        "revision_target": "Add one bounded action that earns limited trust.",
        "minimal_revision_scope": "scene",
        "preserve_strengths": ["Keep the scene's brisk threat escalation."],
        "candidate_sha256": "a" * 64,
    }

    assert validate_authorial_review_finding(finding) == []

    incomplete = dict(finding)
    incomplete["reviewer_role"] = "writer"
    incomplete["counterinterpretation"] = ""
    incomplete["preserve_strengths"] = []
    assert validate_authorial_review_finding(incomplete) == [
        "reviewer_role_not_allowed:writer",
        "counterinterpretation_required",
        "preserve_strengths_required",
    ]


def test_senior_editor_merges_reviewers_into_hash_bound_scene_contract(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    base = {
        "schema_version": "authorial-review-finding/v1",
        "chapter_id": 1,
        "target_scene": "scene-2",
        "classification": "aesthetic_disagreement",
        "evidence_locator": "chapter-001.md:L42",
        "confidence": 0.82,
        "counterinterpretation": "The current reading has a plausible defense.",
        "minimal_revision_scope": "scene",
        "candidate_sha256": candidate_sha256,
    }
    findings = [
        {
            **base,
            "finding_id": "finding-relationship-001",
            "reviewer_role": "relationship_director",
            "problem_type": "unearned_trust",
            "evidence": "Trust rises without an intervening costly choice.",
            "revision_target": "Earn limited trust through one costly action.",
            "preserve_strengths": ["Keep the brisk threat escalation."],
        },
        {
            **base,
            "finding_id": "finding-reader-001",
            "reviewer_role": "reader_simulation_panel",
            "problem_type": "promise_clarity",
            "evidence": "The reader cannot tell which promise changed.",
            "revision_target": "Clarify the changed promise without explaining it.",
            "preserve_strengths": ["Keep the final image ambiguous."],
        },
    ]

    result = compile_senior_editor_revision_contracts(
        findings,
        candidate_path=candidate,
        constraints={
            "must_preserve": ["Do not change the scene outcome."],
            "allowed_freedom": "Local action, staging, and sentence-level choices.",
            "causal_requirements": ["The costly action must precede the trust delta."],
            "character_knowledge_before": ["A suspects B."],
            "character_knowledge_after": ["A trusts B only tactically."],
            "decision_cost": "A exposes one weakness.",
            "new_information": "B chooses not to exploit the weakness.",
            "forbidden_regressions": ["Do not convert suspicion into intimacy."],
        },
    )

    assert result["status"] == "pass"
    assert result["candidate"]["sha256"] == candidate_sha256
    assert len(result["contracts"]) == 1
    contract = result["contracts"][0]
    assert contract["compiled_by"] == "senior_editor"
    assert contract["rewrite_scope"] == "scene"
    assert contract["must_change"] == [
        "Earn limited trust through one costly action.",
        "Clarify the changed promise without explaining it.",
    ]
    assert contract["must_preserve"] == [
        "Do not change the scene outcome.",
        "Keep the brisk threat escalation.",
        "Keep the final image ambiguous.",
    ]
    assert [item["reviewer_role"] for item in contract["review_evidence"]] == [
        "relationship_director",
        "reader_simulation_panel",
    ]
    assert (
        revision_contract_issues(
            contract,
            chapter_id=1,
            source_candidate_sha256=candidate_sha256,
            triggering_audit_sha256=result["triggering_audit_sha256"],
        )
        == []
    )


def test_narrative_audit_cli_builds_hash_bound_plan(tmp_path: Path) -> None:
    candidate = tmp_path / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")
    request = tmp_path / "audit-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "authorial-audit-request/v1",
                "action": "plan",
                "chapter_id": 1,
                "candidate_path": str(candidate),
                "risk_flags": ["foreshadow_payoff"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "audit", "--request", str(request)],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "authorial-audit-plan/v1"
    assert payload["status"] == "pass"
    assert payload["hard_audit"]["checks"]
    assert [item["reviewer_role"] for item in payload["soft_reviews"]] == [
        "foreshadow_mystery_keeper",
        "reader_simulation_panel",
    ]
