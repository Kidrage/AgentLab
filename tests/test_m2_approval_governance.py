from __future__ import annotations

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
    assert decision.grant["scope"]["task_id"] == "task-auto-approval"
    assert decision.grant["expires_at"] == "2026-07-24T03:50:00Z"


def test_auto_approval_grant_is_scope_bound_and_expires() -> None:
    request = {
        "action": "workspace_patch",
        "task_id": "task-bound",
        "capabilities": ["filesystem_write"],
        "bounded_scope": True,
        "allowed_files": ["agent_runtime/example.py"],
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

    assert valid.valid is True
    assert changed_scope.valid is False
    assert changed_scope.reasons == ("scope_hash_mismatch",)
    assert expired.valid is False
    assert expired.reasons == ("grant_expired",)


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


def test_missing_action_cannot_be_auto_approved() -> None:
    decision = decide_approval({}, ApprovalPolicy(), now="2026-07-23T03:54:00Z")

    assert decision.mode == "human_required"
    assert decision.reasons == ("missing_action",)


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


def test_risk_gate_emits_cost_and_capability_decisions() -> None:
    cases = (
        (
            ApprovalPolicy(require_approval_for_unknown_cli_cost=True),
            {"cost_visibility": "unknown_external_cli_cost"},
            "cost",
            "pending",
        ),
        (
            ApprovalPolicy(
                require_approval_for_risky_capabilities=True,
                risky_capabilities=["shell_execution"],
                critical_capabilities=["secrets"],
            ),
            {"required_capabilities": ["shell_execution"]},
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
