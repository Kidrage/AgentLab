from agent_runtime.costs.estimator import estimate_cost

def test_estimate_cost():
    assert estimate_cost({}) == 1.50
