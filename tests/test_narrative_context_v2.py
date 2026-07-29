from __future__ import annotations

from pathlib import Path
import hashlib

import yaml
from typer.testing import CliRunner

from agent_runtime.narrative.authorial_audit import (
    build_authorial_audit_plan,
    compile_senior_editor_revision_contracts,
    execute_authorial_reviews,
    validate_authorial_review_finding,
)
from agent_runtime.narrative.author_team import build_author_team_manifests
from agent_runtime.narrative.author_team import load_author_team_contract
from agent_runtime.narrative.craft_cards import validate_craft_card
from agent_runtime.narrative.efficiency.context_bundle import (
    build_context_bundle,
)
from agent_runtime.narrative.production.live_revision import (
    revision_contract_issues,
)
from agent_runtime.narrative.role_context import compile_role_context_pack
from agent_runtime.narrative.outbound_transfer import (
    build_narrative_outbound_transfer_contract,
)
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.run_task import app

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "Test_Novel"
TASK_ID = "task_context_v2"


def _context_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    agentlab = tmp_path / "AgentLab"
    (agentlab / "agent_runtime").mkdir(parents=True)
    (agentlab / "agentlab.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    config = agentlab / "config"
    config.mkdir()
    for name in (
        "narrative_author_team.yml",
        "agent_registry.yml",
        "agent_model_profiles.yml",
    ):
        (config / name).write_bytes((ROOT / "config" / name).read_bytes())
    project = agentlab / "projects" / PROJECT
    (project / "production").mkdir(parents=True)
    artifacts = project / "runs" / TASK_ID / "artifacts"
    artifacts.mkdir(parents=True)
    bundle_result = build_context_bundle(
        artifacts / "context_bundles",
        source_root=project,
        canon_snapshot_sha256="test-canon",
        chapter_window=[1],
        shared_files=[],
        role_specific_files={},
    )
    bundle = Path(str(bundle_result["manifest_path"]))
    return agentlab, project, bundle


def _context_bundle(project: Path, sources: list[Path]) -> Path:
    result = build_context_bundle(
        project / "runs" / TASK_ID / "artifacts" / "context_bundles",
        source_root=project,
        canon_snapshot_sha256="test-canon",
        chapter_window=[1],
        shared_files=sources,
        role_specific_files={},
    )
    return Path(str(result["manifest_path"]))


def _register_context_author_team(agentlab: Path, project: Path) -> None:
    (project / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": PROJECT,
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            }
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project)
    pointer = truth.initialize(PROJECT)
    contract = load_author_team_contract(agentlab)
    contract["project_id"] = PROJECT
    ProjectAgentRegistry(truth).register_many(
        build_author_team_manifests(contract),
        expected_snapshot_id=pointer.current_snapshot_id,
        actor_id="test",
        source="user",
        approved=True,
    )


def _review_context_packs(
    project: Path,
    *,
    reviewer_roles: list[str],
    evidence_value: str = "grounded",
) -> dict[str, Path]:
    namespaces_by_role = {
        "canon_timeline_steward": [
            "canon",
            "timeline",
            "character_knowledge",
        ],
        "relationship_director": ["relationship_graph"],
        "reader_simulation_panel": ["reader_questions"],
    }
    evidence_by_role: dict[str, list[dict]] = {}
    role_files: dict[str, list[Path]] = {}
    for role_id in reviewer_roles:
        namespaces = namespaces_by_role[role_id]
        candidates = []
        role_files[role_id] = []
        for namespace in namespaces:
            evidence = (
                project / "production" / f"review-{namespace}.yml"
            )
            content = f"{namespace}: {evidence_value}\n"
            evidence.write_text(content, encoding="utf-8")
            role_files[role_id].append(evidence)
            candidates.append(
                {
                    "path": evidence,
                    "namespace": namespace,
                    "retrieval_stage": "hard_fact",
                    "score": 1.0,
                    "required": True,
                }
            )
        evidence_by_role[role_id] = candidates
    bundle_result = build_context_bundle(
        project
        / "runs"
        / TASK_ID
        / "artifacts"
        / "context_bundles",
        source_root=project,
        canon_snapshot_sha256="review-canon-snapshot",
        chapter_window=[1],
        shared_files=[],
        role_specific_files=role_files,
    )
    candidate = (
        project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
    )
    result = {}
    for role_id in reviewer_roles:
        compiled = compile_role_context_pack(
            project.parents[1],
            project=PROJECT,
            task_id=TASK_ID,
            role_id=role_id,
            context_bundle_manifest=Path(
                str(bundle_result["manifest_path"])
            ),
            evidence_candidates=evidence_by_role[role_id],
            token_budget=1000,
            minimum_evidence_items=1,
            audit_chapter_id=1,
            audit_candidate_path=candidate,
        )
        assert compiled["status"] == "pass", compiled
        result[role_id] = Path(str(compiled["pack_path"]))
    return result


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


def test_narrative_external_transfer_requires_exact_expiring_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    source = project / "production" / "canon.yml"
    source.write_text("fact: true\n", encoding="utf-8")
    fragment = "One minimal Crown fact."
    payload_sha256 = hashlib.sha256(fragment.encode("utf-8")).hexdigest()

    pending = build_narrative_outbound_transfer_contract(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        recipient="example-provider",
        purpose="Check one causal interpretation.",
        minimal_fragment=fragment,
        source_paths=[source],
        expires_at="2999-01-01T00:00:00Z",
    )
    monkeypatch.setenv("AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED", "1")
    monkeypatch.setenv(
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_PAYLOAD_SHA256",
        payload_sha256,
    )
    monkeypatch.setenv(
        "AGENTLAB_ROLE_SESSION_ACCEPTANCE_SCOPE_SHA256",
        pending["request_scope"]["sha256"],
    )
    approved = build_narrative_outbound_transfer_contract(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        recipient="example-provider",
        purpose="Check one causal interpretation.",
        minimal_fragment=fragment,
        source_paths=[source],
        expires_at="2999-01-01T00:00:00Z",
    )

    assert pending["status"] == "pending_approval"
    assert pending["execution_allowed"] is False
    assert approved["status"] == "pass"
    assert approved["execution_allowed"] is True
    assert approved["recipient"] == "example-provider"
    assert approved["purpose"] == "Check one causal interpretation."
    assert approved["minimal_fragment"] == {
        "bytes": len(fragment.encode("utf-8")),
        "sha256": payload_sha256,
        "content_stored_in_contract": False,
    }
    assert approved["expires_at"] == "2999-01-01T00:00:00Z"
    changed_scope = build_narrative_outbound_transfer_contract(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        recipient="different-provider",
        purpose="Check one causal interpretation.",
        minimal_fragment=fragment,
        source_paths=[source],
        expires_at="2999-01-01T00:00:00Z",
    )
    assert changed_scope["status"] == "blocked"
    assert changed_scope["execution_allowed"] is False
    assert "approved_private_context_scope_sha256_mismatch" in changed_scope[
        "issues"
    ]


def test_role_context_pack_is_namespace_scoped_budgeted_and_hash_bound(
    tmp_path: Path,
) -> None:
    agentlab, project, bundle = _context_project(tmp_path)
    evidence = []
    for name, namespace, stage in (
        ("canon.yml", "canon", "hard_fact"),
        ("timeline.yml", "timeline", "graph_adjacent"),
        ("names.yml", "exact_name_index", "semantic"),
        ("knowledge.yml", "character_knowledge", "reflective"),
    ):
        path = project / "production" / name
        path.write_text("12345678", encoding="utf-8")
        evidence.append(
            {
                "path": path,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": 1.0,
            }
        )
    bundle = _context_bundle(
        project,
        [Path(str(item["path"])) for item in evidence],
    )

    first = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="canon_timeline_steward",
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
    )
    second = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="canon_timeline_steward",
        context_bundle_manifest=bundle,
        evidence_candidates=evidence,
        token_budget=5,
        minimum_evidence_items=3,
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
            "path": "production/names.yml",
            "namespace": "exact_name_index",
            "retrieval_stage": "semantic",
            "reason": "token_budget_exceeded",
        },
        {
            "path": "production/knowledge.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "token_budget_exceeded",
        },
    ]
    assert first["token_usage"]["used"] == 4
    assert len(first["pack_sha256"]) == 64
    assert first["selected_evidence"][0]["content"] == "12345678"
    assert first["retrieval_execution"]["compiler_performs_retrieval"] is False
    assert Path(first["pack_path"]).parent == (
        project / "runs" / TASK_ID / "artifacts" / "role_context"
    )


def test_role_context_pack_blocks_cross_role_namespace_leak(
    tmp_path: Path,
) -> None:
    agentlab, project, bundle = _context_project(tmp_path)
    private_memory = project / "project_brain" / "private_memory.yml"
    private_memory.parent.mkdir()
    private_memory.write_text("secret: true\n", encoding="utf-8")
    bundle = _context_bundle(project, [private_memory])

    result = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="writer",
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
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        "namespace_not_allowed:writer:character_private_memory"
    ]
    assert not (
        project / "runs" / TASK_ID / "artifacts" / "role_context"
    ).exists()


def test_role_context_pack_cannot_use_another_roles_bundle_inventory(
    tmp_path: Path,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    other_role_file = project / "production" / "relationship-private.yml"
    other_role_file.write_text("private: true\n", encoding="utf-8")
    result = build_context_bundle(
        project / "runs" / TASK_ID / "artifacts" / "context_bundles",
        source_root=project,
        canon_snapshot_sha256="test-canon",
        chapter_window=[1],
        shared_files=[],
        role_specific_files={
            "relationship_director": [other_role_file],
        },
    )

    compiled = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="writer",
        context_bundle_manifest=Path(str(result["manifest_path"])),
        evidence_candidates=[
            {
                "path": other_role_file,
                "namespace": "writer_context_pack",
                "retrieval_stage": "hard_fact",
            }
        ],
        token_budget=100,
        minimum_evidence_items=1,
    )

    assert compiled["status"] == "blocked"
    assert compiled["issues"] == [
        "evidence_not_bound_by_context_bundle:"
        "production/relationship-private.yml"
    ]


def test_role_context_pack_rejects_noncanonical_run_evidence(
    tmp_path: Path,
) -> None:
    agentlab, project, bundle = _context_project(tmp_path)
    forged = project / "runs" / TASK_ID / "artifacts" / "forged-canon.yml"
    forged.write_text("canon: false\n", encoding="utf-8")
    bundle = _context_bundle(project, [forged])

    result = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="canon_timeline_steward",
        context_bundle_manifest=bundle,
        evidence_candidates=[
            {
                "path": forged,
                "namespace": "canon",
                "retrieval_stage": "hard_fact",
            }
        ],
        token_budget=100,
        minimum_evidence_items=1,
    )

    assert result["status"] == "blocked"
    assert result["issues"] == [
        f"evidence_not_canonical:runs/{TASK_ID}/artifacts/forged-canon.yml"
    ]


def test_role_context_pack_rejects_symlinked_artifacts_output(
    tmp_path: Path,
) -> None:
    agentlab = tmp_path / "AgentLab"
    (agentlab / "config").mkdir(parents=True)
    for name in (
        "narrative_author_team.yml",
        "agent_registry.yml",
        "agent_model_profiles.yml",
    ):
        (agentlab / "config" / name).write_bytes(
            (ROOT / "config" / name).read_bytes()
        )
    project = agentlab / "projects" / PROJECT
    (project / "production").mkdir(parents=True)
    run = project / "runs" / TASK_ID
    run.mkdir(parents=True)
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    (run / "artifacts").symlink_to(outside, target_is_directory=True)
    bundle = outside / "context_bundle.yml"
    bundle.write_text(
        "schema_version: 1\ncontext_bundle_id: ctx-unsafe\n",
        encoding="utf-8",
    )

    result = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="writer",
        context_bundle_manifest=bundle,
        evidence_candidates=[],
        token_budget=100,
        minimum_evidence_items=0,
    )

    assert result == {
        "schema_version": "role-context-pack-result/v1",
        "status": "blocked",
        "issues": ["run_artifacts_symlink_or_escape_forbidden"],
    }


def test_role_context_pack_rejects_unlicensed_craft_card_payload(
    tmp_path: Path,
) -> None:
    agentlab, project, bundle = _context_project(tmp_path)
    craft_card = project / "project_brain" / "craft_card.yml"
    craft_card.parent.mkdir()
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
    bundle = _context_bundle(project, [craft_card])

    result = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="research_style_curator",
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
    agentlab, project, bundle = _context_project(tmp_path)
    hard_fact = project / "production" / "canon.yml"
    reflection = project / "production" / "reflection.yml"
    hard_fact.write_text("fact", encoding="utf-8")
    reflection.write_text("reflection", encoding="utf-8")
    bundle = _context_bundle(project, [hard_fact, reflection])

    result = compile_role_context_pack(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        role_id="canon_timeline_steward",
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
    )

    assert [item["path"] for item in result["selected_evidence"]] == [
        "production/canon.yml"
    ]
    assert result["omitted_evidence"] == [
        {
            "path": "production/reflection.yml",
            "namespace": "character_knowledge",
            "retrieval_stage": "reflective",
            "reason": "reflective_retrieval_not_needed",
        }
    ]


def test_narrative_context_compile_cli_uses_request_contract(
    tmp_path: Path,
) -> None:
    agentlab, project, bundle = _context_project(tmp_path)
    canon = project / "production" / "canon.yml"
    canon.write_text("fact: true\n", encoding="utf-8")
    bundle = _context_bundle(project, [canon])
    request = tmp_path / "request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "role-context-compile-request/v1",
                "project": PROJECT,
                "task_id": TASK_ID,
                "role_id": "canon_timeline_steward",
                "context_bundle_manifest": bundle.relative_to(
                    project
                ).as_posix(),
                "evidence_candidates": [
                    {
                        "path": "production/canon.yml",
                        "namespace": "canon",
                        "retrieval_stage": "hard_fact",
                    }
                ],
                "token_budget": 100,
                "minimum_evidence_items": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "context", "compile", "--request", str(request)],
        env={"AGENTLAB_ROOT": str(agentlab)},
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "role-context-pack/v1"
    assert payload["status"] == "pass"
    assert Path(payload["pack_path"]).is_file()


def test_authorial_audit_plan_always_runs_hard_gates_and_risk_reviewers(
    tmp_path: Path,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    candidate = project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")

    plan = build_authorial_audit_plan(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
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
    assert plan["execution_bindings"]["revision_attempt_reservation"].endswith(
        "reserve_revision_attempt"
    )
    assert plan["execution_bindings"]["blind_ab_execution"].endswith(
        "run_literary_ab_review"
    )
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


def test_authorial_review_execution_uses_bound_project_agents_and_verified_outputs(
    tmp_path: Path,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    _register_context_author_team(agentlab, project)
    candidate = project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    context_packs = _review_context_packs(
        project,
        reviewer_roles=[
            "canon_timeline_steward",
            "relationship_director",
            "reader_simulation_panel",
        ],
    )
    created_items: list[dict] = []
    verified: list[tuple[str, str]] = []
    output_hashes: dict[tuple[str, str], str] = {}
    emit_hard_error = False

    class FakeRuntime:
        def __init__(self) -> None:
            self.task_exists = True

        def load_task(self, task_id: str) -> dict:
            if not self.task_exists:
                from agent_runtime.task_runtime_v2 import EntityNotFound

                raise EntityNotFound(task_id)
            return {"work_items": {item["work_item_id"]: item for item in created_items}}

        def create_task(self, **_kwargs) -> dict:
            self.task_exists = True
            return {"task": {"status": "ready"}, "work_items": {}}

        def create_work_items(
            self,
            _task_id: str,
            *,
            items: list[dict],
            **_kwargs,
        ) -> dict:
            created_items.extend(items)
            return {"work_items": {item["work_item_id"]: item for item in items}}

        def verify_attempt_execution_receipt(
            self,
            task_id: str,
            attempt_id: str,
        ) -> dict:
            verified.append((task_id, attempt_id))
            return {
                "ok": True,
                "output_sha256": output_hashes[(task_id, attempt_id)],
                "receipt_sha256": "f" * 64,
            }

    reviewer_roles = set(context_packs)
    active_context_packs = context_packs

    class FakeExecutor:
        def execute(
            self,
            *,
            task_id: str,
            work_item_id: str,
            attempt_id: str,
            source_paths: list[Path],
            external_context_request: dict,
            **_kwargs,
        ) -> dict:
            reviewer = next(
                role_id
                for role_id in reviewer_roles
                if work_item_id.endswith(role_id.replace("_", "-"))
            )
            assert source_paths == [candidate, active_context_packs[reviewer]]
            assert external_context_request["purpose"]
            assert external_context_request["minimal_fragment"]
            assert (
                external_context_request["expires_at"]
                == "2999-01-01T00:00:00Z"
            )
            output = {
                "schema_version": "authorial-review-output/v1",
                "status": "pass",
                "project": PROJECT,
                "task_id": TASK_ID,
                "chapter_id": 1,
                "reviewer_role": reviewer,
                "candidate_sha256": candidate_sha256,
                "findings": [],
            }
            if emit_hard_error and reviewer == "relationship_director":
                output["findings"] = [
                    {
                        "schema_version": "authorial-review-finding/v1",
                        "finding_id": "hard-relationship-001",
                        "reviewer_role": reviewer,
                        "chapter_id": 1,
                        "target_scene": "scene-1",
                        "classification": "hard_error",
                        "problem_type": "consent_boundary",
                        "evidence_locator": "chapter-001.md:L1",
                        "evidence": "The required exit right is absent.",
                        "confidence": 0.95,
                        "counterinterpretation": (
                            "The scene could be read as implied negotiation."
                        ),
                        "revision_target": "Restore an explicit exit right.",
                        "minimal_revision_scope": "scene",
                        "preserve_strengths": ["Keep the scene tension."],
                        "candidate_sha256": candidate_sha256,
                    }
                ]
            if reviewer == "canon_timeline_steward":
                output["hard_check_results"] = {
                    check: {
                        "status": "pass",
                        "evidence_locator": (
                            "production/review-canon.yml:L1"
                        ),
                    }
                    for check in (
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
                    )
                }
            else:
                output["dimensions_reviewed"] = {
                    "relationship_director": [
                        "relationship_progression",
                        "consent_and_agency",
                    ],
                    "reader_simulation_panel": [
                        "reader_promise",
                        "emotional_effect",
                        "position_bias_check",
                    ],
                }[reviewer]
            output_path = (
                project
                / "runtime"
                / "tasks"
                / task_id
                / "attempt_logs"
                / attempt_id
                / "output.md"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                yaml.safe_dump(output, sort_keys=False),
                encoding="utf-8",
            )
            output_hashes[(task_id, attempt_id)] = hashlib.sha256(
                output_path.read_bytes()
            ).hexdigest()
            return {
                "output_path": str(output_path),
                "receipt_path": str(output_path.with_name("attempt_receipt.yml")),
            }

    result = execute_authorial_reviews(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        chapter_id=1,
        candidate_path=candidate,
        risk_flags=["relationship_progression"],
        context_pack_paths=context_packs,
        outbound_expires_at="2999-01-01T00:00:00Z",
        task_runtime=FakeRuntime(),
        attempt_executor=FakeExecutor(),
    )

    assert result["status"] == "pass"
    assert result["hard_gate_status"] == "pass"
    assert [item["reviewer_role"] for item in result["executions"]] == [
        "canon_timeline_steward",
        "relationship_director",
        "reader_simulation_panel",
    ]
    assert len(created_items) == 3
    assert all(
        item["assigned_agent_id"] in reviewer_roles
        for item in created_items
    )
    assert len(verified) == 3

    first_work_item_ids = {
        item["work_item_id"] for item in created_items
    }
    active_context_packs = _review_context_packs(
        project,
        reviewer_roles=sorted(reviewer_roles),
        evidence_value="revised",
    )
    repeated = execute_authorial_reviews(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        chapter_id=1,
        candidate_path=candidate,
        risk_flags=["relationship_progression"],
        context_pack_paths=active_context_packs,
        outbound_expires_at="2999-01-01T00:00:00Z",
        task_runtime=FakeRuntime(),
        attempt_executor=FakeExecutor(),
    )
    second_work_item_ids = {
        item["work_item_id"] for item in created_items
    } - first_work_item_ids

    assert repeated["status"] == "pass"
    assert repeated["execution_sha256"] != result["execution_sha256"]
    assert len(second_work_item_ids) == 3
    assert first_work_item_ids.isdisjoint(second_work_item_ids)

    active_context_packs = _review_context_packs(
        project,
        reviewer_roles=sorted(reviewer_roles),
        evidence_value="hard-error-review",
    )
    emit_hard_error = True
    blocked = execute_authorial_reviews(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        chapter_id=1,
        candidate_path=candidate,
        risk_flags=["relationship_progression"],
        context_pack_paths=active_context_packs,
        outbound_expires_at="2999-01-01T00:00:00Z",
        task_runtime=FakeRuntime(),
        attempt_executor=FakeExecutor(),
    )

    assert blocked["status"] == "blocked"
    assert blocked["hard_gate_status"] == "blocked"
    assert blocked["issues"] == ["hard_authorial_audit_failed"]


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
    agentlab, project, _ = _context_project(tmp_path)
    candidate = project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
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
        agentlab_root=agentlab,
        project=PROJECT,
        task_id=TASK_ID,
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
    agentlab, project, _ = _context_project(tmp_path)
    candidate = project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")
    request = tmp_path / "audit-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "authorial-audit-request/v1",
                "action": "plan",
                "project": PROJECT,
                "task_id": TASK_ID,
                "chapter_id": 1,
                "candidate_path": (
                    f"runs/{TASK_ID}/artifacts/chapter-001.md"
                ),
                "risk_flags": ["foreshadow_payoff"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "audit", "--request", str(request)],
        env={"AGENTLAB_ROOT": str(agentlab)},
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


def test_narrative_audit_cli_executes_professional_review_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    candidate = project / "runs" / TASK_ID / "artifacts" / "chapter-001.md"
    candidate.write_text("Candidate prose.", encoding="utf-8")
    context_packs = _review_context_packs(
        project,
        reviewer_roles=[
            "canon_timeline_steward",
            "relationship_director",
            "reader_simulation_panel",
        ],
    )
    request = tmp_path / "audit-review-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "authorial-audit-request/v1",
                "action": "execute_reviews",
                "project": PROJECT,
                "task_id": TASK_ID,
                "chapter_id": 1,
                "candidate_path": (
                    f"runs/{TASK_ID}/artifacts/chapter-001.md"
                ),
                "risk_flags": ["relationship_progression"],
                "outbound_expires_at": "2999-01-01T00:00:00Z",
                "context_pack_paths": {
                    role_id: path.relative_to(project).as_posix()
                    for role_id, path in context_packs.items()
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_execute(root: Path, **kwargs) -> dict:
        calls.append((root, kwargs))
        return {
            "schema_version": "authorial-review-execution/v1",
            "status": "pass",
            "hard_gate_status": "pass",
            "executions": [],
            "issues": [],
        }

    monkeypatch.setattr(
        "agent_runtime.cli.narrative.execute_authorial_reviews",
        fake_execute,
    )
    result = CliRunner().invoke(
        app,
        ["narrative", "audit", "--request", str(request)],
        env={"AGENTLAB_ROOT": str(agentlab)},
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "authorial-review-execution/v1"
    assert calls[0][1]["project"] == PROJECT
    assert calls[0][1]["task_id"] == TASK_ID
    assert calls[0][1]["candidate_path"] == candidate
    assert calls[0][1]["risk_flags"] == ["relationship_progression"]
    assert calls[0][1]["context_pack_paths"] == context_packs


def test_narrative_audit_cli_executes_existing_blind_ab_state_machine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    spec = project / "runs" / TASK_ID / "artifacts" / "blind-ab-spec.yml"
    spec.write_text("schema_version: 1\n", encoding="utf-8")
    request = tmp_path / "audit-execute-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "schema_version": "authorial-audit-request/v1",
                "action": "execute_blind_ab",
                "project": PROJECT,
                "task_id": TASK_ID,
                "spec_path": (
                    f"runs/{TASK_ID}/artifacts/blind-ab-spec.yml"
                ),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_preflight(spec_path: Path, *, repository_root: Path) -> dict:
        calls.append(("preflight", spec_path, repository_root))
        return {
            "status": "ready",
            "project": PROJECT,
            "task_id": TASK_ID,
        }

    def fake_review(root: Path, *, project: str, task_id: str) -> dict:
        calls.append(("review", root, project, task_id))
        return {"status": "pass", "selection_applied": False}

    monkeypatch.setattr(
        "agent_runtime.cli.narrative.preflight_literary_ab_review",
        fake_preflight,
    )
    monkeypatch.setattr(
        "agent_runtime.cli.narrative.run_literary_ab_review",
        fake_review,
    )

    result = CliRunner().invoke(
        app,
        ["narrative", "audit", "--request", str(request)],
        env={"AGENTLAB_ROOT": str(agentlab)},
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)
    assert payload["schema_version"] == "authorial-blind-ab-execution/v1"
    assert payload["status"] == "pass"
    assert payload["review"]["selection_applied"] is False
    assert [item[0] for item in calls] == ["preflight", "review"]


def test_authorial_audit_rejects_candidate_outside_run_artifacts(
    tmp_path: Path,
) -> None:
    agentlab, project, _ = _context_project(tmp_path)
    candidate = project / "production" / "chapter-001.md"
    candidate.write_text("Unaccepted prose.", encoding="utf-8")

    result = build_authorial_audit_plan(
        agentlab,
        project=PROJECT,
        task_id=TASK_ID,
        chapter_id=1,
        candidate_path=candidate,
        risk_flags=[],
    )

    assert result == {
        "status": "blocked",
        "issues": ["candidate_not_run_artifact"],
    }
