def attribute_cost(entry: dict) -> str:
    return f"{entry.get('role')}-{entry.get('worker')}"
