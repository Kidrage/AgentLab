from __future__ import annotations

from pathlib import Path
import hashlib

import pytest
import yaml

from agent_runtime.narrative.acceptance_ladder import (
    build_narrative_acceptance_status,
)
from agent_runtime.narrative.author_team import REQUIRED_AUTHOR_ROLES
from agent_runtime.narrative.metric_universe import (
    project_metric_universe,
)
from agent_runtime.narrative.candidates.manifest import (
    create_candidate_set,
    freeze_candidate_set,
)
from agent_runtime.narrative.candidates.promotion import (
    evidence_bundle_sha256 as compute_evidence_bundle_sha256,
)
from agent_runtime.narrative.state_stress import (
    run_pseudoprose_state_stress,
)
from narrative_acceptance_support import (
    record_signed_candidate_acceptance,
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "Crown_of_Ash"


def _write_yaml(path: Path, value: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return {
        "path": path.name if path.parent.name == "Crown_of_Ash" else (
            path.relative_to(path.parents[2]).as_posix()
        ),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _binding(project_root: Path, path: Path, **extra: str) -> dict:
    return {
        "path": path.relative_to(project_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **extra,
    }


def _test_agentlab_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentlab"
    config = root / "config" / "narrative_acceptance_ladder.yml"
    config.parent.mkdir(parents=True)
    config.write_bytes(
        (ROOT / "config" / "narrative_acceptance_ladder.yml").read_bytes()
    )
    return root


def test_state_stress_refuses_symlinked_output_ancestor(
    tmp_path: Path,
) -> None:
    agentlab_root = tmp_path / "agentlab"
    project_root = agentlab_root / "projects" / PROJECT
    project_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_root / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="ancestor is a symlink"):
        run_pseudoprose_state_stress(
            agentlab_root,
            project=PROJECT,
            task_id="task_p5_stress",
            chapter_count=100,
        )
    assert list(outside.iterdir()) == []


def test_acceptance_ladder_fails_closed_without_stage_evidence(
    tmp_path: Path,
) -> None:
    agentlab_root = _test_agentlab_root(tmp_path)
    project_root = agentlab_root / "projects" / "Crown_of_Ash"
    project_root.mkdir(parents=True)

    result = build_narrative_acceptance_status(
        agentlab_root,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=project_root / "acceptance",
    )

    assert result["schema_version"] == "narrative-acceptance-status/v1"
    assert [stage["stage"] for stage in result["stages"]] == [
        "P0",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
    ]
    assert all(stage["status"] == "missing" for stage in result["stages"])
    assert result["highest_completed_stage"] is None
    assert result["full_scale_production_ready"] is False
    assert result["claim_1980_chapter_capability_allowed"] is False


def test_acceptance_ladder_rejects_generic_self_asserted_evidence(
    tmp_path: Path,
) -> None:
    agentlab_root = _test_agentlab_root(tmp_path)
    project_root = agentlab_root / "projects" / "Crown_of_Ash"
    evidence_dir = project_root / "acceptance"
    evidence_dir.mkdir(parents=True)
    artifact = project_root / "verified-evidence.yml"
    artifact.write_text("verified: true\n", encoding="utf-8")
    artifact_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    ladder = yaml.safe_load(
        (ROOT / "config" / "narrative_acceptance_ladder.yml").read_text(
            encoding="utf-8"
        )
    )
    metrics = {
        "hard_continuity_errors": 0,
        "planted_fact_and_promise_recall": 0.95,
        "state_and_retrieval_traceability": 1.0,
        "cross_project_knowledge_leaks": 0,
        "due_promise_resolution_rate": 1.0,
        "blind_preference_rate": 0.65,
        "consecutive_windows_without_core_regression": 2,
    }
    for stage_id, stage in ladder["stages"].items():
        receipt = {
            "schema_version": "narrative-acceptance-receipt/v1",
            "project": "Crown_of_Ash",
            "stage": stage_id,
            "status": "pass",
            "checks": {
                check_id: {"status": "pass"}
                for check_id in stage["required_checks"]
            },
            "artifact_bindings": [
                {
                    "path": "verified-evidence.yml",
                    "sha256": artifact_sha256,
                }
            ],
        }
        if stage_id == "P5":
            receipt["release_metrics"] = metrics
        (evidence_dir / f"{stage_id}.yml").write_text(
            yaml.safe_dump(receipt, sort_keys=False),
            encoding="utf-8",
        )

    rejected = build_narrative_acceptance_status(
        agentlab_root,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=evidence_dir,
    )
    assert rejected["highest_completed_stage"] is None
    assert rejected["release_metrics_pass"] is False
    assert rejected["stages"][0]["issues"] == [
        "P0:stage_evidence_binding_required"
    ]
    assert rejected["claim_1980_chapter_capability_allowed"] is False

    artifact.write_text("verified: replaced\n", encoding="utf-8")
    tampered = build_narrative_acceptance_status(
        agentlab_root,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=evidence_dir,
    )
    assert tampered["stages"][0]["status"] == "blocked"
    assert tampered["stages"][0]["issues"] == [
        "artifact_sha256_mismatch:verified-evidence.yml",
        "P0:stage_evidence_binding_required",
    ]
    assert tampered["claim_1980_chapter_capability_allowed"] is False


def test_acceptance_ladder_inspects_stage_specific_trial_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agentlab_root = _test_agentlab_root(tmp_path)
    project_root = agentlab_root / "projects" / PROJECT
    evidence_dir = project_root / "acceptance"
    evidence_dir.mkdir(parents=True)
    ladder = yaml.safe_load(
        (ROOT / "config" / "narrative_acceptance_ladder.yml").read_text(
            encoding="utf-8"
        )
    )
    common = {"project": PROJECT, "status": "pass"}
    runtime_outputs: dict[tuple[str, str], str] = {}
    runtime_projections: dict[str, dict] = {}
    verified_attempts: list[tuple[str, str]] = []

    def verify_runtime_attempt(_self, task_id: str, attempt_id: str) -> dict:
        verified_attempts.append((task_id, attempt_id))
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "ok": True,
            "receipt_sha256": "c" * 64,
            "output_sha256": runtime_outputs[(task_id, attempt_id)],
            "runtime_provider": "test-provider",
            "model_id": "test-model",
        }

    def load_runtime_task(_self, task_id: str) -> dict:
        return runtime_projections[task_id]

    def list_runtime_tasks(_self, *, include_legacy: bool = False) -> list[dict]:
        del include_legacy
        return [{"task_id": task_id} for task_id in sorted(runtime_projections)]

    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.verify_attempt_execution_receipt",
        verify_runtime_attempt,
    )
    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.load_task",
        load_runtime_task,
    )
    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.list_tasks",
        list_runtime_tasks,
    )

    def producer_contract(
        stage: str,
        *,
        kind: str | None,
        step: str | None,
    ) -> tuple[str, str | None, str]:
        if stage == "P0":
            return "blueprint-migration", None, "Scribe"
        if stage == "P1":
            return "agent-registration", None, "Supervisor"
        if stage == "P2":
            return (
                "causality-trial",
                "plot_causality_architect",
                "NarrativePlanner",
            )
        if stage == "P3":
            producers = {
                "retrieval": ("research_style_curator", "Researcher"),
                "planning": ("arc_scene_planner", "NarrativePlanner"),
                "draft": ("writer", "Writer"),
                "audit": ("canon_timeline_steward", "Reviewer"),
                "revision": ("writer", "Writer"),
                "blind_review": ("reader_simulation_panel", "Reviewer"),
                "promotion": ("senior_editor", "Reviewer"),
                "state_projection": ("state_projector", "Scribe"),
            }
            agent_id, role = producers[str(step)]
            return f"narrative-{str(step).replace('_', '-')}", agent_id, role
        if stage == "P4" and kind == "accepted_chapter":
            return "accepted-chapter", "senior_editor", "Reviewer"
        if stage == "P4":
            return "drift-review", "reader_simulation_panel", "Reviewer"
        if kind == "pseudoprose_stress":
            return "pseudoprose-stress", "state_projector", "Scribe"
        if kind == "real_model_arc":
            return "real-model-arc", "authorial_director", "Supervisor"
        if kind == "metric_universe":
            return "metric-universe", "state_projector", "Scribe"
        return "release-metrics", "state_projector", "Scribe"

    def runtime_ref(
        stage: str,
        *,
        task_id: str,
        attempt_id: str,
        kind: str | None = None,
        chapter_id: int | None = None,
        step: str | None = None,
        details: dict | None = None,
    ) -> dict:
        work_item_id = f"work-{attempt_id}"
        work_item_kind, agent_id, runtime_role = producer_contract(
            stage,
            kind=kind,
            step=step,
        )
        path = project_root / "runtime-evidence" / f"{attempt_id}.yml"
        if kind == "metric_universe":
            projected = project_metric_universe(
                agentlab_root,
                project=PROJECT,
                task_id=task_id,
                attempt_id=attempt_id,
                metric_id=str((details or {}).get("metric_id") or ""),
                work_item_id=work_item_id,
                output_path=path,
            )
            document = {
                key: value
                for key, value in projected.items()
                if key != "artifact"
            }
        else:
            document = {
                **common,
                "schema_version": "narrative-runtime-stage-evidence/v1",
                "stage": stage,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "kind": kind,
                "chapter_id": chapter_id,
                "step": step,
                "work_item_id": work_item_id,
                **(details or {}),
            }
            _write_yaml(path, document)
        binding = _binding(project_root, path)
        runtime_outputs[(task_id, attempt_id)] = binding["sha256"]
        projection = runtime_projections.setdefault(
            task_id,
            {"attempts": {}, "work_items": {}},
        )
        projection["work_items"][work_item_id] = {
            "work_item_id": work_item_id,
            "kind": work_item_kind,
            "assigned_agent_id": agent_id,
        }
        execution_contract = {"role": runtime_role}
        if kind == "metric_universe":
            execution_contract.update(
                {
                    "executor_type": "deterministic_tool",
                    "deterministic_tool": {
                        key: document["producer"][key]
                        for key in (
                            "tool_id",
                            "tool_version",
                            "input_tree_sha256",
                        )
                    },
                }
            )
        projected_attempt = {
            "attempt_id": attempt_id,
            "work_item_id": work_item_id,
            "execution_contract": execution_contract,
        }
        if kind == "metric_universe":
            projected_attempt.update(
                {
                    "status": "succeeded",
                    "outcome": {
                        "execution_origin": (
                            "deterministic_tool_executor"
                        )
                    },
                }
            )
        projection["attempts"][attempt_id] = projected_attempt
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "kind": kind,
            "chapter_id": chapter_id,
            "step": step,
            "work_item_id": work_item_id,
            "artifact": binding,
        }

    evidence: dict[str, dict] = {
        "P0": {
            **common,
            "schema_version": "narrative-p0-evidence/v1",
            "stage": "P0",
            "authoritative_chapter_range": [1, 20],
            "current_planning_window_count": 2,
            "double_current_count": 1,
            "legacy_seal_status": "current",
            "runtime_attempts": [
                runtime_ref(
                    "P0",
                    task_id="task_p0",
                    attempt_id="attempt_p0",
                    kind="blueprint_migration",
                    details={
                        "authoritative_chapter_range": [1, 25],
                        "current_planning_window_count": 1,
                        "double_current_count": 0,
                        "legacy_seal_status": "superseded",
                    },
                )
            ],
        },
        "P1": {
            **common,
            "schema_version": "narrative-p1-evidence/v1",
            "stage": "P1",
            "registered_agent_count": 0,
            "private_knowledge_namespaces": [],
            "atomic_registration": False,
            "role_dag_audit": {"status": "fail"},
            "project_truth_audit": {"status": "fail"},
            "runtime_attempts": [
                runtime_ref(
                    "P1",
                    task_id="task_p1",
                    attempt_id="attempt_p1",
                    kind="agent_registration",
                    details={
                        "registered_agent_count": 13,
                        "private_knowledge_namespaces": [
                            f"agent.{PROJECT}.{role_id}"
                            for role_id in REQUIRED_AUTHOR_ROLES
                        ],
                        "atomic_registration": True,
                        "role_dag_audit": {"status": "pass"},
                        "project_truth_audit": {"status": "pass"},
                    },
                )
            ],
        },
    }
    p2_receipts = []
    p2_trial_bindings = []
    for chapter_id in range(1, 4):
        context_path = (
            project_root / "trials" / f"p2-context-{chapter_id}.yml"
        )
        candidate_path = (
            project_root / "trials" / f"p2-candidate-{chapter_id}.yml"
        )
        _write_yaml(context_path, {"chapter_id": chapter_id, "kind": "context"})
        _write_yaml(
            candidate_path,
            {"chapter_id": chapter_id, "kind": "candidate"},
        )
        source_boundaries = {
            "guesses_committed_as_facts": 0,
            "abilities_without_sources": 0,
            "knowledge_without_sources": 0,
        }
        trial_artifact_path = (
            project_root / "trials" / f"p2-artifact-{chapter_id}.yml"
        )
        _write_yaml(
            trial_artifact_path,
            {
                "schema_version": "narrative-causality-trial-evidence/v1",
                **common,
                "chapter_id": chapter_id,
                "source_boundaries": source_boundaries,
                "context_pack_bindings": [
                    _binding(project_root, context_path)
                ],
                "candidate_binding": _binding(project_root, candidate_path),
            },
        )
        trial_artifact_binding = _binding(
            project_root,
            trial_artifact_path,
        )
        p2_trial_bindings.append(trial_artifact_binding)
        path = project_root / "trials" / f"p2-{chapter_id}.yml"
        _write_yaml(
            path,
            {
                **common,
                "schema_version": "narrative-chapter-trial-receipt/v1",
                "chapter_id": chapter_id,
                "source_boundaries": source_boundaries,
                "trial_artifact_binding": trial_artifact_binding,
            },
        )
        p2_receipts.append(_binding(project_root, path))
    evidence["P2"] = {
        **common,
        "schema_version": "narrative-p2-evidence/v1",
        "stage": "P2",
        "chapter_receipts": p2_receipts,
        "runtime_attempts": [
            runtime_ref(
                "P2",
                task_id=f"task_p2_chapter_{chapter_id}",
                attempt_id=f"attempt_p2_chapter_{chapter_id}",
                kind="causality_trial",
                chapter_id=chapter_id,
                details={
                    "chapter_receipt_sha256": p2_receipts[
                        chapter_id - 1
                    ]["sha256"],
                    "source_boundaries": {
                        "guesses_committed_as_facts": 0,
                        "abilities_without_sources": 0,
                        "knowledge_without_sources": 0,
                    },
                    "trial_artifact_binding": p2_trial_bindings[
                        chapter_id - 1
                    ],
                },
            )
            for chapter_id in range(1, 4)
        ],
    }
    p3_receipts = []
    p3_step_bindings = {}
    p3_steps = (
        "retrieval",
        "planning",
        "draft",
        "audit",
        "revision",
        "blind_review",
        "promotion",
        "state_projection",
    )
    for chapter_id in range(1, 11):
        seed_path = project_root / "trials" / f"p3-seed-{chapter_id}.yml"
        _write_yaml(seed_path, {"chapter_id": chapter_id, "kind": "seed"})
        previous_binding = _binding(project_root, seed_path)
        step_receipts = {}
        for step in p3_steps:
            step_path = (
                project_root
                / "trials"
                / f"p3-{chapter_id}-{step}-artifact.yml"
            )
            _write_yaml(
                step_path,
                {
                    "schema_version": "narrative-production-step-evidence/v1",
                    **common,
                    "chapter_id": chapter_id,
                    "step": step,
                    "input_bindings": [previous_binding],
                },
            )
            previous_binding = _binding(project_root, step_path)
            step_receipts[step] = {
                "status": "pass",
                "artifact_binding": previous_binding,
            }
            p3_step_bindings[(chapter_id, step)] = previous_binding
        path = project_root / "trials" / f"p3-{chapter_id}.yml"
        _write_yaml(
            path,
            {
                **common,
                "schema_version": "narrative-production-loop-receipt/v1",
                "chapter_id": chapter_id,
                "steps": step_receipts,
            },
        )
        p3_receipts.append(_binding(project_root, path))
    evidence["P3"] = {
        **common,
        "schema_version": "narrative-p3-evidence/v1",
        "stage": "P3",
        "chapter_receipts": p3_receipts,
        "runtime_attempts": [
            runtime_ref(
                "P3",
                task_id=f"task_p3_chapter_{chapter_id}",
                attempt_id=f"attempt_p3_{chapter_id}_{step}",
                chapter_id=chapter_id,
                step=step,
                details={
                    "chapter_receipt_sha256": p3_receipts[
                        chapter_id - 1
                    ]["sha256"],
                    "step_artifact_binding": p3_step_bindings[
                        (chapter_id, step)
                    ],
                },
            )
            for chapter_id in range(1, 11)
            for step in p3_steps
        ],
    }
    p4_receipts = []
    p4_accepted_bindings = []
    for chapter_id in range(1, 31):
        source_path = project_root / "trials" / f"p4-source-{chapter_id}.yml"
        _write_yaml(source_path, {"chapter_id": chapter_id, "kind": "source"})
        accepted_path = (
            project_root / "trials" / f"p4-accepted-{chapter_id}.yml"
        )
        _write_yaml(
            accepted_path,
            {
                "schema_version": "narrative-accepted-chapter-evidence/v1",
                **common,
                "chapter_id": chapter_id,
                "source_bindings": [_binding(project_root, source_path)],
            },
        )
        accepted_binding = _binding(project_root, accepted_path)
        p4_accepted_bindings.append(accepted_binding)
        path = project_root / "trials" / f"p4-{chapter_id}.yml"
        _write_yaml(
            path,
            {
                **common,
                "schema_version": "narrative-accepted-chapter-receipt/v1",
                "chapter_id": chapter_id,
                "accepted_artifact_binding": accepted_binding,
            },
        )
        p4_receipts.append(_binding(project_root, path))
    evidence["P4"] = {
        **common,
        "schema_version": "narrative-p4-evidence/v1",
        "stage": "P4",
        "chapter_receipts": p4_receipts,
        "drift_checks": {
            check: {"status": "fail"}
            for check in (
                "character_convergence",
                "template_repetition",
                "relationship_progression",
                "promise_resolution",
                "summary_loss",
                "preference_overfitting",
            )
        },
        "runtime_attempts": [
            runtime_ref(
                "P4",
                task_id=f"task_p4_chapter_{chapter_id}",
                attempt_id=f"attempt_p4_chapter_{chapter_id}",
                kind="accepted_chapter",
                chapter_id=chapter_id,
                details={
                    "chapter_receipt_sha256": p4_receipts[
                        chapter_id - 1
                    ]["sha256"],
                    "accepted_artifact_binding": p4_accepted_bindings[
                        chapter_id - 1
                    ],
                },
            )
            for chapter_id in range(1, 31)
        ]
        + [
            runtime_ref(
                "P4",
                task_id="task_p4_drift_review",
                attempt_id="attempt_p4_drift_review",
                kind="drift_review",
                details={
                    "drift_checks": {
                        check: {"status": "pass"}
                        for check in (
                            "character_convergence",
                            "template_repetition",
                            "relationship_progression",
                            "promise_resolution",
                            "summary_loss",
                            "preference_overfitting",
                        )
                    },
                    "sample_bindings": p4_accepted_bindings,
                },
            )
        ],
    }
    candidate_chapters = []
    candidate_records = []
    for chapter_id in range(1, 4):
        candidate_chapter = (
            project_root / "p5" / f"candidate-chapter-{chapter_id:03d}.md"
        )
        candidate_chapter.parent.mkdir(parents=True, exist_ok=True)
        candidate_chapter.write_text(
            f"Accepted arc chapter {chapter_id}.\n",
            encoding="utf-8",
        )
        candidate_chapters.append(candidate_chapter)
        candidate_records.append(
            {
                "chapter_id": chapter_id,
                "artifact_path": candidate_chapter.relative_to(
                    project_root
                ).as_posix(),
                "source_run_id": "task_p5_real_arc",
                "source_model": "test-model",
                "model_tier": "final",
                "context_manifest_sha256": "d" * 64,
                "generation_receipt": (
                    f"p5/receipts/{chapter_id:03d}-generation.yml"
                ),
                "correctness_audit": (
                    f"p5/receipts/{chapter_id:03d}-correctness.yml"
                ),
                "literary_audit": (
                    f"p5/receipts/{chapter_id:03d}-literary.yml"
                ),
                "cost_receipt": f"p5/receipts/{chapter_id:03d}-cost.yml",
            }
        )
    candidate_set = create_candidate_set(
        project_root,
        candidate_set_id="test-real-model-arc",
        created_at="2026-07-29T00:00:00Z",
        canon_snapshot_sha256="canon-test",
        scorecard_version=1,
        chapters=candidate_records,
    )
    candidate_set = freeze_candidate_set(
        project_root,
        Path(candidate_set["manifest_path"]),
        frozen_at="2026-07-29T00:00:01Z",
    )
    candidate_receipt_contracts = {
        "generation_receipt": (
            "narrative-generation-receipt/v1",
            "narrative-generation",
            "writer",
            "Writer",
        ),
        "correctness_audit": (
            "narrative-correctness-audit-receipt/v1",
            "narrative-correctness-audit",
            "canon_timeline_steward",
            "Reviewer",
        ),
        "literary_audit": (
            "narrative-literary-audit-receipt/v1",
            "narrative-literary-audit",
            "senior_editor",
            "Reviewer",
        ),
        "cost_receipt": (
            "narrative-cost-receipt/v1",
            "narrative-cost-audit",
            "authorial_director",
            "Supervisor",
        ),
    }
    for chapter in candidate_set["chapters"]:
        chapter_id = int(chapter["chapter_id"])
        for field, (
            schema_version,
            work_item_kind,
            agent_id,
            runtime_role,
        ) in candidate_receipt_contracts.items():
            task_id = f"task_p5_candidate_{chapter_id}_{field}"
            attempt_id = f"attempt_p5_candidate_{chapter_id}_{field}"
            work_item_id = f"work-{attempt_id}"
            receipt_path = project_root / str(chapter[field])
            _write_yaml(
                receipt_path,
                {
                    "schema_version": schema_version,
                    "project": PROJECT,
                    "chapter_id": chapter_id,
                    "status": "pass",
                    "candidate_set_sha256": candidate_set[
                        "candidate_set_sha256"
                    ],
                    "artifact_sha256": chapter["artifact_sha256"],
                    "blocking_count": 0,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "work_item_id": work_item_id,
                    "execution_receipt_sha256": "c" * 64,
                    "provider": "test-provider",
                    "model_id": "test-model",
                },
            )
            runtime_outputs[(task_id, attempt_id)] = hashlib.sha256(
                receipt_path.read_bytes()
            ).hexdigest()
            runtime_projections[task_id] = {
                "work_items": {
                    work_item_id: {
                        "work_item_id": work_item_id,
                        "kind": work_item_kind,
                        "assigned_agent_id": agent_id,
                    }
                },
                "attempts": {
                    attempt_id: {
                        "attempt_id": attempt_id,
                        "work_item_id": work_item_id,
                        "execution_contract": {"role": runtime_role},
                    }
                },
            }
    arc_artifact = Path(str(candidate_set["manifest_path"]))
    arc_run = project_root / "p5" / "real-model-run.yml"
    promoted_chapters = []
    for chapter_id, candidate_chapter in enumerate(candidate_chapters, start=1):
        promoted_chapter = (
            project_root
            / "release_objects"
            / "editions"
            / "test-arc"
            / f"chapter_{chapter_id:03d}.md"
        )
        promoted_chapter.parent.mkdir(parents=True, exist_ok=True)
        promoted_chapter.write_bytes(candidate_chapter.read_bytes())
        promoted_chapters.append(
            {
                "chapter_id": chapter_id,
                "artifact_path": promoted_chapter.relative_to(
                    project_root
                ).as_posix(),
                "artifact_sha256": hashlib.sha256(
                    promoted_chapter.read_bytes()
                ).hexdigest(),
            }
        )
    arc_promotion = (
        project_root
        / "release_objects"
        / "editions"
        / "test-arc"
        / "promotion_receipt.yml"
    )
    _write_yaml(
        arc_run,
        {
            "schema_version": "narrative-real-model-arc-run/v1",
            "status": "pass",
            "project": PROJECT,
            "task_id": "task_p5_real_arc",
            "attempt_id": "attempt_p5_real_arc",
            "provider": "test-provider",
            "model_id": "test-model",
            "candidate_set_sha256": candidate_set[
                "candidate_set_sha256"
            ],
            "chapter_start": 1,
            "chapter_end": 3,
            "chapter_count": 3,
        },
    )
    evidence_bundle_sha256 = compute_evidence_bundle_sha256(
        project_root,
        candidate_set,
    )
    recorded_acceptance = record_signed_candidate_acceptance(
        project_root,
        manifest_path=Path(candidate_set["manifest_path"]),
        actor_id="test-user",
        idempotency_key="accept-test-real-model-arc",
        approved_at="2026-07-29T00:00:02Z",
    )
    user_acceptance = project_root / recorded_acceptance["receipt_path"]
    _write_yaml(
        arc_promotion,
        {
            "schema_version": 1,
            "status": "promoted",
            "production_modified": True,
            "candidate_set_id": candidate_set["candidate_set_id"],
            "candidate_set_sha256": candidate_set[
                "candidate_set_sha256"
            ],
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "user_acceptance_receipt": user_acceptance.relative_to(
                project_root
            ).as_posix(),
            "chapters": promoted_chapters,
        },
    )
    arc_run_binding = _binding(project_root, arc_run)
    arc_artifact_binding = _binding(project_root, arc_artifact)
    arc_promotion_binding = _binding(project_root, arc_promotion)
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "schema_version": 1,
            "current_release": {
                "candidate_set_id": candidate_set["candidate_set_id"],
                "candidate_set_sha256": candidate_set[
                    "candidate_set_sha256"
                ],
                "promotion_receipt": arc_promotion_binding["path"],
            },
        },
    )
    verified_metrics = {
        "hard_continuity_errors": 0,
        "planted_fact_and_promise_recall": 0.95,
        "state_and_retrieval_traceability": 1.0,
        "cross_project_knowledge_leaks": 0,
        "due_promise_resolution_rate": 1.0,
        "blind_preference_rate": 0.65,
        "consecutive_windows_without_core_regression": 2,
    }
    metric_calculations = {
        "hard_continuity_errors": {"operation": "count", "numerator": 0},
        "planted_fact_and_promise_recall": {
            "operation": "ratio",
            "numerator": 95,
            "denominator": 100,
        },
        "state_and_retrieval_traceability": {
            "operation": "ratio",
            "numerator": 100,
            "denominator": 100,
        },
        "cross_project_knowledge_leaks": {
            "operation": "count",
            "numerator": 0,
        },
        "due_promise_resolution_rate": {
            "operation": "ratio",
            "numerator": 10,
            "denominator": 10,
        },
        "blind_preference_rate": {
            "operation": "ratio",
            "numerator": 65,
            "denominator": 100,
        },
        "consecutive_windows_without_core_regression": {
            "operation": "count",
            "numerator": 2,
        },
    }
    metric_samples = {
        "hard_continuity_errors": [0],
        "planted_fact_and_promise_recall": [True] * 95 + [False] * 5,
        "state_and_retrieval_traceability": [True] * 100,
        "cross_project_knowledge_leaks": [0],
        "due_promise_resolution_rate": [True] * 10,
        "blind_preference_rate": [True] * 65 + [False] * 35,
        "consecutive_windows_without_core_regression": [1, 1],
    }
    metric_evidence = {}
    metric_universe_runtime_refs = []
    metric_subject_producers = {
        "hard_continuity_errors": (
            "narrative-hard-continuity-audit",
            "canon_timeline_steward",
            "Reviewer",
        ),
        "planted_fact_and_promise_recall": (
            "narrative-retrieval-trace",
            "research_style_curator",
            "Researcher",
        ),
        "state_and_retrieval_traceability": (
            "narrative-traceability-record",
            "state_projector",
            "Scribe",
        ),
        "cross_project_knowledge_leaks": (
            "narrative-knowledge-isolation-audit",
            "canon_timeline_steward",
            "Reviewer",
        ),
        "due_promise_resolution_rate": (
            "narrative-promise-disposition",
            "foreshadow_mystery_keeper",
            "Reviewer",
        ),
        "blind_preference_rate": (
            "narrative-blind-review-vote",
            "reader_simulation_panel",
            "Reviewer",
        ),
        "consecutive_windows_without_core_regression": (
            "narrative-window-acceptance",
            "authorial_director",
            "Supervisor",
        ),
    }
    for metric_id, metric_value in verified_metrics.items():
        bound_samples = []
        for sample_index, sample_result in enumerate(
            metric_samples[metric_id],
            start=1,
        ):
            sample_id = f"{metric_id}-{sample_index:03d}"
            subject_path = (
                project_root
                / "acceptance"
                / "metric-subjects"
                / metric_id
                / f"{sample_index:03d}.yml"
            )
            subject = {
                "project": PROJECT,
                "status": "pass",
                "evidence_bindings": [arc_artifact_binding],
            }
            subject_task_id = f"task_p5_metric_subject_{metric_id}_{sample_index:03d}"
            subject_attempt_id = (
                f"attempt_p5_metric_subject_{metric_id}_{sample_index:03d}"
            )
            subject_work_item_id = f"work-{subject_attempt_id}"
            subject["runtime_binding"] = {
                "task_id": subject_task_id,
                "attempt_id": subject_attempt_id,
                "work_item_id": subject_work_item_id,
            }
            if metric_id == "hard_continuity_errors":
                subject.update(
                    {
                        "schema_version": "narrative-hard-continuity-audit/v1",
                        "blocking_findings": [f"f-{sample_index}"]
                        * int(sample_result),
                    }
                )
            elif metric_id == "planted_fact_and_promise_recall":
                expected_item_id = f"promise-{sample_index:03d}"
                subject.update(
                    {
                        "schema_version": "narrative-retrieval-trace/v1",
                        "expected_item_id": expected_item_id,
                        "retrieved_item_ids": (
                            [expected_item_id] if sample_result else []
                        ),
                    }
                )
            elif metric_id == "state_and_retrieval_traceability":
                subject.update(
                    {
                        "schema_version": "narrative-traceability-record/v1",
                        "state_change_binding": arc_artifact_binding,
                        "retrieval_evidence_binding": arc_run_binding,
                    }
                )
            elif metric_id == "cross_project_knowledge_leaks":
                subject.update(
                    {
                        "schema_version": (
                            "narrative-knowledge-isolation-audit/v1"
                        ),
                        "observed_project_namespaces": (
                            [PROJECT]
                            + [
                                f"foreign-{value}"
                                for value in range(int(sample_result))
                            ]
                        ),
                    }
                )
            elif metric_id == "due_promise_resolution_rate":
                subject.update(
                    {
                        "schema_version": "narrative-promise-disposition/v1",
                        "due": True,
                        "disposition": (
                            "paid_off" if sample_result else "overdue"
                        ),
                    }
                )
            elif metric_id == "blind_preference_rate":
                subject.update(
                    {
                        "schema_version": "narrative-blind-review-vote/v1",
                        "randomized_order": True,
                        "voter_id": f"reader-{sample_index:03d}",
                        "preferred_candidate": (
                            "system" if sample_result else "baseline"
                        ),
                    }
                )
            else:
                subject.update(
                    {
                        "schema_version": "narrative-window-acceptance/v1",
                        "accepted": True,
                        "core_regression": not bool(sample_result),
                    }
            )
            _write_yaml(subject_path, subject)
            subject_binding = _binding(project_root, subject_path)
            (
                subject_work_kind,
                subject_agent_id,
                subject_runtime_role,
            ) = metric_subject_producers[metric_id]
            runtime_outputs[
                (subject_task_id, subject_attempt_id)
            ] = subject_binding["sha256"]
            runtime_projections[subject_task_id] = {
                "work_items": {
                    subject_work_item_id: {
                        "work_item_id": subject_work_item_id,
                        "kind": subject_work_kind,
                        "assigned_agent_id": subject_agent_id,
                    }
                },
                "attempts": {
                    subject_attempt_id: {
                        "attempt_id": subject_attempt_id,
                        "work_item_id": subject_work_item_id,
                        "status": "succeeded",
                        "execution_contract": {
                            "role": subject_runtime_role,
                        },
                    }
                },
            }
            sample_path = (
                project_root
                / "p5"
                / "metric-samples"
                / metric_id
                / f"{sample_index:03d}.yml"
            )
            _write_yaml(
                sample_path,
                {
                    "schema_version": "narrative-release-metric-sample/v1",
                    "project": PROJECT,
                    "metric_id": metric_id,
                    "sample_id": sample_id,
                    "subject_locator": subject_binding["path"],
                    "subject_sha256": subject_binding["sha256"],
                    "subject_binding": subject_binding,
                    "result": sample_result,
                    "status": "pass",
                },
            )
            bound_samples.append(
                {
                    "sample_id": sample_id,
                    "result": sample_result,
                    "evidence_binding": _binding(
                        project_root,
                        sample_path,
                    ),
                }
            )
        universe_ref = runtime_ref(
            "P5",
            task_id=f"task_p5_metric_universe_{metric_id}",
            attempt_id=f"attempt_p5_metric_universe_{metric_id}",
            kind="metric_universe",
            details={
                "metric_id": metric_id,
            },
        )
        metric_universe_runtime_refs.append(universe_ref)
        metric_source = (
            project_root / "p5" / f"metric-source-{metric_id}.yml"
        )
        _write_yaml(
            metric_source,
            {
                "schema_version": "narrative-release-metric-source/v1",
                "project": PROJECT,
                "metric_id": metric_id,
                "operation": metric_calculations[metric_id]["operation"],
                "samples": bound_samples,
                "universe_binding": universe_ref["artifact"],
            },
        )
        metric_path = project_root / "p5" / f"metric-{metric_id}.yml"
        _write_yaml(
            metric_path,
            {
                "schema_version": "narrative-release-metric-evidence/v1",
                "project": PROJECT,
                "metric_id": metric_id,
                "value": metric_value,
                "calculation": metric_calculations[metric_id],
                "source_bindings": [_binding(project_root, metric_source)],
            },
        )
        metric_evidence[metric_id] = _binding(project_root, metric_path)
    stress_execution = run_pseudoprose_state_stress(
        agentlab_root,
        project=PROJECT,
        task_id="task_p5_stress",
        chapter_count=100,
    )
    evidence["P5"] = {
        **common,
        "schema_version": "narrative-p5-evidence/v1",
        "stage": "P5",
        "pseudoprose_chapter_count": 1,
        "recovery": {"status": "fail"},
        "rollback": {"status": "fail"},
        "real_model_arc": {
            "status": "fail",
        },
        "runtime_attempts": [
            runtime_ref(
                "P5",
                task_id="task_p5_stress",
                attempt_id="attempt_p5_stress",
                kind="pseudoprose_stress",
                details={
                    key: stress_execution[key]
                    for key in (
                        "pseudoprose_chapter_count",
                        "state_store_root",
                        "event_ledger_binding",
                        "state_artifact_bindings",
                        "state_chain_sha256",
                        "recovery_receipt_binding",
                        "rollback_receipt_binding",
                    )
                },
            ),
            runtime_ref(
                "P5",
                task_id="task_p5_real_arc",
                attempt_id="attempt_p5_real_arc",
                kind="real_model_arc",
                details={
                    "real_model_arc": {
                        "status": "pass",
                        "provider": "test-provider",
                        "candidate_set_sha256": candidate_set[
                            "candidate_set_sha256"
                        ],
                        "run_sha256": arc_run_binding["sha256"],
                        "artifact_sha256": arc_artifact_binding["sha256"],
                        "promotion_receipt_sha256": arc_promotion_binding[
                            "sha256"
                        ],
                        "run_binding": arc_run_binding,
                        "artifact_binding": arc_artifact_binding,
                        "promotion_receipt_binding": arc_promotion_binding,
                    }
                },
            ),
            runtime_ref(
                "P5",
                task_id="task_p5_release_metrics",
                attempt_id="attempt_p5_release_metrics",
                kind="release_metrics",
                details={
                    "release_metrics": verified_metrics,
                    "metric_evidence": metric_evidence,
                },
            ),
            *metric_universe_runtime_refs,
        ],
    }
    def validate_blueprint(*_args, **_kwargs) -> dict:
        return {"status": "pass", "chapter_range": [1, 25]}

    def validate_planning_window(*_args, **_kwargs) -> dict:
        return {
            "status": "pass",
            "current_count": 1,
            "double_current_count": 0,
            "legacy_seal_status": "superseded",
            "locked_chapters": list(range(1, 11)),
            "horizon_chapters": list(range(11, 26)),
        }

    class FakeTruth:
        def __init__(self, _project_root: Path) -> None:
            pass

        def audit(self) -> dict:
            return {"status": "pass"}

    class FakeManifest:
        def __init__(self, role_id: str) -> None:
            self.id = role_id
            self.status = "active"
            self.collaboration = {"dependencies": []}
            self.knowledge_binding = {
                "namespace": f"agent.{PROJECT}.{role_id}"
            }

        def to_dict(self) -> dict:
            return {
                "id": self.id,
                "status": self.status,
                "collaboration": self.collaboration,
                "knowledge_binding": self.knowledge_binding,
            }

    class FakeRegistry:
        def __init__(self, _truth: FakeTruth) -> None:
            pass

        def list(self, *, include_archived: bool) -> list[FakeManifest]:
            assert include_archived is False
            return [
                FakeManifest(role_id)
                for role_id in REQUIRED_AUTHOR_ROLES
            ]

    class FakeKnowledgeStore:
        def __init__(self, _root: Path) -> None:
            pass

        def space_exists(self, _namespace: str) -> bool:
            return True

        def inactive_spaces(self, _namespaces) -> tuple:
            return ()

    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder.validate_crown_blueprint",
        validate_blueprint,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder."
        "validate_current_planning_window",
        validate_planning_window,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder.ProjectTruthStore",
        FakeTruth,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder.ProjectAgentRegistry",
        FakeRegistry,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder.KnowledgeStore",
        FakeKnowledgeStore,
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder.load_author_team_contract",
        lambda *_args, **_kwargs: {"schema_version": "test"},
    )
    monkeypatch.setattr(
        "agent_runtime.narrative.acceptance_ladder."
        "build_author_team_manifests",
        lambda _contract: tuple(
            FakeManifest(role_id) for role_id in REQUIRED_AUTHOR_ROLES
        ),
    )
    unverified_receipt_metrics = {
        "hard_continuity_errors": 0,
        "planted_fact_and_promise_recall": 0.0,
        "state_and_retrieval_traceability": 1.0,
        "cross_project_knowledge_leaks": 0,
        "due_promise_resolution_rate": 1.0,
        "blind_preference_rate": 0.0,
        "consecutive_windows_without_core_regression": 2,
    }
    for stage_id, stage_evidence in evidence.items():
        evidence_path = project_root / "acceptance" / f"{stage_id}-evidence.yml"
        _write_yaml(evidence_path, stage_evidence)
        receipt = {
            "schema_version": "narrative-acceptance-receipt/v1",
            "project": PROJECT,
            "stage": stage_id,
            "status": "pass",
            "checks": {
                check_id: {"status": "pass"}
                for check_id in ladder["stages"][stage_id]["required_checks"]
            },
            "artifact_bindings": [
                _binding(
                    project_root,
                    evidence_path,
                    evidence_kind="stage_evidence",
                    schema_version=stage_evidence["schema_version"],
                )
            ],
        }
        if stage_id == "P5":
            receipt["release_metrics"] = unverified_receipt_metrics
        _write_yaml(evidence_dir / f"{stage_id}.yml", receipt)

    accepted = build_narrative_acceptance_status(
        agentlab_root,
        project=PROJECT,
        project_root=project_root,
        evidence_dir=evidence_dir,
    )

    assert accepted["highest_completed_stage"] == "P5", accepted["stages"][-1]
    assert accepted["release_metrics_pass"] is True
    assert accepted["claim_1980_chapter_capability_allowed"] is True
    assert set(runtime_outputs).issubset(set(verified_attempts))

    first_generation_receipt = (
        project_root
        / str(candidate_set["chapters"][0]["generation_receipt"])
    )
    tampered_receipt = yaml.safe_load(
        first_generation_receipt.read_text(encoding="utf-8")
    )
    tampered_receipt["blocking_count"] = 1
    _write_yaml(first_generation_receipt, tampered_receipt)
    tampered = build_narrative_acceptance_status(
        agentlab_root,
        project=PROJECT,
        project_root=project_root,
        evidence_dir=evidence_dir,
    )
    assert tampered["stages"][5]["status"] == "blocked"
    assert tampered["claim_1980_chapter_capability_allowed"] is False
    assert any(
        "candidate_set_chapter_receipt_invalid" in issue
        for issue in tampered["stages"][5]["issues"]
    )
