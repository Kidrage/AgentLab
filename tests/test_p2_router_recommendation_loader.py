from pathlib import Path

from agent_runtime.router_update.patch_builder import build_router_policy_patch
from agent_runtime.router_update.recommendation_loader import load_router_policy, load_router_update_policy, load_routing_recommendations


FIXTURES = Path("tests/fixtures/p2_router_update")


def test_recommendation_apply_automatically_true_is_ignored(tmp_path: Path):
    recommendations = load_routing_recommendations(FIXTURES / "routing_recommendations_watchlist.yml")
    assert recommendations[0].apply_automatically is False
    patch = build_router_policy_patch(recommendations, load_router_policy(FIXTURES / "router_policy.yml"), load_router_update_policy(Path("config/router_update_policy.yml")), tmp_path)
    assert patch.apply_automatically is False
    assert patch.requires_human_approval is True


def test_unknown_provider_recommendation_warns_not_crash(tmp_path: Path):
    recommendations = load_routing_recommendations(FIXTURES / "routing_recommendations_unknown_provider.yml")
    patch = build_router_policy_patch(recommendations, load_router_policy(FIXTURES / "router_policy.yml"), load_router_update_policy(Path("config/router_update_policy.yml")), tmp_path)
    assert patch.warnings
    assert patch.operations[0].operation_type == "no_op"
