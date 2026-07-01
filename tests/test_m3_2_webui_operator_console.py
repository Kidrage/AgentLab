"""M3-2 WebUI Operator Console — contract tests for operator actions via WebUI."""

from __future__ import annotations

from agent_runtime.operator_os.action_contract import (
    build_operator_action_catalog,
    validate_operator_action,
    GLOBAL_FORBIDDEN_EFFECTS,
)


def test_all_8_operator_actions_supported() -> None:
    """Verify all 8 operator actions are in the catalog."""
    catalog = build_operator_action_catalog()
    actions = set(catalog["actions"].keys())
    required = {
        "approve", "reject", "pause", "resume", "retry",
        "request_missing_evidence", "inspect_evidence",
        "open_artifact", "export_handoff",
    }
    missing = required - actions
    assert not missing, f"Missing actions in catalog: {missing}"


def test_mutating_actions_require_actor_and_reason() -> None:
    """Mutating actions must be blocked without actor/reason."""
    for action in ["approve", "reject", "pause", "resume", "retry", "request_missing_evidence"]:
        result = validate_operator_action({
            "action": action,
            "target_type": "phase_acceptance",
            "target_id": "test",
        })
        assert result["status"] == "blocked", f"{action} should be blocked without actor/reason"
        assert "actor_required" in result["errors"]


def test_readonly_actions_no_actor_required() -> None:
    """Read-only actions should NOT require actor/reason."""
    targets = {"inspect_evidence": "phase", "open_artifact": "artifact", "export_handoff": "project"}
    for action in ["inspect_evidence", "open_artifact", "export_handoff"]:
        result = validate_operator_action({
            "action": action,
            "target_type": targets[action],
            "target_id": "test",
        })
        assert result["status"] == "ok", f"{action} should work without actor"
        assert result["mutates_state"] is False


def test_forbidden_effects_blocked() -> None:
    """All global forbidden effects must be blocked."""
    for effect in GLOBAL_FORBIDDEN_EFFECTS:
        result = validate_operator_action({
            "action": "approve",
            "target_type": "phase_acceptance",
            "target_id": "test",
            "actor": "operator",
            "reason": "test",
            "requested_effects": [effect],
        })
        assert result["status"] == "blocked", f"Effect '{effect}' should be blocked"
        error_msgs = " ".join(result["errors"])
        assert effect in error_msgs, f"Error must mention forbidden effect '{effect}'"


def test_approve_reject_targets_phase_acceptance() -> None:
    """approve/reject must support phase_acceptance targets."""
    for action in ["approve", "reject"]:
        result = validate_operator_action({
            "action": action,
            "target_type": "phase_acceptance",
            "target_id": "phase_1",
            "actor": "operator",
            "reason": "evidence complete",
        })
        assert result["status"] == "ok", f"{action} on phase_acceptance should be ok"


def test_pause_resume_targets_project() -> None:
    """pause/resume must support project targets."""
    for action in ["pause", "resume"]:
        result = validate_operator_action({
            "action": action,
            "target_type": "project",
            "target_id": "test_project",
            "actor": "operator",
            "reason": "budget exceeded",
        })
        assert result["status"] == "ok", f"{action} on project should be ok"


def test_retry_targets_task() -> None:
    """retry must support task targets."""
    result = validate_operator_action({
        "action": "retry",
        "target_type": "task",
        "target_id": "task_001",
        "actor": "operator",
        "reason": "evidence now available",
    })
    assert result["status"] == "ok"
