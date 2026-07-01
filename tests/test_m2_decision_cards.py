from agent_runtime.approvals.decision_card import DecisionCard

def test_decision_card_creation():
    card = DecisionCard.create(
        decision_type="budget",
        reason="Test reason",
        task_id="t1"
    )
    assert card.status == "pending"
    assert card.decision_id is not None
    assert card.decision_type == "budget"
