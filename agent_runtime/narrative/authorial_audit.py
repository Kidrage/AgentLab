"""Professional authorial audit planning and finding contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
import math
import re

import yaml

from agent_runtime.narrative.author_team import (
    load_author_team_contract,
    select_author_team,
)
from agent_runtime.narrative.quality.revision import (
    compile_scene_revision_contract,
)
from agent_runtime.narrative.role_context import RETRIEVAL_ORDER
from agent_runtime.project_agents import (
    AgentContract,
    ProjectAgentRegistry,
    effective_contract_hash,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import (
    EntityAlreadyExists,
    EntityNotFound,
    RoleAttemptExecutor,
    TaskRuntime,
)

HARD_AUDIT_CHECKS = (
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

_SOFT_REVIEW_DIMENSIONS = {
    "plot_causality_architect": ("causality", "foreshadow_enablement"),
    "character_ensemble_director": (
        "character_motive",
        "knowledge_and_false_belief",
        "offstage_action",
    ),
    "relationship_director": (
        "relationship_progression",
        "consent_and_agency",
    ),
    "world_archaeologist": ("world_semantics", "environmental_history"),
    "foreshadow_mystery_keeper": (
        "promise_state",
        "mystery_fairness",
    ),
    "research_style_curator": (
        "craft_device_fit",
        "originality_and_source_rights",
    ),
    "reader_simulation_panel": (
        "reader_promise",
        "emotional_effect",
        "position_bias_check",
    ),
}
_REVIEWER_ROLES = frozenset(
    {"canon_timeline_steward", *_SOFT_REVIEW_DIMENSIONS}
)
_FINDING_TEXT_FIELDS = (
    "finding_id",
    "target_scene",
    "problem_type",
    "evidence_locator",
    "evidence",
    "counterinterpretation",
    "revision_target",
)
_FINDING_SCOPES = frozenset({"line", "paragraph", "scene", "chapter"})
_FINDING_CLASSIFICATIONS = frozenset(
    {"hard_error", "aesthetic_disagreement"}
)
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def _resolve_run_candidate(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    candidate_path: Path,
) -> tuple[Path | None, list[str]]:
    if not _PROJECT_ID.fullmatch(project):
        return None, ["project_id_invalid"]
    if not _TASK_ID.fullmatch(task_id):
        return None, ["task_id_invalid"]
    root = Path(agentlab_root).resolve()
    project_root = root / "projects" / project
    if project_root.is_symlink() or not project_root.is_dir():
        return None, ["project_root_invalid"]
    selected = Path(candidate_path)
    if selected.is_symlink():
        return None, ["candidate_symlink_forbidden"]
    candidate = selected.resolve()
    artifacts = (
        project_root.resolve() / "runs" / task_id / "artifacts"
    )
    try:
        relative = candidate.relative_to(artifacts)
    except ValueError:
        return None, ["candidate_not_run_artifact"]
    if not relative.parts or not candidate.is_file():
        return None, ["candidate_not_found"]
    return candidate, []


def validate_authorial_review_finding(
    finding: Mapping[str, object],
) -> list[str]:
    """Validate one evidence-rich hard or soft professional review finding."""

    issues: list[str] = []
    if finding.get("schema_version") != "authorial-review-finding/v1":
        issues.append("unsupported_finding_schema")
    reviewer_role = str(finding.get("reviewer_role") or "")
    if reviewer_role not in _REVIEWER_ROLES:
        issues.append(f"reviewer_role_not_allowed:{reviewer_role}")
    chapter_id = finding.get("chapter_id")
    if (
        isinstance(chapter_id, bool)
        or not isinstance(chapter_id, int)
        or chapter_id <= 0
    ):
        issues.append("chapter_id_must_be_positive")
    for field in _FINDING_TEXT_FIELDS:
        value = finding.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{field}_required")
    classification = str(finding.get("classification") or "")
    if classification not in _FINDING_CLASSIFICATIONS:
        issues.append(f"classification_invalid:{classification}")
    confidence = finding.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        issues.append("confidence_must_be_between_zero_and_one")
    scope = str(finding.get("minimal_revision_scope") or "")
    if scope not in _FINDING_SCOPES:
        issues.append(f"minimal_revision_scope_invalid:{scope}")
    strengths = finding.get("preserve_strengths")
    if (
        not isinstance(strengths, list)
        or not strengths
        or not all(
            isinstance(item, str) and item.strip() for item in strengths
        )
    ):
        issues.append("preserve_strengths_required")
    candidate_sha256 = finding.get("candidate_sha256")
    if (
        not isinstance(candidate_sha256, str)
        or len(candidate_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in candidate_sha256
        )
    ):
        issues.append("candidate_sha256_invalid")
    return issues


def build_authorial_audit_plan(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    chapter_id: int,
    candidate_path: Path,
    risk_flags: Sequence[str],
) -> dict[str, Any]:
    """Bind mandatory hard checks and risk-triggered reviewers to a candidate."""

    if chapter_id <= 0:
        return {"status": "blocked", "issues": ["chapter_id_must_be_positive"]}
    candidate, candidate_issues = _resolve_run_candidate(
        agentlab_root,
        project=project,
        task_id=task_id,
        candidate_path=candidate_path,
    )
    if candidate is None:
        return {"status": "blocked", "issues": candidate_issues}
    try:
        contract = load_author_team_contract(Path(agentlab_root))
    except ValueError as exc:
        return {
            "status": "blocked",
            "issues": [f"author_team_contract_invalid:{exc}"],
        }
    selection = select_author_team(contract, risk_flags=risk_flags)
    if selection["status"] != "pass":
        return {"status": "blocked", "issues": selection["issues"]}

    active_roles = set(selection["active_roles"])
    soft_reviews = [
        {
            "reviewer_role": role_id,
            "dimensions": list(dimensions),
        }
        for role_id, dimensions in _SOFT_REVIEW_DIMENSIONS.items()
        if role_id in active_roles
    ]
    identity: dict[str, Any] = {
        "schema_version": "authorial-audit-plan/v1",
        "project": project,
        "task_id": task_id,
        "chapter_id": chapter_id,
        "candidate": {
            "path": str(candidate),
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        },
        "risk_flags": sorted(set(str(item) for item in risk_flags)),
        "active_roles": selection["active_roles"],
        "hard_audit": {
            "reviewer_role": "canon_timeline_steward",
            "checks": list(HARD_AUDIT_CHECKS),
        },
        "soft_reviews": soft_reviews,
        "senior_editor_role": "senior_editor",
        "revision_attempt_limit": 2,
        "escalation_role": "authorial_director",
        "blind_review": {
            "required_after_revision": True,
            "anonymous": True,
            "order": "hash_randomized",
            "reviewer_role": "reader_simulation_panel",
        },
        "execution_bindings": {
            "revision_attempt_reservation": (
                "agent_runtime.narrative.production.revision_attempts."
                "reserve_revision_attempt"
            ),
            "blind_ab_preflight": (
                "agent_runtime.narrative.quality.live_editor_preflight."
                "preflight_literary_ab_review"
            ),
            "blind_ab_execution": (
                "agent_runtime.narrative.quality.live_editor_runtime."
                "run_literary_ab_review"
            ),
            "blind_ab_finalization": (
                "agent_runtime.narrative.quality.live_editor."
                "finalize_literary_ab_review"
            ),
            "professional_review_execution": (
                "agent_runtime.narrative.authorial_audit."
                "execute_authorial_reviews"
            ),
        },
        "authority_bindings": contract["authority_bindings"],
    }
    plan_sha256 = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **identity,
        "status": "pass",
        "plan_sha256": plan_sha256,
        "issues": [],
    }


def _review_output_issues(
    output: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    reviewer_role: str,
    dimensions: Sequence[str] | None,
    allowed_evidence_locators: set[str],
) -> list[str]:
    issues: list[str] = []
    for field, expected in (
        ("schema_version", "authorial-review-output/v1"),
        ("status", "pass"),
        ("project", plan["project"]),
        ("task_id", plan["task_id"]),
        ("chapter_id", plan["chapter_id"]),
        ("reviewer_role", reviewer_role),
        ("candidate_sha256", plan["candidate"]["sha256"]),
    ):
        if output.get(field) != expected:
            issues.append(f"review_output_{field}_mismatch")
    findings = output.get("findings")
    if not isinstance(findings, list):
        issues.append("review_output_findings_must_be_list")
    else:
        for index, finding in enumerate(findings):
            if not isinstance(finding, Mapping):
                issues.append(f"review_output_finding[{index}]_invalid")
                continue
            issues.extend(
                f"review_output_finding[{index}]:{issue}"
                for issue in validate_authorial_review_finding(finding)
            )
            if finding.get("reviewer_role") != reviewer_role:
                issues.append(
                    f"review_output_finding[{index}]:reviewer_role_mismatch"
                )
            if (
                finding.get("chapter_id") != plan["chapter_id"]
                or finding.get("candidate_sha256")
                != plan["candidate"]["sha256"]
            ):
                issues.append(
                    f"review_output_finding[{index}]:candidate_identity_mismatch"
                )
            locator_path = str(
                finding.get("evidence_locator") or ""
            ).split(":", 1)[0]
            if locator_path not in allowed_evidence_locators:
                issues.append(
                    f"review_output_finding[{index}]:"
                    "evidence_locator_not_in_context"
                )
    if reviewer_role == "canon_timeline_steward":
        results = output.get("hard_check_results")
        if not isinstance(results, Mapping) or set(results) != set(
            HARD_AUDIT_CHECKS
        ):
            issues.append("review_output_hard_check_matrix_invalid")
        else:
            for check_id in HARD_AUDIT_CHECKS:
                result = results.get(check_id)
                if (
                    not isinstance(result, Mapping)
                    or result.get("status") not in {"pass", "fail"}
                    or not str(result.get("evidence_locator") or "").strip()
                ):
                    issues.append(
                        f"review_output_hard_check_invalid:{check_id}"
                    )
                elif str(result["evidence_locator"]).split(
                    ":",
                    1,
                )[0] not in allowed_evidence_locators:
                    issues.append(
                        f"review_output_hard_check_locator_not_in_context:"
                        f"{check_id}"
                    )
    elif list(output.get("dimensions_reviewed") or []) != list(
        dimensions or ()
    ):
        issues.append("review_output_dimensions_mismatch")
    return issues


def _load_review_context_pack(
    *,
    project_root: Path,
    task_id: str,
    role_id: str,
    manifest: Any,
    context_pack_path: Path,
    chapter_id: int,
    candidate_path: Path,
    candidate_sha256: str,
    authority_bindings: Mapping[str, Any],
) -> tuple[Path | None, set[str], list[str]]:
    expected_root = (
        project_root / "runs" / task_id / "artifacts" / "role_context"
    ).resolve()
    selected = Path(context_pack_path)
    if selected.is_symlink():
        return None, set(), ["review_context_pack_symlink_forbidden"]
    try:
        pack_path = selected.resolve(strict=True)
        pack_path.relative_to(expected_root)
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    except (
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
    ):
        return None, set(), ["review_context_pack_invalid"]
    if not isinstance(pack, Mapping):
        return None, set(), ["review_context_pack_invalid"]
    declared_sha256 = pack.get("pack_sha256")
    identity = {
        key: value for key, value in pack.items() if key != "pack_sha256"
    }
    observed_sha256 = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    issues: list[str] = []
    for field, expected in (
        ("schema_version", "role-context-pack/v1"),
        ("project", project_root.name),
        ("task_id", task_id),
        ("role_id", role_id),
    ):
        if pack.get(field) != expected:
            issues.append(f"review_context_pack_{field}_mismatch")
    audit_target = pack.get("audit_target")
    expected_candidate_relative = candidate_path.relative_to(
        project_root
    ).as_posix()
    if (
        not isinstance(audit_target, Mapping)
        or audit_target.get("chapter_id") != chapter_id
        or audit_target.get("candidate_path") != expected_candidate_relative
        or audit_target.get("candidate_sha256") != candidate_sha256
    ):
        issues.append("review_context_pack_audit_target_mismatch")
    if declared_sha256 != observed_sha256:
        issues.append("review_context_pack_sha256_mismatch")
    if pack_path.name != f"{role_id}-{observed_sha256[:24]}.yml":
        issues.append("review_context_pack_filename_identity_mismatch")
    if pack.get("evidence_sufficient") is not True:
        issues.append("review_context_pack_evidence_insufficient")
    evidence = pack.get("selected_evidence")
    if not isinstance(evidence, list) or not evidence:
        issues.append("review_context_pack_selected_evidence_required")
        evidence = []
    allowed_namespaces = set(
        str(item)
        for item in (
            manifest.knowledge_binding.get("namespaces") or []
        )
    )
    if pack.get("knowledge_namespaces") != list(
        manifest.knowledge_binding.get("namespaces") or []
    ):
        issues.append("review_context_pack_namespace_contract_mismatch")
    if pack.get("retrieval_order") != list(RETRIEVAL_ORDER):
        issues.append("review_context_pack_retrieval_order_invalid")
    retrieval_execution = pack.get("retrieval_execution")
    if (
        not isinstance(retrieval_execution, Mapping)
        or retrieval_execution.get("compiler_performs_retrieval") is not False
        or retrieval_execution.get("external_transfer") != "forbidden"
        or retrieval_execution.get("candidate_source")
        != "caller_provided_hash_bound_candidates"
    ):
        issues.append("review_context_pack_retrieval_execution_invalid")
    if pack.get("authority_bindings") != authority_bindings:
        issues.append("review_context_pack_authority_binding_mismatch")
    omitted = pack.get("omitted_evidence")
    if not isinstance(omitted, list):
        issues.append("review_context_pack_omissions_invalid")
    token_usage = pack.get("token_usage")
    minimum = pack.get("minimum_evidence_items")
    if (
        not isinstance(token_usage, Mapping)
        or isinstance(token_usage.get("budget"), bool)
        or not isinstance(token_usage.get("budget"), int)
        or token_usage.get("budget", 0) <= 0
        or not isinstance(token_usage.get("used"), int)
        or not isinstance(token_usage.get("remaining"), int)
        or token_usage.get("remaining")
        != token_usage.get("budget") - token_usage.get("used")
        or token_usage.get("estimator") != "ceil_utf8_bytes_div_4"
        or isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum <= 0
        or len(evidence) < minimum
    ):
        issues.append("review_context_pack_budget_contract_invalid")
    bundle_binding = pack.get("context_bundle")
    bundle_inventory: dict[str, str] = {}
    if not isinstance(bundle_binding, Mapping):
        issues.append("review_context_pack_bundle_binding_invalid")
    else:
        bundle_source = project_root / str(bundle_binding.get("path") or "")
        bundle: Mapping[str, Any] = {}
        bundle_bytes = b""
        bundle_valid = False
        try:
            bundle_path = bundle_source.resolve(strict=True)
            bundle_path.relative_to(
                project_root / "runs" / task_id / "artifacts"
            )
            bundle_bytes = bundle_path.read_bytes()
            loaded_bundle = yaml.safe_load(
                bundle_bytes.decode("utf-8")
            ) or {}
            if isinstance(loaded_bundle, Mapping):
                bundle = loaded_bundle
                bundle_valid = True
        except (
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            yaml.YAMLError,
        ):
            bundle_valid = False
        if (
            bundle_source.is_symlink()
            or not bundle_valid
            or bundle_binding.get("sha256")
            != hashlib.sha256(bundle_bytes).hexdigest()
        ):
            issues.append("review_context_pack_bundle_binding_invalid")
        else:
            if (
                bundle_binding.get("context_bundle_id")
                != bundle.get("context_bundle_id")
                or chapter_id not in (bundle.get("chapter_window") or [])
            ):
                issues.append("review_context_pack_bundle_identity_mismatch")
            records = list(bundle.get("shared_files") or [])
            role_records = bundle.get("role_specific_files") or {}
            records.extend(role_records.get(role_id) or [])
            for record in records:
                if isinstance(record, Mapping):
                    bundle_inventory[str(record.get("path") or "")] = str(
                        record.get("sha256") or ""
                    )
    candidate_inventory = pack.get("candidate_inventory")
    if not isinstance(candidate_inventory, list) or not candidate_inventory:
        issues.append("review_context_pack_candidate_inventory_invalid")
        candidate_inventory = []
    stage_index = {
        stage: index for index, stage in enumerate(RETRIEVAL_ORDER)
    }
    normalized_inventory: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_inventory):
        if not isinstance(item, Mapping):
            issues.append(f"review_context_candidate[{index}]_invalid")
            continue
        relative = str(item.get("path") or "")
        stage = str(item.get("retrieval_stage") or "")
        namespace = str(item.get("namespace") or "")
        source = project_root / relative
        try:
            payload = source.resolve(strict=True).read_bytes()
        except (OSError, RuntimeError):
            issues.append(f"review_context_candidate[{index}]_unreadable")
            continue
        expected_tokens = max(1, (len(payload) + 3) // 4)
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            score = float("nan")
        if (
            source.is_symlink()
            or stage not in stage_index
            or namespace not in allowed_namespaces
            or item.get("sha256")
            != hashlib.sha256(payload).hexdigest()
            or item.get("bytes") != len(payload)
            or item.get("estimated_tokens") != expected_tokens
            or bundle_inventory.get(relative) != item.get("sha256")
            or not math.isfinite(score)
        ):
            issues.append(f"review_context_candidate[{index}]_binding_invalid")
            continue
        normalized_inventory.append(
            {
                **dict(item),
                "path": relative,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": score,
                "required": bool(item.get("required", False)),
                "estimated_tokens": expected_tokens,
            }
        )
    sorted_inventory = sorted(
        normalized_inventory,
        key=lambda item: (
            stage_index[item["retrieval_stage"]],
            not item["required"],
            -item["score"],
            item["path"],
        ),
    )
    if normalized_inventory != sorted_inventory:
        issues.append("review_context_candidate_order_invalid")
    expected_selected_paths: list[str] = []
    expected_omitted: list[dict[str, str]] = []
    expected_used_tokens = 0
    if isinstance(minimum, int) and isinstance(token_usage, Mapping):
        budget = token_usage.get("budget")
        if isinstance(budget, int):
            for item in sorted_inventory:
                if (
                    item["retrieval_stage"] == "reflective"
                    and len(expected_selected_paths) >= minimum
                ):
                    expected_omitted.append(
                        {
                            "path": item["path"],
                            "namespace": item["namespace"],
                            "retrieval_stage": item["retrieval_stage"],
                            "reason": "reflective_retrieval_not_needed",
                        }
                    )
                    continue
                if (
                    expected_used_tokens + item["estimated_tokens"]
                    > budget
                ):
                    if item["required"]:
                        issues.append(
                            "review_context_required_evidence_over_budget"
                        )
                    expected_omitted.append(
                        {
                            "path": item["path"],
                            "namespace": item["namespace"],
                            "retrieval_stage": item["retrieval_stage"],
                            "reason": "token_budget_exceeded",
                        }
                    )
                    continue
                expected_selected_paths.append(item["path"])
                expected_used_tokens += item["estimated_tokens"]
    selected_paths = [
        str(item.get("path") or "")
        for item in evidence
        if isinstance(item, Mapping)
    ]
    if selected_paths != expected_selected_paths:
        issues.append("review_context_selected_evidence_algorithm_mismatch")
    if omitted != expected_omitted:
        issues.append("review_context_omission_algorithm_mismatch")
    if (
        isinstance(token_usage, Mapping)
        and token_usage.get("used") != expected_used_tokens
    ):
        issues.append("review_context_token_usage_mismatch")
    inventory_by_path = {
        item["path"]: item for item in sorted_inventory
    }
    allowed_locators: set[str] = set()
    observed_namespaces: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            issues.append(f"review_context_evidence[{index}]_invalid")
            continue
        relative = str(item.get("path") or "")
        namespace = str(item.get("namespace") or "")
        source = project_root / relative
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(project_root)
        except (OSError, RuntimeError, ValueError):
            issues.append(f"review_context_evidence[{index}]_path_invalid")
            continue
        if (
            source.is_symlink()
            or not Path(relative).parts
            or Path(relative).parts[0] not in {"production", "project_brain"}
        ):
            issues.append(f"review_context_evidence[{index}]_not_canonical")
            continue
        payload = resolved.read_bytes()
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(f"review_context_evidence[{index}]_not_utf8")
            continue
        if (
            item.get("sha256")
            != hashlib.sha256(payload).hexdigest()
            or item.get("content") != decoded
        ):
            issues.append(f"review_context_evidence[{index}]_hash_mismatch")
        inventory_item = inventory_by_path.get(relative)
        if inventory_item is None or any(
            item.get(field) != inventory_item.get(field)
            for field in (
                "namespace",
                "retrieval_stage",
                "score",
                "required",
                "bytes",
                "estimated_tokens",
                "sha256",
            )
        ):
            issues.append(
                f"review_context_evidence[{index}]_inventory_mismatch"
            )
        if bundle_inventory.get(relative) != item.get("sha256"):
            issues.append(
                f"review_context_evidence[{index}]_bundle_binding_mismatch"
            )
        if namespace not in allowed_namespaces:
            issues.append(
                f"review_context_evidence[{index}]_namespace_forbidden"
            )
        observed_namespaces.add(namespace)
        allowed_locators.add(relative)
    if role_id == "canon_timeline_steward":
        required_hard_namespaces = {
            "canon",
            "timeline",
            "character_knowledge",
        }
        missing = sorted(required_hard_namespaces - observed_namespaces)
        issues.extend(
            f"review_context_hard_namespace_missing:{namespace}"
            for namespace in missing
        )
    if issues:
        return None, set(), issues
    return pack_path, allowed_locators, []


def execute_authorial_reviews(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    chapter_id: int,
    candidate_path: Path,
    risk_flags: Sequence[str],
    context_pack_paths: Mapping[str, Path],
    outbound_expires_at: str | None = None,
    execution_ordinal: int = 1,
    task_runtime: Any | None = None,
    attempt_executor: Any | None = None,
) -> dict[str, Any]:
    """Execute mandatory and risk-triggered reviews as verified Attempts."""

    plan = build_authorial_audit_plan(
        agentlab_root,
        project=project,
        task_id=task_id,
        chapter_id=chapter_id,
        candidate_path=candidate_path,
        risk_flags=risk_flags,
    )
    if plan.get("status") != "pass":
        return plan
    if (
        isinstance(execution_ordinal, bool)
        or not isinstance(execution_ordinal, int)
        or not 1 <= execution_ordinal <= 2
    ):
        return {
            "status": "blocked",
            "issues": ["review_execution_ordinal_must_be_1_or_2"],
        }
    if attempt_executor is None and not str(outbound_expires_at or "").strip():
        return {
            "status": "blocked",
            "issues": ["review_outbound_expires_at_required"],
        }
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
    truth = ProjectTruthStore(project_root)
    truth_audit = truth.audit()
    if truth_audit.get("status") != "pass":
        return {
            "status": "blocked",
            "issues": ["project_truth_audit_not_pass"],
        }
    snapshot = truth.current()
    registry = ProjectAgentRegistry(truth)
    review_specs = [
        {
            "reviewer_role": plan["hard_audit"]["reviewer_role"],
            "dimensions": None,
            "checks": plan["hard_audit"]["checks"],
        },
        *plan["soft_reviews"],
    ]
    manifests = {}
    context_packs: dict[str, Path] = {}
    allowed_locators: dict[str, set[str]] = {}
    try:
        for spec in review_specs:
            role_id = str(spec["reviewer_role"])
            manifest = registry.get(role_id)
            AgentContract(manifest).assert_active()
            manifests[role_id] = manifest
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "blocked",
            "issues": [f"reviewer_agent_binding_invalid:{exc}"],
        }
    expected_roles = set(manifests)
    if set(context_pack_paths) != expected_roles:
        return {
            "status": "blocked",
            "issues": ["review_context_pack_role_set_mismatch"],
        }
    for role_id, manifest in manifests.items():
        pack_path, locators, pack_issues = _load_review_context_pack(
            project_root=project_root,
            task_id=task_id,
            role_id=role_id,
            manifest=manifest,
            context_pack_path=context_pack_paths[role_id],
            chapter_id=chapter_id,
            candidate_path=Path(plan["candidate"]["path"]),
            candidate_sha256=str(plan["candidate"]["sha256"]),
            authority_bindings=plan["authority_bindings"],
        )
        if pack_path is None:
            return {
                "status": "blocked",
                "issues": [
                    f"{role_id}:{issue}" for issue in pack_issues
                ],
            }
        context_packs[role_id] = pack_path
        allowed_locators[role_id] = {
            Path(plan["candidate"]["path"]).name,
            *locators,
        }
    execution_identity = {
        "plan_sha256": plan["plan_sha256"],
        "execution_ordinal": execution_ordinal,
        "context_pack_sha256": {
            role_id: hashlib.sha256(path.read_bytes()).hexdigest()
            for role_id, path in sorted(context_packs.items())
        },
    }
    execution_sha256 = hashlib.sha256(
        json.dumps(
            execution_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    runtime = task_runtime or TaskRuntime(root, project=project)
    try:
        runtime.load_task(task_id)
    except EntityNotFound:
        return {
            "status": "blocked",
            "issues": ["governed_task_runtime_task_required"],
        }

    work_items = []
    for spec in review_specs:
        role_id = str(spec["reviewer_role"])
        manifest = manifests[role_id]
        execution_key = execution_sha256[:16]
        work_items.append(
            {
                "work_item_id": (
                    f"audit-c{chapter_id:03d}-{execution_key}-"
                    f"{role_id.replace('_', '-')}"
                ),
                "job_id": "job-main",
                "kind": "authorial-review",
                "title": f"Review chapter {chapter_id} as {role_id}",
                "depends_on": [],
                "assigned_agent_id": role_id,
                "agent_manifest_revision": manifest.manifest_revision,
                "canonical_snapshot_id": snapshot.snapshot_id,
                "effective_contract_hash": effective_contract_hash(manifest),
            }
        )
    execution_key = execution_sha256[:16]
    batch_id = f"audit-c{chapter_id:03d}-{execution_key}-reviewers"
    projection = runtime.load_task(task_id)
    existing_items = projection.get("work_items") or {}
    already_present = [
        item for item in work_items if item["work_item_id"] in existing_items
    ]
    if already_present and len(already_present) != len(work_items):
        return {
            "status": "blocked",
            "issues": ["authorial_review_work_item_partial_collision"],
        }
    if already_present:
        binding_fields = (
            "assigned_agent_id",
            "agent_manifest_revision",
            "canonical_snapshot_id",
            "effective_contract_hash",
        )
        if any(
            any(
                existing_items[item["work_item_id"]].get(field)
                != item.get(field)
                for field in binding_fields
            )
            for item in work_items
        ):
            return {
                "status": "blocked",
                "issues": ["authorial_review_work_item_binding_mismatch"],
            }
    else:
        try:
            runtime.create_work_items(
                task_id,
                batch_id=batch_id,
                items=work_items,
                idempotency_key=f"authorial-audit-work:{execution_sha256}",
            )
        except EntityAlreadyExists:
            return {
                "status": "blocked",
                "issues": ["authorial_review_work_item_collision"],
            }

    executor = attempt_executor or RoleAttemptExecutor(root, project=project)
    executions: list[dict[str, Any]] = []
    findings: list[Mapping[str, Any]] = []
    hard_gate_status = "pass"
    for spec, work_item in zip(review_specs, work_items):
        role_id = str(spec["reviewer_role"])
        attempt_id = (
            f"attempt-audit-c{chapter_id:03d}-{execution_key}-"
            f"{role_id.replace('_', '-')}"
        )
        requirements = (
            {"hard_checks": list(spec["checks"])}
            if role_id == "canon_timeline_steward"
            else {"dimensions": list(spec["dimensions"])}
        )
        outbound_request = None
        if outbound_expires_at is not None:
            outbound_request = {
                "purpose": (
                    f"Authorial review of chapter {chapter_id} as {role_id}."
                ),
                "minimal_fragment": Path(
                    plan["candidate"]["path"]
                ).read_text(
                    encoding="utf-8"
                ),
                "expires_at": outbound_expires_at,
                "role": role_id,
            }
        result = executor.execute(
            task_id=task_id,
            work_item_id=work_item["work_item_id"],
            attempt_id=attempt_id,
            role=manifests[role_id].runtime_role,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only YAML using authorial-review-output/v1. "
                        "Findings must cite evidence, confidence, a counter-"
                        "interpretation, minimal revision scope, and strengths "
                        "to preserve. Never approve or mutate the candidate."
                    ),
                },
                {
                    "role": "user",
                    "content": yaml.safe_dump(
                        {
                            "project": project,
                            "task_id": task_id,
                            "chapter_id": chapter_id,
                            "reviewer_role": role_id,
                            "candidate_sha256": plan["candidate"]["sha256"],
                            "requirements": requirements,
                        },
                        sort_keys=False,
                    ),
                },
            ],
            source_paths=[
                Path(plan["candidate"]["path"]),
                context_packs[role_id],
            ],
            external_context_request=outbound_request,
            idempotency_key=(
                f"authorial-audit-execute:{execution_sha256}:{role_id}"
            ),
        )
        expected_output = (
            project_root
            / "runtime"
            / "tasks"
            / task_id
            / "attempt_logs"
            / attempt_id
            / "output.md"
        )
        output_path = Path(str(result.get("output_path") or ""))
        if (
            output_path.is_symlink()
            or not output_path.is_file()
            or output_path.resolve() != expected_output.resolve()
        ):
            return {
                "status": "blocked",
                "issues": [f"review_output_path_invalid:{role_id}"],
            }
        verification = runtime.verify_attempt_execution_receipt(
            task_id,
            attempt_id,
        )
        output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if (
            verification.get("ok") is not True
            or verification.get("output_sha256") != output_sha256
        ):
            return {
                "status": "blocked",
                "issues": [f"review_attempt_verification_failed:{role_id}"],
            }
        try:
            output = yaml.safe_load(
                output_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            output = {}
        if not isinstance(output, Mapping):
            output = {}
        output_issues = _review_output_issues(
            output,
            plan=plan,
            reviewer_role=role_id,
            dimensions=spec.get("dimensions"),
            allowed_evidence_locators=allowed_locators[role_id],
        )
        if output_issues:
            return {
                "status": "blocked",
                "issues": [
                    f"{role_id}:{issue}" for issue in output_issues
                ],
            }
        if role_id == "canon_timeline_steward" and any(
            result.get("status") == "fail"
            for result in output["hard_check_results"].values()
        ):
            hard_gate_status = "blocked"
        if any(
            finding.get("classification") == "hard_error"
            for finding in output["findings"]
        ):
            hard_gate_status = "blocked"
        findings.extend(output["findings"])
        executions.append(
            {
                "reviewer_role": role_id,
                "work_item_id": work_item["work_item_id"],
                "attempt_id": attempt_id,
                "runtime_role": manifests[role_id].runtime_role,
                "output_path": str(output_path),
                "output_sha256": output_sha256,
                "receipt_sha256": verification.get("receipt_sha256"),
                "finding_count": len(output["findings"]),
            }
        )
    return {
        "schema_version": "authorial-review-execution/v1",
        "status": "pass" if hard_gate_status == "pass" else "blocked",
        "project": project,
        "task_id": task_id,
        "chapter_id": chapter_id,
        "candidate": plan["candidate"],
        "plan_sha256": plan["plan_sha256"],
        "execution_sha256": execution_sha256,
        "execution_ordinal": execution_ordinal,
        "context_packs": {
            role_id: {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for role_id, path in context_packs.items()
        },
        "hard_gate_status": hard_gate_status,
        "executions": executions,
        "findings": [dict(item) for item in findings],
        "project_truth_audit": truth_audit,
        "issues": (
            []
            if hard_gate_status == "pass"
            else ["hard_authorial_audit_failed"]
        ),
    }


def _deduplicated_strings(values: Sequence[object]) -> list[str]:
    return list(
        dict.fromkeys(
            text
            for value in values
            if (text := str(value).strip())
        )
    )


def compile_senior_editor_revision_contracts(
    findings: Sequence[Mapping[str, object]],
    *,
    agentlab_root: Path,
    project: str,
    task_id: str,
    candidate_path: Path,
    constraints: Mapping[str, object],
) -> dict[str, Any]:
    """Merge strict reviewer findings into executable scene-level contracts."""

    candidate, candidate_issues = _resolve_run_candidate(
        agentlab_root,
        project=project,
        task_id=task_id,
        candidate_path=candidate_path,
    )
    if candidate is None:
        return {"status": "blocked", "issues": candidate_issues}
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if not findings:
        return {"status": "blocked", "issues": ["review_findings_required"]}

    issues: list[str] = []
    for index, finding in enumerate(findings):
        issues.extend(
            f"finding[{index}]:{issue}"
            for issue in validate_authorial_review_finding(finding)
        )
        if finding.get("candidate_sha256") != candidate_sha256:
            issues.append(f"finding[{index}]:candidate_sha256_mismatch")
    if issues:
        return {"status": "blocked", "issues": issues}
    triggering_audit_sha256 = hashlib.sha256(
        json.dumps(
            [dict(finding) for finding in findings],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    list_fields = (
        "must_preserve",
        "causal_requirements",
        "character_knowledge_before",
        "character_knowledge_after",
        "forbidden_regressions",
    )
    scalar_fields = ("allowed_freedom", "decision_cost", "new_information")
    normalized_constraints: dict[str, Any] = {}
    for field in list_fields:
        value = constraints.get(field)
        if not isinstance(value, list):
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized = _deduplicated_strings(value)
        if not normalized:
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized_constraints[field] = normalized
    for field in scalar_fields:
        value = constraints.get(field)
        if not isinstance(value, str) or not value.strip():
            return {
                "status": "blocked",
                "issues": [f"constraint_{field}_required"],
            }
        normalized_constraints[field] = value.strip()

    grouped: dict[tuple[int, str], list[Mapping[str, object]]] = {}
    for finding in findings:
        key = (int(finding["chapter_id"]), str(finding["target_scene"]))
        grouped.setdefault(key, []).append(finding)

    contracts: list[dict[str, object]] = []
    for (chapter_id, target_scene), scene_findings in grouped.items():
        evidence_lines = [
            (
                f"{finding['reviewer_role']} "
                f"({float(finding['confidence']):.2f}) "
                f"{finding['evidence_locator']}: {finding['evidence']} "
                f"Counterinterpretation: {finding['counterinterpretation']}"
            )
            for finding in scene_findings
        ]
        merged = {
            "chapter_id": chapter_id,
            "target_scene": target_scene,
            "problem_type": " + ".join(
                _deduplicated_strings(
                    [finding["problem_type"] for finding in scene_findings]
                )
            ),
            "evidence": "\n".join(evidence_lines),
            "revision_target": str(scene_findings[0]["revision_target"]),
        }
        preserve_strengths = _deduplicated_strings(
            [
                *normalized_constraints["must_preserve"],
                *(
                    strength
                    for finding in scene_findings
                    for strength in finding["preserve_strengths"]
                ),
            ]
        )
        contract = compile_scene_revision_contract(
            merged,
            must_preserve=preserve_strengths,
            allowed_freedom=normalized_constraints["allowed_freedom"],
            causal_requirements=normalized_constraints["causal_requirements"],
            character_knowledge_before=normalized_constraints[
                "character_knowledge_before"
            ],
            character_knowledge_after=normalized_constraints[
                "character_knowledge_after"
            ],
            decision_cost=normalized_constraints["decision_cost"],
            new_information=normalized_constraints["new_information"],
            forbidden_regressions=normalized_constraints[
                "forbidden_regressions"
            ],
        )
        contract["must_change"] = _deduplicated_strings(
            [finding["revision_target"] for finding in scene_findings]
        )
        contract["rewrite_scope"] = (
            "chapter"
            if any(
                finding["minimal_revision_scope"] == "chapter"
                for finding in scene_findings
            )
            else "scene"
        )
        contract["compiled_by"] = "senior_editor"
        contract["candidate_sha256"] = candidate_sha256
        contract["source_candidate_sha256"] = candidate_sha256
        contract["triggering_audit_sha256"] = triggering_audit_sha256
        contract["finding_classification"] = (
            "hard_error"
            if any(
                finding["classification"] == "hard_error"
                for finding in scene_findings
            )
            else "aesthetic_disagreement"
        )
        contract["review_evidence"] = [
            {
                field: finding[field]
                for field in (
                    "finding_id",
                    "reviewer_role",
                    "classification",
                    "evidence_locator",
                    "confidence",
                    "counterinterpretation",
                    "minimal_revision_scope",
                )
            }
            for finding in scene_findings
        ]
        contract.pop("revision_contract_id", None)
        contract["revision_contract_id"] = "rev-" + hashlib.sha256(
            json.dumps(
                contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        contracts.append(contract)

    result_identity = {
        "schema_version": "senior-editor-revision-set/v1",
        "project": project,
        "task_id": task_id,
        "candidate": {
            "path": str(candidate),
            "sha256": candidate_sha256,
        },
        "triggering_audit_sha256": triggering_audit_sha256,
        "compiled_by": "senior_editor",
        "revision_attempt_limit": 2,
        "escalation_role": "authorial_director",
        "blind_ab_required": True,
        "execution_bindings": {
            "revision_attempt_reservation": (
                "agent_runtime.narrative.production.revision_attempts."
                "reserve_revision_attempt"
            ),
            "blind_ab_execution": (
                "agent_runtime.narrative.quality.live_editor_runtime."
                "run_literary_ab_review"
            ),
        },
        "contracts": contracts,
    }
    return {
        **result_identity,
        "status": "pass",
        "revision_set_sha256": hashlib.sha256(
            json.dumps(
                result_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "issues": [],
    }
