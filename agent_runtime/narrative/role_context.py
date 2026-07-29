"""Role-scoped, evidence-bound narrative context packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
import math
import re

import yaml

from atomic_io import atomic_write_yaml
from agent_runtime.narrative.author_team import load_author_team_contract
from agent_runtime.narrative.craft_cards import validate_craft_card

RETRIEVAL_ORDER = (
    "hard_fact",
    "graph_adjacent",
    "semantic",
    "reflective",
)
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_CANONICAL_INPUT_ROOTS = frozenset({"production", "project_brain"})


def _blocked(*issues: str) -> dict[str, Any]:
    return {
        "schema_version": "role-context-pack-result/v1",
        "status": "blocked",
        "issues": list(issues),
    }


def _inside(root: Path, path: Path, *, label: str) -> tuple[Path | None, str | None]:
    selected = Path(path)
    if selected.is_symlink():
        return None, f"{label}_symlink_forbidden:{path}"
    resolved = selected.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"{label}_outside_source_root:{path}"
    if not resolved.is_file():
        return None, f"{label}_not_found:{path}"
    return resolved, None


def _craft_card_issues(path: Path) -> list[str]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return [f"craft_card_unreadable:{path}"]
    cards = value if isinstance(value, list) else [value]
    issues: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, Mapping):
            issues.append(f"craft_card_invalid:{path}:{index}")
            continue
        issues.extend(
            f"craft_card_invalid:{path}:{index}:{issue}"
            for issue in validate_craft_card(card)
        )
    return issues


def _unsafe_output_path(project_root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return True
    current = project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    try:
        path.resolve().relative_to(project_root)
    except ValueError:
        return True
    return False


def _context_bundle_inventory(
    bundle: Mapping[str, Any],
    *,
    role_id: str,
) -> tuple[dict[str, str], list[str]]:
    issues: list[str] = []
    shared = bundle.get("shared_files")
    role_specific = bundle.get("role_specific_files")
    chapter_window = bundle.get("chapter_window")
    if (
        bundle.get("schema_version") != 1
        or not isinstance(shared, list)
        or not isinstance(role_specific, Mapping)
        or not isinstance(chapter_window, list)
        or not str(bundle.get("canon_snapshot_sha256") or "")
    ):
        return {}, ["context_bundle_manifest_schema_invalid"]
    inventory: dict[str, str] = {}
    records: list[tuple[object, bool]] = [
        (record, True) for record in shared
    ]
    for role_label, role_records in role_specific.items():
        if not isinstance(role_records, list):
            issues.append("context_bundle_role_inventory_invalid")
            continue
        normalized_role = re.sub(
            r"_+",
            "_",
            re.sub(
                r"[^A-Za-z0-9]+",
                "_",
                re.sub(r"(?<!^)(?=[A-Z])", "_", str(role_label)),
            ).strip("_").lower(),
        )
        records.extend(
            (record, normalized_role == role_id) for record in role_records
        )
    for index, (raw, authorized) in enumerate(records):
        if not isinstance(raw, Mapping):
            issues.append(f"context_bundle_record_invalid:{index}")
            continue
        path = str(raw.get("path") or "")
        sha256 = str(raw.get("sha256") or "")
        size = raw.get("bytes")
        if (
            not path
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            issues.append(f"context_bundle_record_invalid:{index}")
            continue
        if authorized:
            previous = inventory.get(path)
            if previous is not None and previous != sha256:
                issues.append(f"context_bundle_record_conflict:{path}")
                continue
            inventory[path] = sha256
    identity_fields = {
        "canon_snapshot_sha256",
        "chapter_window",
        "shared_files",
        "role_specific_files",
        "creative_brief",
        "creative_brief_sha256",
        "predecessor_sha256",
    }
    identity = {
        key: bundle[key]
        for key in identity_fields
        if key in bundle
    }
    expected_id = "ctx-" + hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    if bundle.get("context_bundle_id") != expected_id:
        issues.append("context_bundle_id_not_content_addressed")
    return inventory, issues


def compile_role_context_pack(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    role_id: str,
    context_bundle_manifest: Path,
    evidence_candidates: Sequence[Mapping[str, object]],
    token_budget: int,
    minimum_evidence_items: int,
    audit_chapter_id: int | None = None,
    audit_candidate_path: Path | None = None,
) -> dict[str, Any]:
    """Compile one immutable pack using the mandated retrieval-stage order.

    The caller performs retrieval.  This compiler applies the canonical role
    namespace boundary, deterministically selects evidence within budget, and
    records every omission.  Reflective evidence is considered only while the
    earlier stages have not met ``minimum_evidence_items``.
    """

    if token_budget <= 0:
        return _blocked("token_budget_must_be_positive")
    if minimum_evidence_items < 0:
        return _blocked("minimum_evidence_items_must_be_nonnegative")
    if not _PROJECT_ID.fullmatch(project):
        return _blocked("project_id_invalid")
    if not _TASK_ID.fullmatch(task_id):
        return _blocked("task_id_invalid")
    if (audit_chapter_id is None) != (audit_candidate_path is None):
        return _blocked("audit_target_fields_must_be_declared_together")
    if audit_chapter_id is not None and (
        isinstance(audit_chapter_id, bool) or audit_chapter_id <= 0
    ):
        return _blocked("audit_chapter_id_must_be_positive")

    agentlab = Path(agentlab_root).resolve()
    project_path = agentlab / "projects" / project
    if project_path.is_symlink() or not project_path.is_dir():
        return _blocked("project_root_invalid")
    root = project_path.resolve()
    run_artifacts = root / "runs" / task_id / "artifacts"
    output = run_artifacts / "role_context"
    if _unsafe_output_path(root, output):
        return _blocked("run_artifacts_symlink_or_escape_forbidden")

    bundle_path, bundle_issue = _inside(
        root,
        Path(context_bundle_manifest),
        label="context_bundle_manifest",
    )
    if bundle_issue or bundle_path is None:
        return _blocked(str(bundle_issue))
    try:
        bundle_relative = bundle_path.relative_to(root)
    except ValueError:
        return _blocked("context_bundle_manifest_outside_project")
    expected_prefix = Path("runs") / task_id / "artifacts"
    if bundle_relative.parts[:3] != expected_prefix.parts:
        return _blocked("context_bundle_manifest_not_run_artifact")
    try:
        bundle = yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return _blocked("context_bundle_manifest_unreadable")
    if not isinstance(bundle, Mapping):
        return _blocked("context_bundle_manifest_invalid")
    bundle_inventory, bundle_issues = _context_bundle_inventory(
        bundle,
        role_id=role_id,
    )
    if bundle_issues:
        return _blocked(*bundle_issues)
    audit_target = None
    if audit_chapter_id is not None and audit_candidate_path is not None:
        candidate_path, candidate_issue = _inside(
            root,
            audit_candidate_path,
            label="audit_candidate",
        )
        if candidate_issue or candidate_path is None:
            return _blocked(str(candidate_issue))
        try:
            candidate_relative = candidate_path.relative_to(run_artifacts)
        except ValueError:
            return _blocked("audit_candidate_not_run_artifact")
        if not candidate_relative.parts:
            return _blocked("audit_candidate_not_run_artifact")
        chapter_window = bundle.get("chapter_window")
        if (
            not isinstance(chapter_window, list)
            or audit_chapter_id not in chapter_window
        ):
            return _blocked("audit_chapter_not_in_context_bundle_window")
        audit_target = {
            "chapter_id": audit_chapter_id,
            "candidate_path": candidate_path.relative_to(root).as_posix(),
            "candidate_sha256": hashlib.sha256(
                candidate_path.read_bytes()
            ).hexdigest(),
        }

    try:
        contract = load_author_team_contract(agentlab)
    except ValueError as exc:
        return _blocked(f"author_team_contract_invalid:{exc}")
    roles = contract.get("roles")
    role = roles.get(role_id) if isinstance(roles, Mapping) else None
    if not isinstance(role, Mapping):
        return _blocked(f"unknown_professional_role:{role_id}")
    allowed_namespaces = tuple(
        str(item) for item in role.get("knowledge_namespaces") or []
    )

    candidates: list[dict[str, Any]] = []
    issues: list[str] = []
    observed_paths: set[str] = set()
    for index, candidate in enumerate(evidence_candidates):
        path_value = candidate.get("path")
        if not isinstance(path_value, (str, Path)):
            issues.append(f"evidence_path_required:{index}")
            continue
        path, path_issue = _inside(
            root,
            Path(path_value),
            label=f"evidence[{index}]",
        )
        if path_issue or path is None:
            issues.append(str(path_issue))
            continue
        relative = path.relative_to(root).as_posix()
        relative_parts = Path(relative).parts
        if (
            not relative_parts
            or relative_parts[0] not in _CANONICAL_INPUT_ROOTS
        ):
            issues.append(f"evidence_not_canonical:{relative}")
            continue
        if relative in observed_paths:
            issues.append(f"duplicate_evidence_path:{relative}")
            continue
        observed_paths.add(relative)

        namespace = str(candidate.get("namespace") or "")
        if namespace not in allowed_namespaces:
            issues.append(f"namespace_not_allowed:{role_id}:{namespace}")
            continue
        stage = str(candidate.get("retrieval_stage") or "")
        if stage not in RETRIEVAL_ORDER:
            issues.append(f"retrieval_stage_invalid:{relative}:{stage}")
            continue
        try:
            score = float(candidate.get("score", 0.0))
        except (TypeError, ValueError):
            issues.append(f"evidence_score_invalid:{relative}")
            continue
        if not math.isfinite(score):
            issues.append(f"evidence_score_invalid:{relative}")
            continue
        if namespace == "craft_cards":
            issues.extend(_craft_card_issues(path))

        payload = path.read_bytes()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        if bundle_inventory.get(relative) != payload_sha256:
            issues.append(f"evidence_not_bound_by_context_bundle:{relative}")
            continue
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(f"evidence_not_utf8:{relative}")
            continue
        candidates.append(
            {
                "path": relative,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": score,
                "required": bool(candidate.get("required", False)),
                "bytes": len(payload),
                "estimated_tokens": max(1, math.ceil(len(payload) / 4)),
                "sha256": payload_sha256,
                "content": content,
            }
        )
    if issues:
        return _blocked(*issues)

    stage_index = {stage: index for index, stage in enumerate(RETRIEVAL_ORDER)}
    candidates.sort(
        key=lambda item: (
            stage_index[item["retrieval_stage"]],
            not item["required"],
            -item["score"],
            item["path"],
        )
    )
    candidate_inventory = [
        {
            key: item[key]
            for key in (
                "path",
                "namespace",
                "retrieval_stage",
                "score",
                "required",
                "bytes",
                "estimated_tokens",
                "sha256",
            )
        }
        for item in candidates
    ]
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    used_tokens = 0
    for item in candidates:
        stage = item["retrieval_stage"]
        if stage == "reflective" and len(selected) >= minimum_evidence_items:
            omitted.append(
                {
                    "path": item["path"],
                    "namespace": item["namespace"],
                    "retrieval_stage": stage,
                    "reason": "reflective_retrieval_not_needed",
                }
            )
            continue
        if used_tokens + item["estimated_tokens"] > token_budget:
            if item["required"]:
                return _blocked(f"required_evidence_exceeds_budget:{item['path']}")
            omitted.append(
                {
                    "path": item["path"],
                    "namespace": item["namespace"],
                    "retrieval_stage": stage,
                    "reason": "token_budget_exceeded",
                }
            )
            continue
        selected.append(item)
        used_tokens += item["estimated_tokens"]

    identity = {
        "schema_version": "role-context-pack/v1",
        "project": project,
        "task_id": task_id,
        "role_id": role_id,
        "knowledge_namespaces": list(allowed_namespaces),
        "retrieval_order": list(RETRIEVAL_ORDER),
        "retrieval_execution": {
            "candidate_source": "caller_provided_hash_bound_candidates",
            "compiler_performs_retrieval": False,
            "external_transfer": "forbidden",
            "external_transfer_approval_contract": (
                "agent_runtime.narrative.outbound_transfer."
                "build_narrative_outbound_transfer_contract"
            ),
        },
        "context_bundle": {
            "path": bundle_relative.as_posix(),
            "context_bundle_id": bundle["context_bundle_id"],
            "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        },
        "authority_bindings": contract["authority_bindings"],
        "selected_evidence": selected,
        "omitted_evidence": omitted,
        "candidate_inventory": candidate_inventory,
        "token_usage": {
            "budget": token_budget,
            "used": used_tokens,
            "remaining": token_budget - used_tokens,
            "estimator": "ceil_utf8_bytes_div_4",
        },
        "minimum_evidence_items": minimum_evidence_items,
        "evidence_sufficient": len(selected) >= minimum_evidence_items,
    }
    if audit_target is not None:
        identity["audit_target"] = audit_target
    pack_sha256 = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pack = {**identity, "pack_sha256": pack_sha256}
    pack_path = output / f"{role_id}-{pack_sha256[:24]}.yml"
    if pack_path.exists():
        try:
            existing = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return _blocked("role_context_pack_collision")
        if existing != pack:
            return _blocked("role_context_pack_collision")
        status = "current"
    else:
        output.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(pack_path, pack)
        status = "pass"
    return {
        **pack,
        "status": status,
        "pack_path": str(pack_path),
        "issues": [],
    }
