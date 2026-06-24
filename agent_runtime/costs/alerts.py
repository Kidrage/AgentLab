def check_alerts(ledger, policy):
    total = ledger.get_total()
    hard_limit = policy.get("cost_policy", {}).get("hard_limit_usd", 10.0)
    soft_limit = policy.get("cost_policy", {}).get("soft_limit_usd", 5.0)
    
    if total > hard_limit:
        return "HARD_LIMIT_EXCEEDED"
    elif total > soft_limit:
        return "SOFT_LIMIT_EXCEEDED"
    return "OK"
