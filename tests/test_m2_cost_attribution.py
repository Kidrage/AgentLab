from agent_runtime.costs.attribution import attribute_cost

def test_attribution():
    entry = {"role": "Coder", "worker": "w1"}
    assert attribute_cost(entry) == "Coder-w1"
