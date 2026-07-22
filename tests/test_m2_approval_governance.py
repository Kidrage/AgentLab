from __future__ import annotations

import pytest

from agent_runtime.approvals.approval_ledger import ApprovalLedger
from agent_runtime.approvals.approval_policy import ApprovalPolicy, load_approval_policy
from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.approvals.policy_engine import decide_approval, verify_approval_grant
from agent_runtime.approvals.risk_gate import evaluate_risk


def test_default_policy_auto_approves_bounded_low_risk_action() -> None:
    decision = decide_approval(
        {
            "action": "workspace_patch",
            "project": "AgentLab",
            "task_id": "task-auto-approval",
            "capabilities": ["filesystem_write", "shell_execution"],
            "bounded_scope": True,
            "reversible": True,
            "estimated_cost_usd": 0.0,
            "cost_visibility": "known",
            "output_dir": "/tmp/agentlab-auto-approval",
        },
        ApprovalPolicy(),
        now="2026-07-23T03:50:00Z",
    )

    assert decision.mode == "auto_approved"
    assert decision.requires_human is False
    assert decision.grant is not None
    assert decision.grant["actor"] == "policy:default-auto"
    assert decision.grant["scope_hash"]
    assert decision.grant["policy_hash"]
    assert decision.grant["decision_mode"] == "policy_auto_approved"
    assert decision.grant["policy_id"] == "default-auto"
    assert decision.grant["authorizes_execution"] is True
    assert decision.grant["scope"]["task_id"] == "task-auto-approval"
    assert decision.grant["expires_at"] == "2026-07-24T03:50:00Z"


def test_auto_approval_grant_is_scope_bound_and_expires() -> None:
    request = {
        "action": "workspace_patch",
        "task_id": "task-bound",
        "capabilities": ["filesystem_write"],
        "bounded_scope": True,
        "reversible": True,
        "allowed_files": ["agent_runtime/example.py"],
        "output_dir": "/tmp/agentlab-approval-test",
        "cost_visibility": "known",
        "estimated_cost_usd": 0.0,
    }
    policy = ApprovalPolicy()
    decision = decide_approval(request, policy, now="2026-07-23T05:00:00Z")
    assert decision.grant is not None

    valid = verify_approval_grant(
        decision.grant,
        request,
        policy,
        now="2026-07-23T05:01:00Z",
    )
    changed_scope = verify_approval_grant(
        decision.grant,
        {**request, "allowed_files": ["agent_runtime/other.py"]},
        policy,
        now="2026-07-23T05:01:00Z",
    )
    expired = verify_approval_grant(
        decision.grant,
        request,
        policy,
        now="2026-07-24T05:01:00Z",
    )
    tampered_authority = verify_approval_grant(
        {**decision.grant, "authorizes_execution": False},
        request,
        policy,
        now="2026-07-23T05:01:00Z",
    )

    assert valid.valid is True
    assert changed_scope.valid is False
    assert changed_scope.reasons == ("scope_hash_mismatch",)
    assert expired.valid is False
    assert expired.reasons == ("grant_expired",)
    assert tampered_authority.valid is False
    assert tampered_authority.reasons == ("execution_authority_mismatch",)


def test_default_policy_keeps_public_release_as_human_gate() -> None:
    decision = decide_approval(
        {
            "action": "public_release",
            "project": "AgentLab",
            "task_id": "task-release",
            "bounded_scope": True,
            "reversible": False,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:51:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.requires_human is True
    assert decision.grant is None
    assert "hard_human_action:public_release" in decision.reasons


def test_policy_identifiers_are_normalized_before_safety_checks() -> None:
    action = decide_approval(
        {"action": " Public_Release "},
        ApprovalPolicy(),
        now="2026-07-23T03:51:00Z",
    )
    capability = decide_approval(
        {
            "action": "inspect",
            "capabilities": " Private_Path_Access ",
            "bounded_scope": True,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:51:00Z",
    )

    assert action.mode == "human_required"
    assert capability.mode == "human_required"
    assert capability.reasons == ("critical_capabilities:private_path_access",)


def test_forbidden_action_cannot_be_auto_or_human_approved() -> None:
    decision = decide_approval(
        {
            "action": "evidence_tampering",
            "project": "AgentLab",
            "task_id": "task-forbidden",
        },
        ApprovalPolicy(),
        now="2026-07-23T03:52:00Z",
    )

    assert decision.mode == "forbidden"
    assert decision.requires_human is False
    assert decision.grant is None
    assert decision.reasons == ("forbidden_action:evidence_tampering",)


def test_unknown_or_over_budget_cost_escalates_to_human() -> None:
    policy = ApprovalPolicy()
    cases = (
        ({"action": "model_call", "cost_visibility": "unknown"}, "unknown_cost"),
        (
            {
                "action": "model_call",
                "cost_visibility": "known",
                "estimated_cost_usd": 0.11,
            },
            "cost_exceeds_auto_limit:0.11>0.10",
        ),
    )

    for request, expected_reason in cases:
        decision = decide_approval(request, policy, now="2026-07-23T03:53:00Z")
        assert decision.mode == "human_required"
        assert expected_reason in decision.reasons


def test_non_finite_or_negative_cost_cannot_be_auto_approved() -> None:
    for estimated_cost in (float("nan"), float("inf"), -0.01):
        decision = decide_approval(
            {
                "action": "model_call",
                "cost_visibility": "known",
                "estimated_cost_usd": estimated_cost,
            },
            ApprovalPolicy(),
            now="2026-07-23T03:53:00Z",
        )

        assert decision.mode == "human_required"
        assert decision.reasons == ("invalid_cost",)


def test_cost_sensitive_action_requires_explicit_cost_visibility() -> None:
    decision = decide_approval(
        {"action": "model_call", "estimated_cost_usd": 0.0},
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("missing_cost_visibility",)

    missing_estimate = decide_approval(
        {"action": "model_call", "cost_visibility": "known"},
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )
    assert missing_estimate.mode == "human_required"
    assert missing_estimate.reasons == ("missing_cost_estimate",)


@pytest.mark.parametrize("cost_visibility", [None, "", "opaque"])
def test_execution_request_rejects_invalid_cost_visibility(cost_visibility) -> None:
    decision = decide_approval(
        {
            "action": "external_execution",
            "capabilities": ["external_execution"],
            "bounded_scope": True,
            "reversible": True,
            "output_dir": "/tmp/agentlab-cost-test",
            "cost_visibility": cost_visibility,
            "estimated_cost_usd": 0.0,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )

    assert decision.mode == "human_required"
    expected = "missing_cost_visibility" if cost_visibility in {None, ""} else "invalid_cost_visibility"
    assert decision.reasons == (expected,)


@pytest.mark.parametrize("estimated_cost", [None, "", False])
def test_known_execution_cost_must_be_an_explicit_number(estimated_cost) -> None:
    decision = decide_approval(
        {
            "action": "external_execution",
            "capabilities": ["external_execution"],
            "bounded_scope": True,
            "reversible": True,
            "output_dir": "/tmp/agentlab-cost-test",
            "cost_visibility": "known",
            "estimated_cost_usd": estimated_cost,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )

    assert decision.mode == "human_required"
    expected = "invalid_cost" if estimated_cost is False else "missing_cost_estimate"
    assert decision.reasons == (expected,)


def test_free_execution_can_omit_cost_estimate() -> None:
    decision = decide_approval(
        {
            "action": "external_execution",
            "capabilities": ["external_execution"],
            "bounded_scope": True,
            "reversible": True,
            "output_dir": "/tmp/agentlab-cost-test",
            "cost_visibility": "free",
        },
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )

    assert decision.mode == "auto_approved"
    assert decision.grant is not None
    assert decision.grant["authorizes_execution"] is True


def test_cost_sensitive_capabilities_cannot_bypass_missing_cost_data() -> None:
    for action, capabilities in (
        ("task_execution", ["external_execution"]),
        ("api_call", ["network_access"]),
        ("model_inference", []),
    ):
        decision = decide_approval(
            {
                "action": action,
                "capabilities": capabilities,
                "bounded_scope": True,
                "reversible": True,
                "output_dir": "/tmp/agentlab-cost-test",
            },
            ApprovalPolicy(),
            now="2026-07-23T03:53:00Z",
        )

        assert decision.mode == "human_required"
        assert decision.reasons == ("missing_cost_visibility",)


def test_execution_request_requires_explicit_reversibility() -> None:
    decision = decide_approval(
        {
            "action": "external_execution",
            "capabilities": ["external_execution"],
            "bounded_scope": True,
            "output_dir": "/tmp/agentlab-cost-test",
            "cost_visibility": "known",
            "estimated_cost_usd": 0.0,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:53:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("unknown_action_reversibility",)


def test_unbounded_mutation_escalates_to_human() -> None:
    for bounded_scope in (False, None):
        request = {
            "action": "workspace_patch",
            "capabilities": ["filesystem_write"],
            "reversible": True,
        }
        if bounded_scope is not None:
            request["bounded_scope"] = bounded_scope
        decision = decide_approval(
            request,
            ApprovalPolicy(),
            now="2026-07-23T03:54:00Z",
        )

        assert decision.mode == "human_required"
        assert decision.reasons == ("unbounded_mutation",)


def test_unbounded_risky_network_access_escalates_to_human() -> None:
    decision = decide_approval(
        {
            "action": "external_research",
            "capabilities": ["network_access"],
            "cost_visibility": "known",
            "estimated_cost_usd": 0.0,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:54:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("unbounded_risky_capability:network_access",)


def test_irreversible_mutation_escalates_to_human() -> None:
    decision = decide_approval(
        {
            "action": "workspace_patch",
            "capabilities": ["filesystem_write"],
            "bounded_scope": True,
            "reversible": False,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:54:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("irreversible_mutation",)


def test_unknown_mutation_reversibility_escalates_to_human() -> None:
    decision = decide_approval(
        {
            "action": "workspace_patch",
            "capabilities": ["filesystem_write"],
            "bounded_scope": True,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:54:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("unknown_mutation_reversibility",)


def test_missing_action_cannot_be_auto_approved() -> None:
    decision = decide_approval({}, ApprovalPolicy(), now="2026-07-23T03:54:00Z")

    assert decision.mode == "human_required"
    assert decision.reasons == ("missing_action",)


def test_invalid_grant_expiry_policy_cannot_auto_approve() -> None:
    decision = decide_approval(
        {"action": "local_read"},
        ApprovalPolicy(default_expiry_minutes=0),
        now="2026-07-23T03:54:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("invalid_grant_expiry",)


def test_critical_capability_escalates_to_human() -> None:
    decision = decide_approval(
        {
            "action": "inspect_private_context",
            "capabilities": ["private_path_access"],
            "bounded_scope": True,
        },
        ApprovalPolicy(),
        now="2026-07-23T03:55:00Z",
    )

    assert decision.mode == "human_required"
    assert decision.reasons == ("critical_capabilities:private_path_access",)


def test_approval_policy_defaults_and_override(tmp_path) -> None:
    defaults = load_approval_policy(tmp_path / "defaults")
    assert defaults.require_approval_above_usd == 0.10
    assert defaults.default_mode == "auto"
    assert "shell_execution" in defaults.risky_capabilities

    root = tmp_path / "override"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "approval_policy.yml").write_text(
        "approval_policy:\n  require_approval_above_usd: 100.0",
        encoding="utf-8",
    )
    assert load_approval_policy(root).require_approval_above_usd == 100.0


def test_decision_card_lifecycle_in_approval_ledger() -> None:
    ledger = ApprovalLedger("test_proj")
    card = DecisionCard.create(
        decision_type="budget",
        reason="Test reason",
        task_id="t1",
        decision_id="d1",
    )
    assert card.status == "pending"
    assert card.decision_id == "d1"
    assert card.decision_type == "budget"

    ledger.create_decision_card(card)
    assert len(ledger.list_pending()) == 1
    ledger.approve_decision("d1", "operator", "Looks good")

    assert not ledger.list_pending()
    assert ledger.approvals[0].status == "approved"
    assert len(ledger.events) == 2
    assert ledger.events[1]["action"] == "approved"


def test_automatic_policy_grant_is_recorded_as_approved() -> None:
    ledger = ApprovalLedger("test_proj")
    decision = decide_approval(
        {
            "action": "workspace_patch",
            "task_id": "t-auto",
            "capabilities": ["filesystem_write"],
            "bounded_scope": True,
            "reversible": True,
        },
        ApprovalPolicy(),
        now="2026-07-23T04:00:00Z",
    )

    card = ledger.record_policy_decision(decision, task_id="t-auto")

    assert card.status == "approved"
    assert card.requested_by == "policy:default-auto"
    assert card.authorization["decision_mode"] == "policy_auto_approved"
    assert card.authorization["scope_hash"]
    assert ledger.list_pending() == []
    assert ledger.events[0]["action"] == "auto_approved"


def test_forbidden_policy_decision_cannot_be_human_approved() -> None:
    ledger = ApprovalLedger("test_proj")
    decision = decide_approval(
        {"action": "evidence_tampering"},
        ApprovalPolicy(),
        now="2026-07-23T04:00:00Z",
    )
    card = ledger.record_policy_decision(decision, task_id="t-forbidden")

    changed = ledger.approve_decision(card.decision_id, "operator", "override")

    assert changed is False
    assert card.status == "rejected"
    assert all(event["action"] != "approved" for event in ledger.events)


def test_risk_gate_emits_cost_and_capability_decisions() -> None:
    cases = (
        (
            ApprovalPolicy(require_approval_for_unknown_cli_cost=True),
            {
                "action": "external_execution",
                "cost_visibility": "unknown_external_cli_cost",
                "required_capabilities": [],
                "bounded_scope": True,
                "reversible": True,
            },
            "cost",
            "pending",
        ),
        (
            ApprovalPolicy(
                require_approval_for_risky_capabilities=True,
                risky_capabilities=["shell_execution"],
                critical_capabilities=["secrets"],
            ),
            {
                "action": "task_execution",
                "cost_visibility": "known",
                "estimated_cost_usd": 0.0,
                "required_capabilities": ["shell_execution"],
                "bounded_scope": True,
                "reversible": True,
            },
            "capability",
            "approved",
        ),
    )
    for policy, packet, decision_type, status in cases:
        cards = evaluate_risk(packet, policy)
        assert len(cards) == 1
        assert cards[0].decision_type == decision_type
        assert cards[0].status == status
        assert cards[0].authorization["decision_mode"] in {"human_required", "policy_auto_approved"}


def test_risk_gate_fails_closed_when_runtime_packet_is_incomplete() -> None:
    card = evaluate_risk({}, ApprovalPolicy())[0]

    assert card.status == "pending"
    assert card.authorization["decision_mode"] == "human_required"
    assert card.reason == "missing_action"
