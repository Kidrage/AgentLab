from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_state_transition_proposal(evidence_dir: Path, artifact_name: str = "state_transition_proposal.yml") -> dict[str, Any] | None:
    candidates = [evidence_dir / artifact_name]
    ledger_path = evidence_dir / "evidence_ledger.yml"
    if ledger_path.exists():
        try:
            ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
            result_dir = Path(str(ledger.get("result_dir"))) if ledger.get("result_dir") else None
            if result_dir:
                candidates.extend([result_dir / artifact_name, result_dir / "artifacts" / artifact_name])
        except Exception:
            pass
    for candidate in candidates:
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
    return None


def validate_state_transition_proposal(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    proposal: dict[str, Any] | None,
    *,
    required: bool = False,
) -> dict[str, Any]:
    if proposal is None:
        if required:
            return _verdict(False, ["missing state_transition_proposal.yml"], [])
        return _verdict(True, [], ["no state transition proposal supplied"])

    body = proposal.get("state_transition_proposal") or proposal
    events = body.get("events") or []
    if not isinstance(events, list) or not events:
        if required:
            return _verdict(False, ["state_transition_proposal.yml has no events"], [])
        return _verdict(True, [], ["empty proposal; no durable project facts changed"])

    errors = []
    warnings = []
    allowed_event_types = set(str(item) for item in contract.get("event_types") or [])
    entity_types = set(str(item) for item in contract.get("entity_types") or [])
    artifact_types = set(str(item) for item in contract.get("artifact_types") or [])
    for index, event in enumerate(events):
        prefix = f"events[{index}]"
        event_type = str(event.get("event_type") or "")
        if allowed_event_types and event_type and event_type not in allowed_event_types:
            warnings.append(f"{prefix}: event_type '{event_type}' is not declared by contract")
        if (contract.get("evidence_policy") or {}).get("state_change_requires_evidence", True):
            if not event.get("evidence_refs"):
                errors.append(f"{prefix}: evidence_refs are required")
        kind = str(event.get("target_kind") or event.get("kind") or "entity")
        target_type = str(event.get("target_type") or event.get("entity_type") or event.get("artifact_type") or "")
        target_id = str(event.get("target_id") or event.get("entity_id") or event.get("artifact_id") or "")
        if kind not in {"entity", "artifact"}:
            errors.append(f"{prefix}: target_kind must be entity or artifact")
        if not target_type:
            errors.append(f"{prefix}: target_type is required")
        if not target_id:
            errors.append(f"{prefix}: target_id is required")
        if kind == "entity" and entity_types and target_type not in entity_types:
            warnings.append(f"{prefix}: entity type '{target_type}' is outside selected preset")
        if kind == "artifact" and artifact_types and target_type not in artifact_types:
            warnings.append(f"{prefix}: artifact type '{target_type}' is outside selected preset")
        _check_blocked_transition(contract, snapshot, event, prefix, errors)
        _check_required_event_fields(contract, event, prefix, errors)
    return _verdict(not errors, errors, warnings)


def _check_blocked_transition(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    event: dict[str, Any],
    prefix: str,
    errors: list[str],
) -> None:
    kind = str(event.get("target_kind") or event.get("kind") or "entity")
    collection_key = "entities" if kind == "entity" else "artifacts"
    target_type = str(event.get("target_type") or event.get("entity_type") or event.get("artifact_type") or "")
    target_id = str(event.get("target_id") or event.get("entity_id") or event.get("artifact_id") or "")
    previous = (((snapshot.get(collection_key) or {}).get(target_type) or {}).get(target_id) or {})
    previous_status = str(previous.get("status") or event.get("from_status") or "")
    event_type = str(event.get("event_type") or "")
    to_status = str(event.get("to_status") or "")
    for invariant in contract.get("invariants") or []:
        blocked = {str(item) for item in invariant.get("blocked_from_statuses") or []}
        allowed = {str(item) for item in invariant.get("allowed_events") or []}
        invariant_target = str(invariant.get("target_type") or "")
        if invariant_target and invariant_target != target_type:
            continue
        if previous_status in blocked and event_type not in allowed and to_status in {"active", "resolved", "planned"}:
            errors.append(
                f"{prefix}: invariant '{invariant.get('invariant_id')}' blocks {target_type}/{target_id} "
                f"from {previous_status} to {to_status or 'unknown'} via {event_type or 'unknown'}"
            )


def _check_required_event_fields(
    contract: dict[str, Any],
    event: dict[str, Any],
    prefix: str,
    errors: list[str],
) -> None:
    event_type = str(event.get("event_type") or "")
    for invariant in contract.get("invariants") or []:
        event_types = {str(item) for item in invariant.get("event_types") or []}
        if event_types and event_type not in event_types:
            continue
        for field in invariant.get("required_event_fields") or []:
            if not _has_dotted_field(event, str(field)):
                errors.append(f"{prefix}: invariant '{invariant.get('invariant_id')}' requires field '{field}'")


def _has_dotted_field(data: dict[str, Any], dotted: str) -> bool:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current not in (None, "", [])


def _verdict(valid: bool, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return {
        "valid": valid,
        "verdict": "PASS" if valid else "NEEDS_EVIDENCE",
        "errors": errors,
        "warnings": warnings,
    }
