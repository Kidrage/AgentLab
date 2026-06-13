from pathlib import Path

from agent_runtime.router_update.recommendation_loader import load_router_update_policy


def test_load_router_update_policy():
    policy = load_router_update_policy(Path("config/router_update_policy.yml"))
    assert policy.enabled is True
    assert policy.approval["token_file_name"] == "APPROVE_ROUTER_PATCH"


def test_router_update_policy_never_modifies_production_by_default():
    policy = load_router_update_policy(Path("config/router_update_policy.yml"))
    assert policy.safety["never_modify_production_router_directly"] is True
    assert policy.safety["allow_apply_to_production"] is False
    assert policy.safety["require_human_approval"] is True
