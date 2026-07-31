"""Frontend-independent deterministic Frontdesk intent compiler."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import re

import yaml


def _contains(text: str, vocabulary: tuple[str, ...]) -> bool:
    return any(term in text for term in vocabulary)


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def load_frontdesk_intent_policy(
    agentlab_root: Path | None = None,
) -> dict[str, Any]:
    """Load the sole Frontdesk intent classification authority."""

    root = (
        Path(agentlab_root).resolve()
        if agentlab_root is not None
        else Path(__file__).resolve().parents[1]
    )
    path = root / "config" / "frontdesk_policy.yml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("frontdesk intent policy is unreadable") from exc
    policy = (
        document.get("intent_compiler_v2")
        if isinstance(document, Mapping)
        else None
    )
    if (
        not isinstance(policy, Mapping)
        or policy.get("schema_version") != "frontdesk-intent-policy/v1"
        or not isinstance(policy.get("vocabularies"), Mapping)
        or not isinstance(policy.get("tiers"), Mapping)
        or not isinstance(policy.get("approval_requirements"), Mapping)
    ):
        raise ValueError("frontdesk intent policy schema is invalid")
    return dict(policy)


def _vocabulary(policy: Mapping[str, Any], name: str) -> tuple[str, ...]:
    vocabularies = policy.get("vocabularies")
    values = (
        vocabularies.get(name)
        if isinstance(vocabularies, Mapping)
        else None
    )
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise ValueError(f"frontdesk vocabulary is invalid: {name}")
    return tuple(value.casefold() for value in values)


def _tier(policy: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    tiers = policy.get("tiers")
    value = tiers.get(name) if isinstance(tiers, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError(f"frontdesk tier contract is invalid: {name}")
    return value


def compile_frontdesk_intent(
    request: str,
    *,
    project: str | None = None,
    project_contract_exists: bool = False,
    adapter: str | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile frontdesk-intent/v2; transport adapter is intentionally ignored."""

    del adapter
    selected_policy = (
        dict(policy)
        if isinstance(policy, Mapping)
        else load_frontdesk_intent_policy()
    )
    raw_request = str(request)
    normalized = " ".join(raw_request.strip().casefold().split())
    if not normalized:
        raise ValueError("frontdesk request must not be empty")
    action_text = normalized
    for pattern in selected_policy.get("negated_action_patterns") or []:
        action_text = re.sub(str(pattern), " ", action_text)
    has_mutation = _contains(
        action_text,
        _vocabulary(selected_policy, "mutation"),
    )
    has_external = _contains(
        action_text,
        _vocabulary(selected_policy, "external"),
    )
    has_destructive = _contains(
        action_text,
        _vocabulary(selected_policy, "destructive"),
    )
    has_audit = _contains(
        normalized,
        _vocabulary(selected_policy, "audit"),
    )
    project_vocabulary = _vocabulary(selected_policy, "project")
    project_signals = sum(term in normalized for term in project_vocabulary)
    bounded = _contains(
        normalized,
        _vocabulary(selected_policy, "bounded"),
    )
    single_capability_pattern = str(
        selected_policy.get("single_capability_pattern") or ""
    )
    if not single_capability_pattern:
        raise ValueError("frontdesk single capability pattern is required")
    explicit_single_capability = bool(
        re.search(single_capability_pattern, normalized)
    )
    status_only = (
        _contains(normalized, _vocabulary(selected_policy, "status"))
        and not has_mutation
        and not has_external
        and not has_audit
    )
    evidence: list[str] = [
        "config:frontdesk_policy.yml#intent_compiler_v2"
    ]
    if action_text != normalized:
        evidence.append("rule:negated_action_mask")
    approvals: list[str] = []
    capabilities: list[str] = []
    if status_only:
        contract = _tier(selected_policy, "F0")
        intent = str(contract["intent"])
        task_scope = str(contract["task_scope"])
        route_tier = "F0"
        confidence = float(contract["confidence"])
        capabilities = list(contract["capabilities"])
        evidence.append(str(contract["evidence"]))
    elif explicit_single_capability and not has_mutation:
        contract = _tier(selected_policy, "F1")
        intent = str(contract["intent"])
        task_scope = str(contract["task_scope"])
        route_tier = "F1"
        confidence = float(contract["confidence"])
        capabilities = list(contract["capabilities"])
        evidence.append(str(contract["evidence"]))
    elif (
        project_contract_exists
        and project_signals
        >= int(selected_policy.get("project_signal_threshold") or 2)
    ):
        contract = _tier(selected_policy, "F4")
        intent = str(contract["intent"])
        task_scope = str(contract["task_scope"])
        route_tier = "F4"
        confidence = float(contract["confidence"])
        capabilities = list(contract["capabilities"])
        evidence.extend(
            [
                str(contract["evidence"]),
                "fact:project_contract_exists",
            ]
        )
    elif has_mutation and not has_audit:
        contract = _tier(selected_policy, "F2")
        intent = str(contract["intent"])
        task_scope = str(contract["task_scope"])
        route_tier = "F2"
        confidence = float(
            contract["bounded_confidence"]
            if bounded
            else contract["confidence"]
        )
        capabilities = list(contract["capabilities"])
        evidence.append(str(contract["evidence"]))
    else:
        contract = _tier(selected_policy, "F3")
        intent = str(
            contract["audit_intent"] if has_audit else contract["intent"]
        )
        task_scope = str(contract["task_scope"])
        route_tier = "F3"
        confidence = float(
            contract["audit_confidence"]
            if has_audit
            else contract["confidence"]
        )
        capabilities = list(contract["capabilities"])
        evidence.append(
            str(contract["audit_evidence"])
            if has_audit
            else str(contract["evidence"])
        )
        if (
            project_signals
            or _word_count(normalized)
            < int(
                selected_policy.get("ambiguous_short_request_words") or 6
            )
        ):
            approval_policy = selected_policy["approval_requirements"]
            approvals.append(str(approval_policy["project_contract"]))
    approval_policy = selected_policy["approval_requirements"]
    mutation_scope = "project_scoped" if has_mutation else "none"
    external_effect = "external_write" if has_external else "none"
    if has_external:
        capabilities.append("external_write")
        approvals.append(str(approval_policy["external_effect"]))
    if has_destructive:
        approvals.append(str(approval_policy["destructive_action"]))
    if _contains(
        normalized,
        _vocabulary(selected_policy, "credential"),
    ):
        capabilities.append("credential_access")
        approvals.append(str(approval_policy["credential_scope"]))
    risk = "critical" if has_destructive and has_external else (
        "high" if has_destructive or has_external else (
            "medium" if has_mutation or route_tier in {"F3", "F4"} else "low"
        )
    )
    return {
        "schema_version": "frontdesk-intent/v2",
        "request_sha256": hashlib.sha256(raw_request.encode("utf-8")).hexdigest(),
        "normalized_request": normalized,
        "intent": intent,
        "project": project,
        "task_scope": task_scope,
        "mutation_scope": mutation_scope,
        "external_effect": external_effect,
        "required_capabilities": list(dict.fromkeys(capabilities)),
        "risk": risk,
        "route_tier": route_tier,
        "approval_requirements": list(dict.fromkeys(approvals)),
        "confidence": confidence,
        "evidence": evidence,
    }
