from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.approvals.approval_ledger import ApprovalLedger, load_approval_ledger, write_approval_ledger

def test_approval_ledger():
    ledger = ApprovalLedger("test_proj")
    card = DecisionCard.create(reason="Test", decision_id="d1")
    ledger.create_decision_card(card)

    assert len(ledger.list_pending()) == 1

    ledger.approve_decision("d1", "operator", "Looks good")

    assert len(ledger.list_pending()) == 0
    assert ledger.approvals[0].status == "approved"

    events = ledger.events
    assert len(events) == 2
    assert events[1]["action"] == "approved"
