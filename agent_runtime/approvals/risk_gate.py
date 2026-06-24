from agent_runtime.approvals.decision_card import DecisionCard

def evaluate_risk(capabilities, cli_cost_known=True):
    cards = []
    if not cli_cost_known:
        cards.append(DecisionCard("C001", "unknown external CLI cost"))
    for cap in capabilities:
        if cap in ["shell_execution", "network_access"]:
            cards.append(DecisionCard(f"R_{cap}", f"risky capability: {cap}"))
    return cards
