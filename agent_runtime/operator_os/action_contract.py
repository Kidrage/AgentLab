"""Operator action contracts for M3 control surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperatorActionSpec:
    action: str
    target_types: list[str]
    mutates_state: bool
    requires_actor: bool
    requires_reason: bool
    runtime_contract: str
    audit_event_type: str
    forbidden_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_types": list(self.target_types),
            "mutates_state": self.mutates_state,
            "requires_actor": self.requires_actor,
            "requires_reason": self.requires_reason,
            "runtime_contract": self.runtime_contract,
            "audit_event_type": self.audit_event_type,
            "forbidden_effects": list(self.forbidden_effects),
        }


OPERATOR_ACTIONS: dict[str, OperatorActionSpec] = {
    "approve": OperatorActionSpec(
        action="approve",
        target_types=["decision_card", "phase_acceptance", "executor_result"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="approval_ledger_or_existing_cli_approve",
        audit_event_type="operator.approved",
    ),
    "reject": OperatorActionSpec(
        action="reject",
        target_types=["decision_card", "phase_acceptance", "executor_result"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="approval_ledger_or_existing_cli_reject",
        audit_event_type="operator.rejected",
    ),
    "pause": OperatorActionSpec(
        action="pause",
        target_types=["project", "phase", "task"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="existing_task_pause_or_project_pause",
        audit_event_type="operator.paused",
    ),
    "resume": OperatorActionSpec(
        action="resume",
        target_types=["project", "phase", "task"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="existing_resume_policy_then_resume",
        audit_event_type="operator.resumed",
    ),
    "retry": OperatorActionSpec(
        action="retry",
        target_types=["phase", "task", "executor_result"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="existing_retry_policy_then_retry",
        audit_event_type="operator.retry_requested",
    ),
    "cancel": OperatorActionSpec(
        action="cancel",
        target_types=["task"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="existing_task_cancel",
        audit_event_type="operator.cancelled",
    ),
    "request_missing_evidence": OperatorActionSpec(
        action="request_missing_evidence",
        target_types=["phase", "executor_result"],
        mutates_state=True,
        requires_actor=True,
        requires_reason=True,
        runtime_contract="phase_acceptance_missing_evidence_request",
        audit_event_type="operator.evidence_requested",
    ),
    "inspect_evidence": OperatorActionSpec(
        action="inspect_evidence",
        target_types=["phase", "executor_result", "artifact"],
        mutates_state=False,
        requires_actor=False,
        requires_reason=False,
        runtime_contract="read_only_evidence_view",
        audit_event_type="operator.evidence_inspected",
    ),
    "open_artifact": OperatorActionSpec(
        action="open_artifact",
        target_types=["artifact"],
        mutates_state=False,
        requires_actor=False,
        requires_reason=False,
        runtime_contract="read_only_artifact_view",
        audit_event_type="operator.artifact_opened",
    ),
    "export_handoff": OperatorActionSpec(
        action="export_handoff",
        target_types=["project", "phase", "task"],
        mutates_state=False,
        requires_actor=False,
        requires_reason=False,
        runtime_contract="read_only_handoff_export",
        audit_event_type="operator.handoff_exported",
    ),
}

GLOBAL_FORBIDDEN_EFFECTS = [
    "direct_production_content_write",
    "phase_acceptance_bypass",
    "evidence_gate_bypass",
    "project_brain_bypass",
    "external_executor_enablement",
    "public_server_bind",
    "secret_exposure",
]


def build_operator_action_catalog() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "agent_runtime.operator_os.action_contract",
        "global_forbidden_effects": list(GLOBAL_FORBIDDEN_EFFECTS),
        "actions": {key: value.to_dict() for key, value in sorted(OPERATOR_ACTIONS.items())},
    }


def validate_operator_action(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "")
    target_type = str(request.get("target_type") or "")
    requested_effects = [str(item) for item in request.get("requested_effects") or []]
    spec = OPERATOR_ACTIONS.get(action)
    errors: list[str] = []
    if spec is None:
        errors.append(f"unsupported_operator_action:{action or 'missing'}")
    else:
        if target_type not in spec.target_types:
            errors.append(f"unsupported_target_type:{target_type or 'missing'}")
        if spec.requires_actor and not request.get("actor"):
            errors.append("actor_required")
        if spec.requires_reason and not request.get("reason"):
            errors.append("reason_required")
    for effect in requested_effects:
        if effect in GLOBAL_FORBIDDEN_EFFECTS:
            errors.append(f"forbidden_effect:{effect}")

    status = "ok" if not errors else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "action": action,
        "target_type": target_type,
        "mutates_state": bool(spec.mutates_state) if spec else False,
        "runtime_contract": spec.runtime_contract if spec else None,
        "audit_event_type": spec.audit_event_type if spec else None,
        "errors": errors,
        "must_call_existing_runtime_contract": True,
        "may_bypass_phase_acceptance": False,
        "may_write_production_content_directly": False,
    }
