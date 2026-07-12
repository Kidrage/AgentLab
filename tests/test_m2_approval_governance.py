from __future__ import annotations

from agent_runtime.approvals.approval_ledger import ApprovalLedger
from agent_runtime.approvals.approval_policy import ApprovalPolicy, load_approval_policy
from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.approvals.risk_gate import evaluate_risk


def test_approval_policy_defaults_and_override(tmp_path) -> None:
    defaults = load_approval_policy(tmp_path / "defaults")
    assert defaults.require_approval_above_usd == 0.50
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


def test_risk_gate_emits_cost_and_capability_decisions() -> None:
    cases = (
        (
            ApprovalPolicy(require_approval_for_unknown_cli_cost=True),
            {"cost_visibility": "unknown_external_cli_cost"},
            "cost",
            None,
        ),
        (
            ApprovalPolicy(
                require_approval_for_risky_capabilities=True,
                risky_capabilities=["shell_execution"],
                critical_capabilities=["secrets"],
            ),
            {"required_capabilities": ["shell_execution"]},
            "capability",
            "high",
        ),
    )
    for policy, packet, decision_type, risk_level in cases:
        cards = evaluate_risk(packet, policy)
        assert len(cards) == 1
        assert cards[0].decision_type == decision_type
        if risk_level is not None:
            assert cards[0].risk_level == risk_level
