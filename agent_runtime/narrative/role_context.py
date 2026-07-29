"""Role-scoped, evidence-bound narrative context packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
import math

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


def _blocked(*issues: str) -> dict[str, Any]:
    return {
        "schema_version": "role-context-pack-result/v1",
        "status": "blocked",
        "issues": list(issues),
    }


def _inside(root: Path, path: Path, *, label: str) -> tuple[Path | None, str | None]:
    resolved = Path(path).resolve()
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


def compile_role_context_pack(
    agentlab_root: Path,
    *,
    role_id: str,
    source_root: Path,
    context_bundle_manifest: Path,
    evidence_candidates: Sequence[Mapping[str, object]],
    token_budget: int,
    minimum_evidence_items: int,
    output_dir: Path,
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

    root = Path(source_root).resolve()
    output = Path(output_dir).resolve()
    try:
        output.relative_to(root)
    except ValueError:
        return _blocked(f"output_dir_outside_source_root:{output_dir}")

    bundle_path, bundle_issue = _inside(
        root,
        Path(context_bundle_manifest),
        label="context_bundle_manifest",
    )
    if bundle_issue or bundle_path is None:
        return _blocked(str(bundle_issue))
    try:
        bundle = yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return _blocked("context_bundle_manifest_unreadable")
    if not isinstance(bundle, Mapping) or not str(
        bundle.get("context_bundle_id") or ""
    ):
        return _blocked("context_bundle_manifest_invalid")

    try:
        contract = load_author_team_contract(Path(agentlab_root))
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
        candidates.append(
            {
                "path": relative,
                "namespace": namespace,
                "retrieval_stage": stage,
                "score": score,
                "required": bool(candidate.get("required", False)),
                "bytes": len(payload),
                "estimated_tokens": max(1, math.ceil(len(payload) / 4)),
                "sha256": hashlib.sha256(payload).hexdigest(),
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
        "role_id": role_id,
        "knowledge_namespaces": list(allowed_namespaces),
        "retrieval_order": list(RETRIEVAL_ORDER),
        "context_bundle": {
            "path": bundle_path.relative_to(root).as_posix(),
            "context_bundle_id": bundle["context_bundle_id"],
            "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        },
        "authority_bindings": contract["authority_bindings"],
        "selected_evidence": selected,
        "omitted_evidence": omitted,
        "token_usage": {
            "budget": token_budget,
            "used": used_tokens,
            "remaining": token_budget - used_tokens,
            "estimator": "ceil_utf8_bytes_div_4",
        },
        "minimum_evidence_items": minimum_evidence_items,
        "evidence_sufficient": len(selected) >= minimum_evidence_items,
    }
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
