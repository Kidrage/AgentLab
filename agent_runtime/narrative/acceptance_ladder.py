"""Evidence-bound P0-P5 narrative production acceptance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import math
import re

import yaml

from agent_runtime.knowledge_system.storage import KnowledgeStore
from agent_runtime.narrative.blueprint_validation import validate_crown_blueprint
from agent_runtime.narrative.candidates.manifest import validate_candidate_set
from agent_runtime.narrative.candidates.promotion import (
    evidence_bundle_sha256,
)
from agent_runtime.narrative.author_team import (
    REQUIRED_AUTHOR_ROLES,
    build_author_team_manifests,
    load_author_team_contract,
)
from agent_runtime.narrative.planning_window import (
    validate_current_planning_window,
)
from agent_runtime.narrative.metric_universe import (
    TOOL_ID as METRIC_UNIVERSE_TOOL_ID,
    TOOL_VERSION as METRIC_UNIVERSE_TOOL_VERSION,
    metric_universe_issues,
)
from agent_runtime.narrative.state_store import NarrativeStateStore
from agent_runtime.narrative.user_acceptance import (
    validate_candidate_acceptance,
)
from agent_runtime.project_agents import ProjectAgentRegistry
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import TaskRuntime

_STAGES = ("P0", "P1", "P2", "P3", "P4", "P5")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_P3_STEP_SEQUENCE = (
    "retrieval",
    "planning",
    "draft",
    "audit",
    "revision",
    "blind_review",
    "promotion",
    "state_projection",
)
_P3_STEPS = frozenset(_P3_STEP_SEQUENCE)
_P4_DRIFT_CHECKS = frozenset(
    {
        "character_convergence",
        "template_repetition",
        "relationship_progression",
        "promise_resolution",
        "summary_loss",
        "preference_overfitting",
    }
)
_P3_PRODUCERS = {
    "retrieval": ("research_style_curator", "Researcher"),
    "planning": ("arc_scene_planner", "NarrativePlanner"),
    "draft": ("writer", "Writer"),
    "audit": ("canon_timeline_steward", "Reviewer"),
    "revision": ("writer", "Writer"),
    "blind_review": ("reader_simulation_panel", "Reviewer"),
    "promotion": ("senior_editor", "Reviewer"),
    "state_projection": ("state_projector", "Scribe"),
}


def _read_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return value if isinstance(value, Mapping) else None


def _artifact_issues(
    receipt: Mapping[str, Any],
    *,
    project_root: Path,
) -> list[str]:
    bindings = receipt.get("artifact_bindings")
    if not isinstance(bindings, list) or not bindings:
        return ["artifact_bindings_required"]
    issues: list[str] = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            issues.append(f"artifact_binding_invalid:{index}")
            continue
        path_value = binding.get("path")
        declared_sha256 = binding.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            issues.append(f"artifact_path_required:{index}")
            continue
        path = (project_root / path_value).resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            issues.append(f"artifact_outside_project:{index}")
            continue
        if not path.is_file():
            issues.append(f"artifact_not_found:{path_value}")
            continue
        if not isinstance(declared_sha256, str) or not _SHA256.fullmatch(
            declared_sha256
        ):
            issues.append(f"artifact_sha256_invalid:{path_value}")
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != declared_sha256:
            issues.append(f"artifact_sha256_mismatch:{path_value}")
    return issues


def _binding_document(
    binding: Mapping[str, Any],
    *,
    project_root: Path,
) -> Mapping[str, Any] | None:
    path_value = binding.get("path")
    if not isinstance(path_value, str) or not path_value:
        return None
    path = (project_root / path_value).resolve()
    try:
        path.relative_to(project_root)
    except ValueError:
        return None
    declared = binding.get("sha256")
    if (
        not path.is_file()
        or not isinstance(declared, str)
        or not _SHA256.fullmatch(declared)
        or hashlib.sha256(path.read_bytes()).hexdigest() != declared
    ):
        return None
    return _read_mapping(path)


def _chapter_receipt_issues(
    evidence: Mapping[str, Any],
    *,
    project: str,
    project_root: Path,
    count: int,
    schema_version: str,
    stage_id: str,
) -> list[str]:
    bindings = evidence.get("chapter_receipts")
    if not isinstance(bindings, list) or len(bindings) != count:
        return [f"{stage_id}:chapter_receipt_count_must_be_{count}"]
    binding_issues = _artifact_issues(
        {"artifact_bindings": bindings},
        project_root=project_root,
    )
    issues = [f"{stage_id}:{issue}" for issue in binding_issues]
    chapter_ids: list[int] = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            continue
        receipt = _binding_document(binding, project_root=project_root)
        if receipt is None:
            continue
        if receipt.get("schema_version") != schema_version:
            issues.append(f"{stage_id}:chapter[{index}]:schema_invalid")
        if receipt.get("project") != project:
            issues.append(f"{stage_id}:chapter[{index}]:project_mismatch")
        if receipt.get("status") != "pass":
            issues.append(f"{stage_id}:chapter[{index}]:not_pass")
        chapter_id = receipt.get("chapter_id")
        if (
            isinstance(chapter_id, bool)
            or not isinstance(chapter_id, int)
            or chapter_id <= 0
        ):
            issues.append(f"{stage_id}:chapter[{index}]:id_invalid")
        else:
            chapter_ids.append(chapter_id)
        if stage_id == "P2":
            facts = receipt.get("source_boundaries")
            if not isinstance(facts, Mapping):
                issues.append(f"{stage_id}:chapter[{index}]:source_boundaries_invalid")
            else:
                for field in (
                    "guesses_committed_as_facts",
                    "abilities_without_sources",
                    "knowledge_without_sources",
                ):
                    if facts.get(field) != 0:
                        issues.append(
                            f"{stage_id}:chapter[{index}]:{field}_not_zero"
                        )
            trial_binding = receipt.get("trial_artifact_binding")
            trial = (
                _binding_document(trial_binding, project_root=project_root)
                if isinstance(trial_binding, Mapping)
                else None
            )
            context_bindings = (
                trial.get("context_pack_bindings")
                if isinstance(trial, Mapping)
                else None
            )
            candidate_binding = (
                trial.get("candidate_binding")
                if isinstance(trial, Mapping)
                else None
            )
            if (
                trial is None
                or trial.get("schema_version")
                != "narrative-causality-trial-evidence/v1"
                or trial.get("project") != project
                or trial.get("chapter_id") != chapter_id
                or trial.get("status") != "pass"
                or trial.get("source_boundaries") != facts
                or not isinstance(context_bindings, list)
                or not context_bindings
                or not isinstance(candidate_binding, Mapping)
                or _artifact_issues(
                    {
                        "artifact_bindings": [
                            *context_bindings,
                            candidate_binding,
                        ]
                    },
                    project_root=project_root,
                )
            ):
                issues.append(
                    f"{stage_id}:chapter[{index}]:trial_artifact_invalid"
                )
        elif stage_id == "P3":
            steps = receipt.get("steps")
            if not isinstance(steps, Mapping):
                issues.append(f"{stage_id}:chapter[{index}]:steps_invalid")
            else:
                previous_binding: Mapping[str, Any] | None = None
                for step in _P3_STEP_SEQUENCE:
                    result = steps.get(step)
                    if (
                        not isinstance(result, Mapping)
                        or result.get("status") != "pass"
                    ):
                        issues.append(
                            f"{stage_id}:chapter[{index}]:step_not_pass:{step}"
                        )
                        continue
                    artifact_binding = result.get("artifact_binding")
                    artifact = (
                        _binding_document(
                            artifact_binding,
                            project_root=project_root,
                        )
                        if isinstance(artifact_binding, Mapping)
                        else None
                    )
                    input_bindings = (
                        artifact.get("input_bindings")
                        if isinstance(artifact, Mapping)
                        else None
                    )
                    if (
                        artifact is None
                        or artifact.get("schema_version")
                        != "narrative-production-step-evidence/v1"
                        or artifact.get("project") != project
                        or artifact.get("chapter_id") != chapter_id
                        or artifact.get("step") != step
                        or artifact.get("status") != "pass"
                        or not isinstance(input_bindings, list)
                        or not input_bindings
                        or _artifact_issues(
                            {"artifact_bindings": input_bindings},
                            project_root=project_root,
                        )
                        or (
                            previous_binding is not None
                            and not any(
                                isinstance(item, Mapping)
                                and item.get("path")
                                == previous_binding.get("path")
                                and item.get("sha256")
                                == previous_binding.get("sha256")
                                for item in input_bindings
                            )
                        )
                    ):
                        issues.append(
                            f"{stage_id}:chapter[{index}]:"
                            f"step_artifact_invalid:{step}"
                        )
                    if isinstance(artifact_binding, Mapping):
                        previous_binding = artifact_binding
        elif stage_id == "P4":
            accepted_binding = receipt.get("accepted_artifact_binding")
            accepted = (
                _binding_document(
                    accepted_binding,
                    project_root=project_root,
                )
                if isinstance(accepted_binding, Mapping)
                else None
            )
            source_bindings = (
                accepted.get("source_bindings")
                if isinstance(accepted, Mapping)
                else None
            )
            if (
                accepted is None
                or accepted.get("schema_version")
                != "narrative-accepted-chapter-evidence/v1"
                or accepted.get("project") != project
                or accepted.get("chapter_id") != chapter_id
                or accepted.get("status") != "pass"
                or not isinstance(source_bindings, list)
                or not source_bindings
                or _artifact_issues(
                    {"artifact_bindings": source_bindings},
                    project_root=project_root,
                )
            ):
                issues.append(
                    f"{stage_id}:chapter[{index}]:accepted_artifact_invalid"
                )
    if len(chapter_ids) != len(set(chapter_ids)):
        issues.append(f"{stage_id}:chapter_ids_not_unique")
    expected_ids = {
        "P2": set(range(1, 4)),
        "P3": set(range(1, 11)),
        "P4": set(range(1, 31)),
    }.get(stage_id)
    if expected_ids is not None and set(chapter_ids) != expected_ids:
        issues.append(f"{stage_id}:chapter_id_set_invalid")
    return issues


def _chapter_receipt_hashes(
    evidence: Mapping[str, Any],
    *,
    project_root: Path,
) -> dict[int, str]:
    result: dict[int, str] = {}
    bindings = evidence.get("chapter_receipts")
    if not isinstance(bindings, list):
        return result
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        document = _binding_document(binding, project_root=project_root)
        chapter_id = document.get("chapter_id") if document else None
        declared = binding.get("sha256")
        if (
            isinstance(chapter_id, int)
            and not isinstance(chapter_id, bool)
            and isinstance(declared, str)
            and _SHA256.fullmatch(declared)
        ):
            result[chapter_id] = declared
    return result


def _single_runtime_document(
    verified_attempts: list[Mapping[str, Any]],
    *,
    kind: str,
) -> Mapping[str, Any] | None:
    matches = [
        item.get("_verified_document")
        for item in verified_attempts
        if item.get("kind") == kind
    ]
    return matches[0] if len(matches) == 1 and isinstance(matches[0], Mapping) else None


def _expected_runtime_producer(
    stage_id: str,
    item: Mapping[str, Any],
) -> tuple[str, str | None, str] | None:
    kind = str(item.get("kind") or "")
    if stage_id == "P0" and kind == "blueprint_migration":
        return "blueprint-migration", None, "Scribe"
    if stage_id == "P1" and kind == "agent_registration":
        return "agent-registration", None, "Supervisor"
    if stage_id == "P2" and kind == "causality_trial":
        return (
            "causality-trial",
            "plot_causality_architect",
            "NarrativePlanner",
        )
    if stage_id == "P3":
        step = str(item.get("step") or "")
        producer = _P3_PRODUCERS.get(step)
        if producer is not None:
            return (
                f"narrative-{step.replace('_', '-')}",
                producer[0],
                producer[1],
            )
    if stage_id == "P4" and kind == "accepted_chapter":
        return "accepted-chapter", "senior_editor", "Reviewer"
    if stage_id == "P4" and kind == "drift_review":
        return "drift-review", "reader_simulation_panel", "Reviewer"
    if stage_id == "P5" and kind == "pseudoprose_stress":
        return "pseudoprose-stress", "state_projector", "Scribe"
    if stage_id == "P5" and kind == "real_model_arc":
        return "real-model-arc", "authorial_director", "Supervisor"
    if stage_id == "P5" and kind == "release_metrics":
        return "release-metrics", "state_projector", "Scribe"
    if stage_id == "P5" and kind == "metric_universe":
        return "metric-universe", "state_projector", "Scribe"
    return None


def _runtime_producer_issues(
    *,
    stage_id: str,
    item: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> list[str]:
    expected = _expected_runtime_producer(stage_id, item)
    if expected is None:
        return ["producer_contract_unknown"]
    attempt_id = str(item.get("attempt_id") or "")
    attempt = (projection.get("attempts") or {}).get(attempt_id)
    if not isinstance(attempt, Mapping):
        return ["attempt_projection_missing"]
    work_item_id = str(attempt.get("work_item_id") or "")
    work_item = (projection.get("work_items") or {}).get(work_item_id)
    if not isinstance(work_item, Mapping):
        return ["work_item_projection_missing"]
    expected_kind, expected_agent_id, expected_runtime_role = expected
    issues = []
    if work_item.get("kind") != expected_kind:
        issues.append("work_item_kind_mismatch")
    if (
        expected_agent_id is not None
        and work_item.get("assigned_agent_id") != expected_agent_id
    ):
        issues.append("producer_agent_mismatch")
    execution_contract = attempt.get("execution_contract")
    if (
        not isinstance(execution_contract, Mapping)
        or execution_contract.get("role") != expected_runtime_role
    ):
        issues.append("producer_runtime_role_mismatch")
    if item.get("work_item_id") != work_item_id:
        issues.append("work_item_identity_mismatch")
    if stage_id == "P5" and item.get("kind") == "metric_universe":
        document = item.get("_verified_document")
        producer = (
            document.get("producer")
            if isinstance(document, Mapping)
            else None
        )
        deterministic_tool = (
            execution_contract.get("deterministic_tool")
            if isinstance(execution_contract, Mapping)
            else None
        )
        if (
            not isinstance(producer, Mapping)
            or not isinstance(deterministic_tool, Mapping)
            or not isinstance(execution_contract, Mapping)
            or execution_contract.get("executor_type")
            != "deterministic_tool"
            or deterministic_tool.get("tool_id")
            != METRIC_UNIVERSE_TOOL_ID
            or deterministic_tool.get("tool_version")
            != METRIC_UNIVERSE_TOOL_VERSION
            or deterministic_tool.get("input_tree_sha256")
            != producer.get("input_tree_sha256")
            or attempt.get("status") != "succeeded"
            or (attempt.get("outcome") or {}).get("execution_origin")
            != "deterministic_tool_executor"
        ):
            issues.append("deterministic_producer_receipt_mismatch")
    return issues


def _promotion_receipt_issues(
    binding: Mapping[str, Any] | None,
    *,
    project_root: Path,
    candidate_manifest: Mapping[str, Any],
) -> list[str]:
    if not isinstance(binding, Mapping):
        return ["promotion_receipt_binding_invalid"]
    receipt = _binding_document(binding, project_root=project_root)
    if receipt is None:
        return ["promotion_receipt_unreadable"]
    issues = []
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "promoted"
        or receipt.get("production_modified") is not True
    ):
        issues.append("promotion_receipt_contract_invalid")
    candidate_set_id = candidate_manifest.get("candidate_set_id")
    candidate_set_sha256 = candidate_manifest.get("candidate_set_sha256")
    if (
        receipt.get("candidate_set_id") != candidate_set_id
        or receipt.get("candidate_set_sha256") != candidate_set_sha256
    ):
        issues.append("promotion_receipt_candidate_set_mismatch")
    approval_candidate = project_root / str(
        receipt.get("user_acceptance_receipt") or ""
    )
    try:
        approval_path = approval_candidate.resolve(strict=True)
        approval_path.relative_to(project_root)
    except (OSError, RuntimeError, ValueError):
        approval_path = project_root
    approval = (
        _read_mapping(approval_path)
        if not approval_candidate.is_symlink()
        and approval_path != project_root
        else None
    )
    try:
        ledger_approval = validate_candidate_acceptance(
            project_root,
            approval_path,
            candidate_set_id=candidate_set_id,
            candidate_set_sha256=candidate_set_sha256,
            evidence_bundle_sha256=str(
                receipt.get("evidence_bundle_sha256") or ""
            ),
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        ledger_approval = None
    if (
        approval is None
        or ledger_approval is None
        or approval.get("schema_version")
        != "narrative-user-acceptance-ledger-receipt/v1"
        or approval.get("status") != "accepted"
        or approval.get("action") != "accept_candidate_set"
        or approval.get("actor_type") != "user"
        or not str(approval.get("actor_id") or "").strip()
        or not str(approval.get("idempotency_key") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
        or approval.get("candidate_set_id") != candidate_set_id
        or approval.get("candidate_set_sha256") != candidate_set_sha256
        or approval.get("evidence_bundle_sha256")
        != receipt.get("evidence_bundle_sha256")
    ):
        issues.append("promotion_receipt_user_acceptance_invalid")
    chapters = receipt.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return [*issues, "promotion_receipt_chapters_required"]
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, Mapping):
            issues.append(f"promotion_chapter[{index}]_invalid")
            continue
        path_value = str(chapter.get("artifact_path") or "")
        sha256 = str(chapter.get("artifact_sha256") or "")
        artifact_issues = _artifact_issues(
            {
                "artifact_bindings": [
                    {"path": path_value, "sha256": sha256}
                ]
            },
            project_root=project_root,
        )
        if artifact_issues:
            issues.append(f"promotion_chapter[{index}]_artifact_invalid")
    def chapter_pairs(values: object) -> set[tuple[int, str]]:
        pairs: set[tuple[int, str]] = set()
        if not isinstance(values, list):
            return pairs
        for value in values:
            if not isinstance(value, Mapping):
                continue
            chapter_id = value.get("chapter_id")
            sha256 = value.get("artifact_sha256")
            if (
                isinstance(chapter_id, int)
                and not isinstance(chapter_id, bool)
                and isinstance(sha256, str)
                and _SHA256.fullmatch(sha256)
            ):
                pairs.add((chapter_id, sha256))
        return pairs

    expected_chapters = chapter_pairs(candidate_manifest.get("chapters"))
    observed_chapters = chapter_pairs(chapters)
    if not expected_chapters or observed_chapters != expected_chapters:
        issues.append("promotion_receipt_chapter_set_mismatch")
    index = _read_mapping(project_root / "project_artifact_index.yml")
    current_release = index.get("current_release") if index else None
    if (
        not isinstance(current_release, Mapping)
        or current_release.get("candidate_set_id") != candidate_set_id
        or current_release.get("candidate_set_sha256")
        != candidate_set_sha256
        or current_release.get("promotion_receipt")
        != binding.get("path")
    ):
        issues.append("promotion_receipt_release_index_mismatch")
    return issues


def _candidate_promotion_evidence_issues(
    manifest: Mapping[str, Any],
    *,
    agentlab_root: Path,
    project: str,
    project_root: Path,
    expected_evidence_bundle_sha256: object,
) -> list[str]:
    issues: list[str] = []
    candidate_set_sha256 = str(
        manifest.get("candidate_set_sha256") or ""
    )
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or len(chapters) < 3:
        return ["candidate_set_complete_arc_requires_three_chapters"]
    chapter_ids = [
        chapter.get("chapter_id")
        for chapter in chapters
        if isinstance(chapter, Mapping)
    ]
    if (
        len(chapter_ids) != len(chapters)
        or not chapter_ids
        or any(
            not isinstance(chapter_id, int)
            or isinstance(chapter_id, bool)
            for chapter_id in chapter_ids
        )
    ):
        issues.append("candidate_set_arc_chapters_not_contiguous")
    elif chapter_ids != list(range(chapter_ids[0], chapter_ids[0] + len(chapters))):
        issues.append("candidate_set_arc_chapters_not_contiguous")
    observed_artifact_paths: set[str] = set()
    observed_artifact_sha256: set[str] = set()
    observed_receipt_paths: set[str] = set()
    observed_attempts: set[tuple[str, str, str]] = set()
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            issues.append("candidate_set_chapter_invalid")
            continue
        if chapter.get("model_tier") != "final":
            issues.append(
                f"candidate_set_chapter_not_final:{chapter.get('chapter_id')}"
            )
        artifact_path = str(chapter.get("artifact_path") or "")
        if not artifact_path or artifact_path in observed_artifact_paths:
            issues.append(
                f"candidate_set_chapter_artifact_reused:"
                f"{chapter.get('chapter_id')}"
            )
        observed_artifact_paths.add(artifact_path)
        artifact_sha256 = str(chapter.get("artifact_sha256") or "")
        if (
            not _SHA256.fullmatch(artifact_sha256)
            or artifact_sha256 in observed_artifact_sha256
        ):
            issues.append(
                f"candidate_set_chapter_artifact_content_reused:"
                f"{chapter.get('chapter_id')}"
            )
        observed_artifact_sha256.add(artifact_sha256)
        receipt_contracts = {
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
        for field, (
            schema_version,
            work_item_kind,
            agent_id,
            runtime_role,
        ) in receipt_contracts.items():
            receipt_path_value = str(chapter.get(field) or "")
            path_candidate = project_root / receipt_path_value
            if (
                not receipt_path_value
                or receipt_path_value in observed_receipt_paths
            ):
                issues.append(
                    f"candidate_set_chapter_receipt_reused:"
                    f"{chapter.get('chapter_id')}:{field}"
                )
            observed_receipt_paths.add(receipt_path_value)
            try:
                path = path_candidate.resolve(strict=True)
                path.relative_to(project_root)
                receipt = _read_mapping(path)
            except (OSError, RuntimeError, ValueError):
                receipt = None
            if (
                path_candidate.is_symlink()
                or receipt is None
                or str(receipt.get("status") or "").lower()
                not in {"pass", "passed", "accepted", "ok"}
                or receipt.get("schema_version") != schema_version
                or receipt.get("project") != project
                or receipt.get("chapter_id") != chapter.get("chapter_id")
                or receipt.get("candidate_set_sha256")
                != candidate_set_sha256
                or receipt.get("artifact_sha256") != artifact_sha256
                or isinstance(receipt.get("blocking_count"), bool)
                or not isinstance(receipt.get("blocking_count"), int)
                or receipt.get("blocking_count") != 0
            ):
                issues.append(
                    f"candidate_set_chapter_receipt_invalid:"
                    f"{chapter.get('chapter_id')}:{field}"
                )
                continue
            task_id = str(receipt.get("task_id") or "")
            attempt_id = str(receipt.get("attempt_id") or "")
            work_item_id = str(receipt.get("work_item_id") or "")
            runtime_identity = (task_id, attempt_id, work_item_id)
            if runtime_identity in observed_attempts:
                issues.append(
                    f"candidate_set_chapter_receipt_runtime_reused:"
                    f"{chapter.get('chapter_id')}:{field}"
                )
            observed_attempts.add(runtime_identity)
            try:
                runtime = TaskRuntime(agentlab_root, project=project)
                verification = runtime.verify_attempt_execution_receipt(
                    task_id,
                    attempt_id,
                )
                projection = runtime.load_task(task_id)
                attempt = (projection.get("attempts") or {}).get(attempt_id)
                work_item = (projection.get("work_items") or {}).get(
                    work_item_id
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                verification = {}
                attempt = None
                work_item = None
            execution_contract = (
                attempt.get("execution_contract")
                if isinstance(attempt, Mapping)
                else None
            )
            if (
                not task_id
                or not attempt_id
                or not work_item_id
                or verification.get("ok") is not True
                or verification.get("output_sha256")
                != hashlib.sha256(path.read_bytes()).hexdigest()
                or receipt.get("execution_receipt_sha256")
                != verification.get("receipt_sha256")
                or receipt.get("provider")
                != verification.get("runtime_provider")
                or receipt.get("model_id") != verification.get("model_id")
                or not str(receipt.get("provider") or "").strip()
                or not str(receipt.get("model_id") or "").strip()
                or not isinstance(attempt, Mapping)
                or attempt.get("work_item_id") != work_item_id
                or not isinstance(work_item, Mapping)
                or work_item.get("kind") != work_item_kind
                or work_item.get("assigned_agent_id") != agent_id
                or not isinstance(execution_contract, Mapping)
                or execution_contract.get("role") != runtime_role
            ):
                issues.append(
                    f"candidate_set_chapter_receipt_runtime_invalid:"
                    f"{chapter.get('chapter_id')}:{field}"
                )
    try:
        observed_bundle_sha256 = evidence_bundle_sha256(
            project_root,
            manifest,
        )
    except (OSError, RuntimeError, ValueError):
        observed_bundle_sha256 = None
    if (
        observed_bundle_sha256 is None
        or observed_bundle_sha256 != expected_evidence_bundle_sha256
    ):
        issues.append("candidate_set_evidence_bundle_mismatch")
    return issues


def _state_chain_sha256(bindings: list[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            [str(binding.get("sha256") or "") for binding in bindings],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _stress_state_evidence_issues(
    stress: Mapping[str, Any],
    *,
    project: str,
    project_root: Path,
    expected_count: int,
) -> list[str]:
    bindings = stress.get("state_artifact_bindings")
    if not isinstance(bindings, list) or len(bindings) != expected_count:
        return ["state_artifact_binding_count_mismatch"]
    if any(not isinstance(binding, Mapping) for binding in bindings):
        return ["state_artifact_binding_invalid"]
    typed_bindings = [binding for binding in bindings if isinstance(binding, Mapping)]
    store_root_value = str(stress.get("state_store_root") or "")
    raw_store_root = project_root / store_root_value
    try:
        store_root = raw_store_root.resolve(strict=True)
        store_root.relative_to(project_root)
        store = NarrativeStateStore(store_root, project=project)
        live_final_projection = store.read(at_version=expected_count + 1)
    except (OSError, RuntimeError, ValueError):
        store = None
        live_final_projection = None
        issues = ["state_store_runtime_invalid"]
    else:
        issues = []
    ledger_binding = stress.get("event_ledger_binding")
    if (
        store is None
        or not isinstance(ledger_binding, Mapping)
        or _artifact_issues(
            {"artifact_bindings": [ledger_binding]},
            project_root=project_root,
        )
        or Path(str(ledger_binding.get("path") or "")).as_posix()
        != store.events_path.relative_to(project_root).as_posix()
    ):
        issues.append("state_store_event_ledger_invalid")
    issues.extend(
        f"state_{issue}"
        for issue in _artifact_issues(
            {"artifact_bindings": typed_bindings},
            project_root=project_root,
        )
    )
    chapter_ids: list[int] = []
    for index, binding in enumerate(typed_bindings):
        document = _binding_document(binding, project_root=project_root)
        if (
            document is None
            or document.get("schema_version")
            != "narrative-state-store-projection/v1"
            or document.get("project") != project
            or document.get("status") != "pass"
        ):
            issues.append(f"state_artifact_contract_invalid:{index}")
            continue
        chapter_id = document.get("chapter_id")
        if isinstance(chapter_id, bool) or not isinstance(chapter_id, int):
            issues.append(f"state_artifact_chapter_invalid:{index}")
        else:
            chapter_ids.append(chapter_id)
        projection = document.get("projection")
        try:
            live_projection = (
                store.read(at_version=chapter_id + 1)
                if store is not None
                else None
            )
        except (OSError, RuntimeError, ValueError):
            live_projection = None
        expected_projection_sha256 = (
            hashlib.sha256(
                json.dumps(
                    projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if isinstance(projection, Mapping)
            else ""
        )
        if (
            document is None
            or live_projection is None
            or projection != live_projection
            or document.get("projection_sha256")
            != expected_projection_sha256
            or (projection or {}).get("chapters", {}).get(str(chapter_id))
            is None
        ):
            issues.append(f"state_store_projection_invalid:{index}")
    if chapter_ids != list(range(1, expected_count + 1)):
        issues.append("state_artifact_chapter_sequence_invalid")
    chain_sha256 = _state_chain_sha256(typed_bindings)
    if stress.get("state_chain_sha256") != chain_sha256:
        issues.append("state_chain_sha256_mismatch")
    for field, schema_version in (
        ("recovery_receipt_binding", "narrative-state-recovery-receipt/v1"),
        ("rollback_receipt_binding", "narrative-state-rollback-receipt/v1"),
    ):
        binding = stress.get(field)
        document = (
            _binding_document(binding, project_root=project_root)
            if isinstance(binding, Mapping)
            else None
        )
        if (
            document is None
            or document.get("schema_version") != schema_version
            or document.get("project") != project
            or document.get("status") != "pass"
            or document.get("state_chain_sha256") != chain_sha256
        ):
            issues.append(f"{field}_invalid")
            continue
        active_state_path = str(document.get("active_state_path") or "")
        active_state_candidate = project_root / active_state_path
        try:
            active_state = active_state_candidate.resolve(strict=True)
            active_state.relative_to(project_root)
            active_state_sha256 = hashlib.sha256(
                active_state.read_bytes()
            ).hexdigest()
        except (OSError, RuntimeError, ValueError):
            active_state_sha256 = ""
        if (
            active_state_candidate.is_symlink()
            or not active_state_path
            or not active_state_sha256
        ):
            issues.append(f"{field}_active_state_invalid")
            continue
        if field == "recovery_receipt_binding":
            expected_binding = document.get("expected_snapshot_binding")
            recovered_binding = document.get("recovered_snapshot_binding")
            snapshot_issues = _artifact_issues(
                {
                    "artifact_bindings": [
                        expected_binding,
                        recovered_binding,
                    ]
                },
                project_root=project_root,
            )
            if (
                snapshot_issues
                or not isinstance(expected_binding, Mapping)
                or not isinstance(recovered_binding, Mapping)
                or expected_binding.get("sha256")
                != recovered_binding.get("sha256")
                or document.get("expected_snapshot_sha256")
                != expected_binding.get("sha256")
                or document.get("expected_snapshot_sha256")
                != document.get("recovered_snapshot_sha256")
                or active_state_sha256
                != document.get("recovered_snapshot_sha256")
                or not _SHA256.fullmatch(
                    str(document.get("corrupted_snapshot_sha256") or "")
                )
                or document.get("corrupted_snapshot_sha256")
                == active_state_sha256
                or not isinstance(live_final_projection, Mapping)
                or live_final_projection
                != _read_mapping(
                    project_root
                    / str(recovered_binding.get("path") or "")
                )
            ):
                issues.append("recovery_snapshot_mismatch")
        else:
            pre_change_binding = document.get("pre_change_binding")
            mutated_binding = document.get("mutated_binding")
            rollback_binding = document.get("rollback_binding")
            rollback_receipt = document.get("state_store_rollback_receipt")
            snapshot_issues = _artifact_issues(
                {
                    "artifact_bindings": [
                        pre_change_binding,
                        mutated_binding,
                        rollback_binding,
                    ]
                },
                project_root=project_root,
            )
            if (
                snapshot_issues
                or not isinstance(pre_change_binding, Mapping)
                or not isinstance(mutated_binding, Mapping)
                or not isinstance(rollback_binding, Mapping)
                or pre_change_binding.get("sha256")
                == mutated_binding.get("sha256")
                or document.get("pre_change_sha256")
                != pre_change_binding.get("sha256")
                or document.get("mutated_sha256")
                != mutated_binding.get("sha256")
                or document.get("rollback_sha256")
                != rollback_binding.get("sha256")
                or active_state_sha256
                != document.get("rollback_sha256")
                or store is None
                or document.get("rollback_chapter") != expected_count - 1
                or not isinstance(rollback_receipt, Mapping)
                or rollback_receipt.get("schema_version")
                != "narrative-state-commit-receipt/v1"
                or rollback_receipt.get("status") != "rolled_back"
                or rollback_receipt.get("target_chapter")
                != expected_count - 1
                or rollback_receipt.get("restored_state_sha256")
                != (
                    _read_mapping(
                        project_root
                        / str(pre_change_binding.get("path") or "")
                    )
                    or {}
                ).get("state_sha256")
                or _read_mapping(
                    project_root / str(rollback_binding.get("path") or "")
                )
                != store.read()
            ):
                issues.append("rollback_snapshot_mismatch")
    return issues


def _metric_calculation_value(calculation: object) -> float | None:
    if not isinstance(calculation, Mapping):
        return None
    operation = calculation.get("operation")
    numerator = calculation.get("numerator")
    if (
        isinstance(numerator, bool)
        or not isinstance(numerator, (int, float))
        or not math.isfinite(float(numerator))
    ):
        return None
    if operation == "count":
        return float(numerator)
    denominator = calculation.get("denominator")
    if (
        operation != "ratio"
        or isinstance(denominator, bool)
        or not isinstance(denominator, (int, float))
        or not math.isfinite(float(denominator))
        or float(denominator) <= 0
    ):
        return None
    return float(numerator) / float(denominator)


def _metric_subject_result(
    metric_id: str,
    subject: Mapping[str, Any],
    *,
    project: str,
    project_root: Path,
) -> object:
    schemas = {
        "hard_continuity_errors": "narrative-hard-continuity-audit/v1",
        "planted_fact_and_promise_recall": "narrative-retrieval-trace/v1",
        "state_and_retrieval_traceability": "narrative-traceability-record/v1",
        "cross_project_knowledge_leaks": "narrative-knowledge-isolation-audit/v1",
        "due_promise_resolution_rate": "narrative-promise-disposition/v1",
        "blind_preference_rate": "narrative-blind-review-vote/v1",
        "consecutive_windows_without_core_regression": (
            "narrative-window-acceptance/v1"
        ),
    }
    if (
        subject.get("schema_version") != schemas.get(metric_id)
        or subject.get("project") != project
        or subject.get("status") != "pass"
    ):
        raise ValueError("metric subject contract invalid")
    evidence_bindings = subject.get("evidence_bindings")
    if (
        not isinstance(evidence_bindings, list)
        or not evidence_bindings
        or _artifact_issues(
            {"artifact_bindings": evidence_bindings},
            project_root=project_root,
        )
    ):
        raise ValueError("metric subject evidence invalid")
    if metric_id == "hard_continuity_errors":
        findings = subject.get("blocking_findings")
        if not isinstance(findings, list):
            raise ValueError("hard continuity findings invalid")
        return len(findings)
    if metric_id == "planted_fact_and_promise_recall":
        expected_id = str(subject.get("expected_item_id") or "")
        retrieved_ids = subject.get("retrieved_item_ids")
        if not expected_id or not isinstance(retrieved_ids, list):
            raise ValueError("retrieval trace invalid")
        return expected_id in {
            str(value) for value in retrieved_ids if str(value).strip()
        }
    if metric_id == "state_and_retrieval_traceability":
        trace_bindings = [
            subject.get("state_change_binding"),
            subject.get("retrieval_evidence_binding"),
        ]
        if any(not isinstance(value, Mapping) for value in trace_bindings):
            raise ValueError("traceability bindings invalid")
        return not _artifact_issues(
            {"artifact_bindings": trace_bindings},
            project_root=project_root,
        )
    if metric_id == "cross_project_knowledge_leaks":
        namespaces = subject.get("observed_project_namespaces")
        if not isinstance(namespaces, list):
            raise ValueError("knowledge isolation namespaces invalid")
        return sum(1 for value in namespaces if value != project)
    if metric_id == "due_promise_resolution_rate":
        if subject.get("due") is not True:
            raise ValueError("promise sample is not due")
        return subject.get("disposition") in {
            "paid_off",
            "transformed",
            "explicitly_deferred",
            "retired",
        }
    if metric_id == "blind_preference_rate":
        preferred = subject.get("preferred_candidate")
        if (
            subject.get("randomized_order") is not True
            or preferred not in {"system", "baseline"}
            or not str(subject.get("voter_id") or "").strip()
        ):
            raise ValueError("blind review vote invalid")
        return preferred == "system"
    if metric_id == "consecutive_windows_without_core_regression":
        if subject.get("accepted") is not True:
            raise ValueError("window acceptance invalid")
        return 0 if subject.get("core_regression") is True else 1
    raise ValueError("metric subject type unsupported")


def _release_metric_evidence_issues(
    *,
    metric_id: str,
    value: object,
    binding: object,
    project: str,
    project_root: Path,
    verified_universe_path: str,
) -> tuple[list[str], set[str]]:
    if not isinstance(binding, Mapping):
        return ["binding_invalid"], set()
    document = _binding_document(binding, project_root=project_root)
    if (
        document is None
        or document.get("schema_version")
        != "narrative-release-metric-evidence/v1"
        or document.get("project") != project
        or document.get("metric_id") != metric_id
    ):
        return ["contract_invalid"], set()
    source_bindings = document.get("source_bindings")
    if not isinstance(source_bindings, list) or not source_bindings:
        return ["source_bindings_required"], set()
    if _artifact_issues(
        {"artifact_bindings": source_bindings},
        project_root=project_root,
    ):
        return ["source_binding_invalid"], set()
    calculation = document.get("calculation")
    source_paths: set[str] = set()
    source_operation: str | None = None
    source_samples: list[object] = []
    observed_sample_ids: set[str] = set()
    observed_subjects: set[tuple[str, str]] = set()
    declared_universe: set[tuple[str, str]] = set()
    for index, source_binding in enumerate(source_bindings):
        if not isinstance(source_binding, Mapping):
            return [f"source_contract_invalid:{index}"], source_paths
        source = _binding_document(source_binding, project_root=project_root)
        path_value = str(source_binding.get("path") or "")
        source_paths.add(path_value)
        if (
            source is None
            or source.get("schema_version")
            != "narrative-release-metric-source/v1"
            or source.get("project") != project
            or source.get("metric_id") != metric_id
            or source.get("operation") not in {"count", "ratio"}
            or not isinstance(source.get("samples"), list)
            or not source.get("samples")
        ):
            return [f"source_contract_invalid:{index}"], source_paths
        universe_binding = source.get("universe_binding")
        universe = (
            _binding_document(
                universe_binding,
                project_root=project_root,
            )
            if isinstance(universe_binding, Mapping)
            else None
        )
        universe_contract = (
            universe.get("metric_universe")
            if isinstance(universe, Mapping)
            else None
        )
        universe_subjects = (
            universe_contract.get("subject_bindings")
            if isinstance(universe_contract, Mapping)
            else None
        )
        if (
            universe is None
            or not verified_universe_path
            or str(universe_binding.get("path") or "")
            != verified_universe_path
            or universe.get("schema_version")
            != "narrative-runtime-stage-evidence/v1"
            or universe.get("kind") != "metric_universe"
            or universe.get("metric_id") != metric_id
            or not isinstance(universe_contract, Mapping)
            or universe_contract.get("schema_version")
            != "narrative-release-metric-universe/v1"
            or universe_contract.get("project") != project
            or universe_contract.get("metric_id") != metric_id
            or universe_contract.get("status") != "sealed"
            or not isinstance(universe_subjects, list)
            or not universe_subjects
            or _artifact_issues(
                {"artifact_bindings": universe_subjects},
                project_root=project_root,
            )
            or metric_universe_issues(project_root, universe)
        ):
            return [f"source_universe_invalid:{index}"], source_paths
        for subject_binding in universe_subjects:
            if not isinstance(subject_binding, Mapping):
                return [f"source_universe_invalid:{index}"], source_paths
            subject_identity = (
                str(subject_binding.get("path") or ""),
                str(subject_binding.get("sha256") or ""),
            )
            if subject_identity in declared_universe:
                return ["source_universe_subject_reused"], source_paths
            declared_universe.add(subject_identity)
        operation = str(source.get("operation"))
        if source_operation is not None and source_operation != operation:
            return ["source_operation_mismatch"], source_paths
        source_operation = operation
        for sample_index, sample in enumerate(source["samples"]):
            if not isinstance(sample, Mapping):
                return ["source_samples_invalid"], source_paths
            sample_id = str(sample.get("sample_id") or "")
            evidence_binding = sample.get("evidence_binding")
            sample_evidence = (
                _binding_document(
                    evidence_binding,
                    project_root=project_root,
                )
                if isinstance(evidence_binding, Mapping)
                else None
            )
            subject_binding = (
                sample_evidence.get("subject_binding")
                if isinstance(sample_evidence, Mapping)
                else None
            )
            subject = (
                _binding_document(
                    subject_binding,
                    project_root=project_root,
                )
                if isinstance(subject_binding, Mapping)
                else None
            )
            try:
                derived_sample_result = (
                    _metric_subject_result(
                        metric_id,
                        subject,
                        project=project,
                        project_root=project_root,
                    )
                    if isinstance(subject, Mapping)
                    else None
                )
            except (TypeError, ValueError):
                derived_sample_result = None
            subject_identity = (
                str(
                    subject_binding.get("path") or ""
                    if isinstance(subject_binding, Mapping)
                    else ""
                ),
                str(
                    subject_binding.get("sha256") or ""
                    if isinstance(subject_binding, Mapping)
                    else ""
                ),
            )
            if (
                not sample_id
                or sample_id in observed_sample_ids
                or sample_evidence is None
                or sample_evidence.get("schema_version")
                != "narrative-release-metric-sample/v1"
                or sample_evidence.get("project") != project
                or sample_evidence.get("metric_id") != metric_id
                or sample_evidence.get("sample_id") != sample_id
                or sample_evidence.get("status") != "pass"
                or not str(
                    sample_evidence.get("subject_locator") or ""
                ).strip()
                or not isinstance(subject_binding, Mapping)
                or sample_evidence.get("subject_locator")
                != subject_binding.get("path")
                or sample_evidence.get("subject_sha256")
                != subject_binding.get("sha256")
                or derived_sample_result is None
                or derived_sample_result != sample.get("result")
                or sample_evidence.get("result") != sample.get("result")
                or subject_identity in observed_subjects
            ):
                return [
                    f"source_sample_evidence_invalid:{index}:{sample_index}"
                ], source_paths
            observed_sample_ids.add(sample_id)
            observed_subjects.add(subject_identity)
            source_samples.append(sample["result"])
    if observed_subjects != declared_universe:
        return ["source_sample_universe_mismatch"], source_paths
    if source_operation == "count":
        if any(
            isinstance(sample, bool)
            or not isinstance(sample, (int, float))
            or not math.isfinite(float(sample))
            or float(sample) < 0
            for sample in source_samples
        ):
            return ["source_samples_invalid"], source_paths
        derived_calculation: Mapping[str, Any] = {
            "operation": "count",
            "numerator": sum(float(sample) for sample in source_samples),
        }
    elif source_operation == "ratio":
        if any(not isinstance(sample, bool) for sample in source_samples):
            return ["source_samples_invalid"], source_paths
        derived_calculation = {
            "operation": "ratio",
            "numerator": sum(1 for sample in source_samples if sample),
            "denominator": len(source_samples),
        }
    else:
        return ["source_operation_invalid"], source_paths
    computed = _metric_calculation_value(derived_calculation)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or calculation != derived_calculation
        or computed is None
        or not math.isclose(computed, float(value), rel_tol=0.0, abs_tol=1e-12)
        or document.get("value") != value
    ):
        return ["calculation_mismatch"], source_paths
    return [], source_paths


def _stage_evidence_issues(
    stage_id: str,
    receipt: Mapping[str, Any],
    *,
    agentlab_root: Path,
    project: str,
    project_root: Path,
    validated_outputs: dict[str, Any] | None = None,
) -> list[str]:
    bindings = receipt.get("artifact_bindings")
    stage_bindings = (
        [
            binding
            for binding in bindings
            if isinstance(binding, Mapping)
            and binding.get("evidence_kind") == "stage_evidence"
        ]
        if isinstance(bindings, list)
        else []
    )
    if len(stage_bindings) != 1:
        return [f"{stage_id}:stage_evidence_binding_required"]
    binding = stage_bindings[0]
    evidence = _binding_document(binding, project_root=project_root)
    if evidence is None:
        return [f"{stage_id}:stage_evidence_unreadable"]
    expected_schema = f"narrative-{stage_id.lower()}-evidence/v1"
    issues: list[str] = []
    if (
        binding.get("schema_version") != expected_schema
        or evidence.get("schema_version") != expected_schema
    ):
        issues.append(f"{stage_id}:stage_evidence_schema_invalid")
    if evidence.get("project") != project:
        issues.append(f"{stage_id}:stage_evidence_project_mismatch")
    if evidence.get("stage") != stage_id:
        issues.append(f"{stage_id}:stage_evidence_stage_mismatch")
    if evidence.get("status") != "pass":
        issues.append(f"{stage_id}:stage_evidence_not_pass")
    if issues:
        return issues

    runtime_attempts = evidence.get("runtime_attempts")
    if not isinstance(runtime_attempts, list) or not runtime_attempts:
        return [f"{stage_id}:runtime_attempts_required"]
    runtime = TaskRuntime(agentlab_root, project=project)
    verified_attempts: list[Mapping[str, Any]] = []
    observed_attempts: set[tuple[str, str]] = set()
    for index, raw in enumerate(runtime_attempts):
        if not isinstance(raw, Mapping):
            issues.append(f"{stage_id}:runtime_attempt[{index}]:invalid")
            continue
        task_id = str(raw.get("task_id") or "")
        attempt_id = str(raw.get("attempt_id") or "")
        identity = (task_id, attempt_id)
        if not task_id or not attempt_id or identity in observed_attempts:
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:identity_invalid"
            )
            continue
        observed_attempts.add(identity)
        try:
            verification = runtime.verify_attempt_execution_receipt(
                task_id,
                attempt_id,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:verification_failed:"
                f"{type(exc).__name__}"
            )
            continue
        artifact = raw.get("artifact")
        artifact_issues = _artifact_issues(
            {"artifact_bindings": [artifact]},
            project_root=project_root,
        )
        document = (
            _binding_document(artifact, project_root=project_root)
            if isinstance(artifact, Mapping)
            else None
        )
        if artifact_issues or document is None:
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:artifact_invalid"
            )
            continue
        semantic_fields = (
            "kind",
            "chapter_id",
            "step",
            "work_item_id",
        )
        if (
            document.get("schema_version")
            != "narrative-runtime-stage-evidence/v1"
            or document.get("project") != project
            or document.get("stage") != stage_id
            or document.get("status") != "pass"
            or document.get("task_id") != task_id
            or document.get("attempt_id") != attempt_id
            or any(document.get(field) != raw.get(field) for field in semantic_fields)
        ):
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:artifact_semantics_mismatch"
            )
            continue
        if (
            verification.get("ok") is not True
            or not isinstance(artifact, Mapping)
            or verification.get("output_sha256") != artifact.get("sha256")
        ):
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:verification_output_mismatch"
            )
            continue
        try:
            projection = runtime.load_task(task_id)
        except (OSError, RuntimeError, ValueError) as exc:
            issues.append(
                f"{stage_id}:runtime_attempt[{index}]:projection_failed:"
                f"{type(exc).__name__}"
            )
            continue
        verified_item = {
            **dict(raw),
            "_verified_document": document,
        }
        producer_issues = _runtime_producer_issues(
            stage_id=stage_id,
            item=verified_item,
            projection=projection,
        )
        if producer_issues:
            issues.extend(
                f"{stage_id}:runtime_attempt[{index}]:{issue}"
                for issue in producer_issues
            )
            continue
        verified_attempts.append(
            {
                **verified_item,
                "_verification": verification,
            }
        )
    if issues:
        return issues

    if stage_id == "P0":
        migration = _single_runtime_document(
            verified_attempts,
            kind="blueprint_migration",
        )
        if migration is None:
            issues.append("P0:blueprint_migration_runtime_attempt_required")
            migration = {}
        if migration.get("authoritative_chapter_range") != [1, 25]:
            issues.append("P0:authoritative_chapter_range_must_be_1_25")
        if migration.get("current_planning_window_count") != 1:
            issues.append("P0:current_planning_window_count_must_be_one")
        if migration.get("double_current_count") != 0:
            issues.append("P0:double_current_count_must_be_zero")
        if migration.get("legacy_seal_status") != "superseded":
            issues.append("P0:legacy_seal_not_superseded")
        try:
            blueprint_validation = validate_crown_blueprint(
                agentlab_root,
                project=project,
                chapter_start=1,
                chapter_end=25,
            )
        except (OSError, RuntimeError, ValueError):
            blueprint_validation = {"status": "blocked"}
        if (
            blueprint_validation.get("status") != "pass"
            or blueprint_validation.get("chapter_range") != [1, 25]
        ):
            issues.append("P0:deterministic_blueprint_validation_not_pass")
        try:
            planning_validation = validate_current_planning_window(
                agentlab_root,
                project=project,
            )
        except (OSError, RuntimeError, ValueError):
            planning_validation = {"status": "blocked"}
        if (
            planning_validation.get("status") != "pass"
            or planning_validation.get("current_count") != 1
            or planning_validation.get("double_current_count") != 0
            or planning_validation.get("legacy_seal_status")
            != "superseded"
            or planning_validation.get("locked_chapters")
            != list(range(1, 11))
            or planning_validation.get("horizon_chapters")
            != list(range(11, 26))
        ):
            issues.append(
                "P0:deterministic_planning_window_validation_not_pass"
            )
    elif stage_id == "P1":
        registration = _single_runtime_document(
            verified_attempts,
            kind="agent_registration",
        )
        if registration is None:
            issues.append("P1:agent_registration_runtime_attempt_required")
            registration = {}
        if registration.get("registered_agent_count") != 13:
            issues.append("P1:registered_agent_count_must_be_13")
        namespaces = registration.get("private_knowledge_namespaces")
        if (
            not isinstance(namespaces, list)
            or len(namespaces) != 13
            or len(set(str(item) for item in namespaces)) != 13
        ):
            issues.append("P1:private_knowledge_namespaces_must_be_13_unique")
        if registration.get("atomic_registration") is not True:
            issues.append("P1:atomic_registration_required")
        for field in ("role_dag_audit", "project_truth_audit"):
            value = registration.get(field)
            if not isinstance(value, Mapping) or value.get("status") != "pass":
                issues.append(f"P1:{field}_not_pass")
        try:
            truth = ProjectTruthStore(project_root)
            canonical_audit = truth.audit()
            canonical_manifests = ProjectAgentRegistry(truth).list(
                include_archived=False
            )
            author_team_contract = load_author_team_contract(agentlab_root)
            author_team_contract["project_id"] = project
            expected_manifests = build_author_team_manifests(
                author_team_contract
            )
            professional_contract_matches = [
                manifest.to_dict() for manifest in canonical_manifests
            ] == [manifest.to_dict() for manifest in expected_manifests]
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            canonical_audit = {"status": "fail"}
            canonical_manifests = []
            professional_contract_matches = False
        canonical_namespaces = [
            str(manifest.knowledge_binding.get("namespace") or "")
            for manifest in canonical_manifests
        ]
        canonical_role_ids = {
            manifest.id for manifest in canonical_manifests
        }
        dependency_graph = {
            manifest.id: tuple(
                str(item)
                for item in (
                    manifest.collaboration.get("dependencies") or []
                )
            )
            for manifest in canonical_manifests
        }
        dag_valid = all(
            dependency in canonical_role_ids
            for dependencies in dependency_graph.values()
            for dependency in dependencies
        )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(role_id: str) -> bool:
            if role_id in visited:
                return True
            if role_id in visiting:
                return False
            visiting.add(role_id)
            if not all(
                visit(dependency)
                for dependency in dependency_graph.get(role_id, ())
            ):
                return False
            visiting.remove(role_id)
            visited.add(role_id)
            return True

        dag_valid = dag_valid and all(
            visit(role_id) for role_id in canonical_role_ids
        )
        knowledge_store = KnowledgeStore(agentlab_root)
        if (
            canonical_audit.get("status") != "pass"
            or len(canonical_manifests) != 13
            or canonical_role_ids != set(REQUIRED_AUTHOR_ROLES)
            or not professional_contract_matches
            or any(
                manifest.status != "active"
                for manifest in canonical_manifests
            )
            or not dag_valid
            or len(set(canonical_namespaces)) != 13
            or set(canonical_namespaces) != set(str(item) for item in namespaces)
            or not all(
                knowledge_store.space_exists(namespace)
                for namespace in canonical_namespaces
            )
            or knowledge_store.inactive_spaces(canonical_namespaces)
        ):
            issues.append("P1:canonical_team_state_validation_not_pass")
    elif stage_id == "P2":
        issues.extend(
            _chapter_receipt_issues(
                evidence,
                project=project,
                project_root=project_root,
                count=3,
                schema_version="narrative-chapter-trial-receipt/v1",
                stage_id=stage_id,
            )
        )
        receipt_hashes = _chapter_receipt_hashes(
            evidence,
            project_root=project_root,
        )
        runtime_chapters = {
            item.get("chapter_id")
            for item in verified_attempts
            if item.get("kind") == "causality_trial"
        }
        if runtime_chapters != {1, 2, 3}:
            issues.append("P2:three_verified_runtime_chapters_required")
        for item in verified_attempts:
            if item.get("kind") != "causality_trial":
                continue
            chapter_id = item.get("chapter_id")
            document = item["_verified_document"]
            expected_receipt_sha256 = receipt_hashes.get(chapter_id)
            receipt_document = next(
                (
                    _binding_document(
                        chapter_binding,
                        project_root=project_root,
                    )
                    for chapter_binding in evidence.get("chapter_receipts") or []
                    if isinstance(chapter_binding, Mapping)
                    and (
                        _binding_document(
                            chapter_binding,
                            project_root=project_root,
                        )
                        or {}
                    ).get("chapter_id")
                    == chapter_id
                ),
                None,
            )
            if (
                expected_receipt_sha256 is None
                or document.get("chapter_receipt_sha256")
                != expected_receipt_sha256
                or not isinstance(receipt_document, Mapping)
                or document.get("trial_artifact_binding")
                != receipt_document.get("trial_artifact_binding")
            ):
                issues.append(
                    f"P2:chapter[{chapter_id}]:verified_artifact_chain_mismatch"
                )
            facts = document.get("source_boundaries")
            if not isinstance(facts, Mapping):
                issues.append(
                    f"P2:chapter[{chapter_id}]:verified_source_boundaries_invalid"
                )
                continue
            for field in (
                "guesses_committed_as_facts",
                "abilities_without_sources",
                "knowledge_without_sources",
            ):
                if facts.get(field) != 0:
                    issues.append(
                        f"P2:chapter[{chapter_id}]:verified_{field}_not_zero"
                    )
    elif stage_id == "P3":
        issues.extend(
            _chapter_receipt_issues(
                evidence,
                project=project,
                project_root=project_root,
                count=10,
                schema_version="narrative-production-loop-receipt/v1",
                stage_id=stage_id,
            )
        )
        receipt_hashes = _chapter_receipt_hashes(
            evidence,
            project_root=project_root,
        )
        runtime_steps = {
            (item.get("chapter_id"), item.get("step"))
            for item in verified_attempts
        }
        expected_steps = {
            (chapter_id, step)
            for chapter_id in range(1, 11)
            for step in _P3_STEPS
        }
        if runtime_steps != expected_steps:
            issues.append("P3:ten_chapter_runtime_step_matrix_incomplete")
        for item in verified_attempts:
            chapter_id = item.get("chapter_id")
            expected_receipt_sha256 = receipt_hashes.get(chapter_id)
            receipt_document = next(
                (
                    _binding_document(
                        chapter_binding,
                        project_root=project_root,
                    )
                    for chapter_binding in evidence.get("chapter_receipts") or []
                    if isinstance(chapter_binding, Mapping)
                    and (
                        _binding_document(
                            chapter_binding,
                            project_root=project_root,
                        )
                        or {}
                    ).get("chapter_id")
                    == chapter_id
                ),
                None,
            )
            expected_step_binding = (
                (receipt_document.get("steps") or {})
                .get(item.get("step"), {})
                .get("artifact_binding")
                if isinstance(receipt_document, Mapping)
                and isinstance(receipt_document.get("steps"), Mapping)
                else None
            )
            if (
                expected_receipt_sha256 is None
                or item["_verified_document"].get(
                    "chapter_receipt_sha256"
                )
                != expected_receipt_sha256
                or item["_verified_document"].get(
                    "step_artifact_binding"
                )
                != expected_step_binding
            ):
                issues.append(
                    f"P3:chapter[{chapter_id}]:verified_artifact_chain_mismatch"
                )
    elif stage_id == "P4":
        issues.extend(
            _chapter_receipt_issues(
                evidence,
                project=project,
                project_root=project_root,
                count=30,
                schema_version="narrative-accepted-chapter-receipt/v1",
                stage_id=stage_id,
            )
        )
        receipt_hashes = _chapter_receipt_hashes(
            evidence,
            project_root=project_root,
        )
        drift_review = _single_runtime_document(
            verified_attempts,
            kind="drift_review",
        )
        if drift_review is None:
            issues.append("P4:drift_review_runtime_attempt_required")
            drift_review = {}
        drift = drift_review.get("drift_checks")
        if not isinstance(drift, Mapping):
            issues.append("P4:drift_checks_invalid")
        else:
            for check_id in sorted(_P4_DRIFT_CHECKS):
                value = drift.get(check_id)
                if not isinstance(value, Mapping) or value.get("status") != "pass":
                    issues.append(f"P4:drift_check_not_pass:{check_id}")
        expected_samples: set[tuple[str, str]] = set()
        for chapter_binding in evidence.get("chapter_receipts") or []:
            chapter_receipt = (
                _binding_document(
                    chapter_binding,
                    project_root=project_root,
                )
                if isinstance(chapter_binding, Mapping)
                else None
            )
            accepted_binding = (
                chapter_receipt.get("accepted_artifact_binding")
                if isinstance(chapter_receipt, Mapping)
                else None
            )
            if isinstance(accepted_binding, Mapping):
                expected_samples.add(
                    (
                        str(accepted_binding.get("path") or ""),
                        str(accepted_binding.get("sha256") or ""),
                    )
                )
        sample_bindings = drift_review.get("sample_bindings")
        observed_samples = {
            (
                str(binding.get("path") or ""),
                str(binding.get("sha256") or ""),
            )
            for binding in sample_bindings
            if isinstance(binding, Mapping)
        } if isinstance(sample_bindings, list) else set()
        if (
            not isinstance(sample_bindings, list)
            or _artifact_issues(
                {"artifact_bindings": sample_bindings},
                project_root=project_root,
            )
            or len(expected_samples) != 30
            or observed_samples != expected_samples
        ):
            issues.append("P4:drift_review_sample_bindings_invalid")
        runtime_chapters = {
            item.get("chapter_id")
            for item in verified_attempts
            if item.get("kind") == "accepted_chapter"
        }
        if runtime_chapters != set(range(1, 31)):
            issues.append("P4:thirty_verified_runtime_chapters_required")
        for item in verified_attempts:
            if item.get("kind") != "accepted_chapter":
                continue
            chapter_id = item.get("chapter_id")
            expected_receipt_sha256 = receipt_hashes.get(chapter_id)
            receipt_document = next(
                (
                    _binding_document(
                        chapter_binding,
                        project_root=project_root,
                    )
                    for chapter_binding in evidence.get("chapter_receipts") or []
                    if isinstance(chapter_binding, Mapping)
                    and (
                        _binding_document(
                            chapter_binding,
                            project_root=project_root,
                        )
                        or {}
                    ).get("chapter_id")
                    == chapter_id
                ),
                None,
            )
            if (
                expected_receipt_sha256 is None
                or item["_verified_document"].get(
                    "chapter_receipt_sha256"
                )
                != expected_receipt_sha256
                or not isinstance(receipt_document, Mapping)
                or item["_verified_document"].get(
                    "accepted_artifact_binding"
                )
                != receipt_document.get("accepted_artifact_binding")
            ):
                issues.append(
                    f"P4:chapter[{chapter_id}]:verified_artifact_chain_mismatch"
                )
    elif stage_id == "P5":
        stress = _single_runtime_document(
            verified_attempts,
            kind="pseudoprose_stress",
        )
        arc_output = _single_runtime_document(
            verified_attempts,
            kind="real_model_arc",
        )
        metric_output = _single_runtime_document(
            verified_attempts,
            kind="release_metrics",
        )
        if stress is None:
            issues.append("P5:pseudoprose_stress_runtime_attempt_required")
            stress = {}
        if arc_output is None:
            issues.append("P5:real_model_arc_runtime_attempt_required")
            arc_output = {}
        if metric_output is None:
            issues.append("P5:release_metrics_runtime_attempt_required")
            metric_output = {}
        count = stress.get("pseudoprose_chapter_count")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 100 <= count <= 500
        ):
            issues.append("P5:pseudoprose_chapter_count_out_of_range")
        elif isinstance(stress, Mapping):
            issues.extend(
                f"P5:pseudoprose_{issue}"
                for issue in _stress_state_evidence_issues(
                    stress,
                    project=project,
                    project_root=project_root,
                    expected_count=count,
                )
            )
        arc = arc_output.get("real_model_arc")
        if not isinstance(arc, Mapping) or arc.get("status") != "pass":
            issues.append("P5:real_model_arc_not_pass")
        else:
            arc_attempt = next(
                (
                    item
                    for item in verified_attempts
                    if item.get("kind") == "real_model_arc"
                ),
                {},
            )
            arc_verification = arc_attempt.get("_verification") or {}
            if (
                not str(arc.get("provider") or "").strip()
                or arc.get("provider")
                != arc_verification.get("runtime_provider")
                or not str(arc_verification.get("model_id") or "").strip()
            ):
                issues.append("P5:real_model_arc_provider_model_mismatch")
            for field, hash_field in (
                ("run_binding", "run_sha256"),
                ("artifact_binding", "artifact_sha256"),
                ("promotion_receipt_binding", "promotion_receipt_sha256"),
            ):
                binding = arc.get(field)
                binding_issues = _artifact_issues(
                    {"artifact_bindings": [binding]},
                    project_root=project_root,
                )
                if binding_issues:
                    issues.append(f"P5:real_model_arc_{field}_invalid")
                elif (
                    not isinstance(binding, Mapping)
                    or arc.get(hash_field) != binding.get("sha256")
                ):
                    issues.append(
                        f"P5:real_model_arc_{hash_field}_mismatch"
                    )
            run_document = (
                _binding_document(
                    arc.get("run_binding"),
                    project_root=project_root,
                )
                if isinstance(arc.get("run_binding"), Mapping)
                else None
            )
            if (
                run_document is None
                or run_document.get("schema_version")
                != "narrative-real-model-arc-run/v1"
                or run_document.get("status") != "pass"
                or run_document.get("project") != project
                or run_document.get("task_id") != arc_attempt.get("task_id")
                or run_document.get("attempt_id")
                != arc_attempt.get("attempt_id")
                or run_document.get("provider")
                != arc_verification.get("runtime_provider")
                or run_document.get("model_id")
                != arc_verification.get("model_id")
            ):
                issues.append("P5:real_model_arc_run_contract_invalid")
            artifact_binding = arc.get("artifact_binding")
            artifact_document = (
                _binding_document(
                    artifact_binding,
                    project_root=project_root,
                )
                if isinstance(artifact_binding, Mapping)
                else None
            )
            artifact_path = (
                project_root / str(artifact_binding.get("path") or "")
                if isinstance(artifact_binding, Mapping)
                else project_root
            )
            try:
                candidate_validation = (
                    validate_candidate_set(project_root, artifact_path)
                    if artifact_document is not None
                    else {"status": "stale"}
                )
            except (OSError, RuntimeError, ValueError):
                candidate_validation = {"status": "stale"}
            if (
                artifact_document is None
                or candidate_validation.get("status") != "pass"
                or arc.get("candidate_set_sha256")
                != artifact_document.get("candidate_set_sha256")
                or (
                    run_document is not None
                    and run_document.get("candidate_set_sha256")
                    != artifact_document.get("candidate_set_sha256")
                )
            ):
                issues.append(
                    "P5:real_model_arc_candidate_set_contract_invalid"
                )
            promotion_document = (
                _binding_document(
                    arc.get("promotion_receipt_binding"),
                    project_root=project_root,
                )
                if isinstance(
                    arc.get("promotion_receipt_binding"),
                    Mapping,
                )
                else None
            )
            if artifact_document is not None:
                issues.extend(
                    f"P5:real_model_arc_{issue}"
                    for issue in _candidate_promotion_evidence_issues(
                        artifact_document,
                        agentlab_root=agentlab_root,
                        project=project,
                        project_root=project_root,
                        expected_evidence_bundle_sha256=(
                            promotion_document or {}
                        ).get("evidence_bundle_sha256"),
                    )
                )
                manifest_chapters = artifact_document.get("chapters")
                manifest_ids = [
                    chapter.get("chapter_id")
                    for chapter in manifest_chapters
                    if isinstance(chapter, Mapping)
                ] if isinstance(manifest_chapters, list) else []
                if (
                    run_document is None
                    or run_document.get("chapter_start")
                    != (manifest_ids[0] if manifest_ids else None)
                    or run_document.get("chapter_end")
                    != (manifest_ids[-1] if manifest_ids else None)
                    or run_document.get("chapter_count") != len(manifest_ids)
                ):
                    issues.append(
                        "P5:real_model_arc_run_chapter_range_mismatch"
                    )
            promotion_issues = _promotion_receipt_issues(
                arc.get("promotion_receipt_binding"),
                project_root=project_root,
                candidate_manifest=artifact_document or {},
            )
            issues.extend(
                f"P5:real_model_arc_{issue}"
                for issue in promotion_issues
            )
        release_metrics = metric_output.get("release_metrics")
        if not isinstance(release_metrics, Mapping):
            issues.append("P5:verified_release_metrics_required")
        else:
            metric_evidence = metric_output.get("metric_evidence")
            if (
                not isinstance(metric_evidence, Mapping)
                or set(metric_evidence) != set(release_metrics)
            ):
                issues.append("P5:release_metric_evidence_set_invalid")
            else:
                verified_universe_paths = {
                    str(item["_verified_document"].get("metric_id") or ""): str(
                        (item.get("artifact") or {}).get("path") or ""
                    )
                    for item in verified_attempts
                    if item.get("kind") == "metric_universe"
                    and isinstance(item.get("_verified_document"), Mapping)
                }
                observed_source_paths: set[str] = set()
                for metric_id, value in release_metrics.items():
                    binding = metric_evidence.get(metric_id)
                    metric_issues, source_paths = (
                        _release_metric_evidence_issues(
                            metric_id=str(metric_id),
                            value=value,
                            binding=binding,
                            project=project,
                            project_root=project_root,
                            verified_universe_path=verified_universe_paths.get(
                                str(metric_id),
                                "",
                            ),
                        )
                    )
                    if metric_issues:
                        issues.append(
                            "P5:release_metric_evidence_invalid:"
                            f"{metric_id}:{','.join(metric_issues)}"
                        )
                    if observed_source_paths.intersection(source_paths):
                        issues.append(
                            f"P5:release_metric_source_reused:{metric_id}"
                        )
                    observed_source_paths.update(source_paths)
            if not any(
                issue.startswith("P5:release_metric")
                for issue in issues
            ) and validated_outputs is not None:
                validated_outputs["release_metrics"] = dict(release_metrics)
    return issues


def _metric_pass(value: object, rule: Mapping[str, Any]) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    threshold = rule.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return False
    operator = rule.get("operator")
    if operator == "eq":
        return float(value) == float(threshold)
    if operator == "gte":
        return float(value) >= float(threshold)
    return False


def build_narrative_acceptance_status(
    agentlab_root: Path,
    *,
    project: str,
    project_root: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    """Verify staged receipts and refuse full-scale claims before P5."""

    root = Path(agentlab_root).resolve()
    raw_project = Path(project_root)
    raw_receipts = Path(evidence_dir)
    selected_project = raw_project.resolve()
    receipts = raw_receipts.resolve()
    expected_project = (root / "projects" / project).resolve()
    if (
        not _PROJECT_ID.fullmatch(project)
        or raw_project.is_symlink()
        or raw_receipts.is_symlink()
        or selected_project != expected_project
    ):
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["project_root_binding_invalid"],
        }
    config_path = root / "config" / "narrative_acceptance_ladder.yml"
    config = _read_mapping(config_path)
    if (
        config is None
        or config.get("schema_version")
        != "narrative-acceptance-ladder/v1"
    ):
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["acceptance_ladder_config_invalid"],
        }
    try:
        receipts.relative_to(selected_project)
    except ValueError:
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["evidence_dir_outside_project"],
        }

    stage_config = config.get("stages")
    if not isinstance(stage_config, Mapping) or tuple(stage_config) != _STAGES:
        return {
            "schema_version": "narrative-acceptance-status/v1",
            "project": project,
            "status": "blocked",
            "issues": ["acceptance_stage_config_invalid"],
        }

    stages: list[dict[str, Any]] = []
    chain_open = True
    validated_outputs: dict[str, Any] = {}
    for stage_id in _STAGES:
        receipt_path = receipts / f"{stage_id}.yml"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            stages.append(
                {
                    "stage": stage_id,
                    "status": (
                        "blocked" if receipt_path.is_symlink() else "missing"
                    ),
                    "receipt_path": str(receipt_path),
                    "issues": [
                        "receipt_symlink_forbidden"
                        if receipt_path.is_symlink()
                        else "receipt_missing"
                    ],
                }
            )
            chain_open = False
            continue
        receipt = _read_mapping(receipt_path)
        issues: list[str] = []
        if receipt is None:
            issues.append("receipt_invalid")
            receipt = {}
        if receipt.get("schema_version") != "narrative-acceptance-receipt/v1":
            issues.append("receipt_schema_invalid")
        if receipt.get("project") != project:
            issues.append("receipt_project_mismatch")
        if receipt.get("stage") != stage_id:
            issues.append("receipt_stage_mismatch")
        if receipt.get("status") != "pass":
            issues.append("receipt_not_pass")
        required = stage_config[stage_id].get("required_checks")
        checks = receipt.get("checks")
        if not isinstance(required, list) or not isinstance(checks, Mapping):
            issues.append("required_checks_invalid")
        else:
            for check_id in required:
                check = checks.get(check_id)
                if not isinstance(check, Mapping) or check.get("status") != "pass":
                    issues.append(f"required_check_not_pass:{check_id}")
        issues.extend(_artifact_issues(receipt, project_root=selected_project))
        issues.extend(
            _stage_evidence_issues(
                stage_id,
                receipt,
                agentlab_root=root,
                project=project,
                project_root=selected_project,
                validated_outputs=validated_outputs,
            )
        )
        if not chain_open:
            issues.append("prior_stage_not_pass")
        status = "pass" if not issues else "blocked"
        if status != "pass":
            chain_open = False
        stages.append(
            {
                "stage": stage_id,
                "status": status,
                "receipt_path": str(receipt_path),
                "receipt_sha256": hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
                "issues": issues,
            }
        )

    passed = [item["stage"] for item in stages if item["status"] == "pass"]
    highest_completed = passed[-1] if passed else None
    metrics = validated_outputs.get("release_metrics")
    metric_rules = config.get("release_metrics")
    metric_results: dict[str, bool] = {}
    if isinstance(metrics, Mapping) and isinstance(metric_rules, Mapping):
        metric_results = {
            metric_id: _metric_pass(metrics.get(metric_id), rule)
            for metric_id, rule in metric_rules.items()
            if isinstance(rule, Mapping)
        }
    metrics_pass = (
        isinstance(metric_rules, Mapping)
        and len(metric_results) == len(metric_rules)
        and all(metric_results.values())
    )
    full_scale_ready = (
        all(item["status"] == "pass" for item in stages) and metrics_pass
    )
    return {
        "schema_version": "narrative-acceptance-status/v1",
        "project": project,
        "status": "pass" if full_scale_ready else "incomplete",
        "stages": stages,
        "highest_completed_stage": highest_completed,
        "release_metrics": metric_results,
        "release_metrics_pass": metrics_pass,
        "full_scale_production_ready": full_scale_ready,
        "claim_1980_chapter_capability_allowed": full_scale_ready,
        "issues": [] if full_scale_ready else ["P5_not_fully_accepted"],
    }
