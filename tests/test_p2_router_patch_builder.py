from pathlib import Path

from agent_runtime.governance.models import ProviderRoutingRecommendation
from agent_runtime.router_update.patch_builder import build_router_policy_patch
from agent_runtime.router_update.recommendation_loader import load_router_policy, load_router_update_policy


FIXTURES = Path("tests/fixtures/p2_router_update")


def _patch(recommendation: ProviderRoutingRecommendation, tmp_path: Path):
    return build_router_policy_patch([recommendation], load_router_policy(FIXTURES / "router_policy.yml"), load_router_update_policy(Path("config/router_update_policy.yml")), tmp_path)


def test_require_manual_approval_builds_set_requires_approval_op(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.cline", "require_manual_approval", ["risk"], 0, True, False), tmp_path)
    assert patch.operations[0].operation_type == "set_requires_approval"
    assert patch.operations[0].new_value is True


def test_require_manual_approval_no_op_when_already_true(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.codex", "require_manual_approval", ["risk"], 0, True, False), tmp_path)
    assert patch.operations[0].operation_type == "no_op"


def test_watchlist_adds_note_not_disable(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("agentlab.mock_patch", "watchlist", ["low acceptance"], 0, True, False), tmp_path)
    assert patch.operations[0].operation_type == "add_watchlist_note"
    assert "watchlist_recommended_by_governance" in patch.operations[0].new_value


def test_quarantine_requires_approval_and_downgrades_not_disable(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.cline", "quarantine", ["blocked"], -99, True, False), tmp_path)
    types = {op.operation_type for op in patch.operations}
    assert "set_requires_approval" in types
    assert "add_quarantine_note" in types
    assert "set_enabled" not in types


def test_downgrade_moves_provider_down_without_removing(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.codex", "downgrade", ["expensive"], -1, True, False), tmp_path)
    op = next(item for item in patch.operations if item.operation_type == "adjust_priority")
    assert "manual.codex" in op.new_value
    assert op.new_value.index("manual.codex") > op.old_value.index("manual.codex")


def test_prefer_does_not_enable_disabled_provider(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("api.deepseek", "prefer", ["healthy"], 1, True, False), tmp_path)
    assert patch.operations[0].operation_type == "no_op"
    assert "disabled provider cannot be promoted" in patch.operations[0].reason


def test_prefer_does_not_put_external_auto_provider_before_internal(tmp_path: Path):
    policy = load_router_policy(FIXTURES / "router_policy.yml")
    for provider in policy["executor_router"]["providers"]:
        if provider["provider_id"] == "manual.cline":
            provider["execution_mode"] = "approved_auto"
            provider["requires_approval"] = False
    patch = build_router_policy_patch([ProviderRoutingRecommendation("manual.cline", "prefer", ["healthy"], 1, True, False)], policy, load_router_update_policy(Path("config/router_update_policy.yml")), tmp_path)
    assert patch.operations[0].operation_type == "no_op"


def test_patch_apply_automatically_false(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.cline", "require_manual_approval", ["risk"], 0, True, True), tmp_path)
    assert patch.apply_automatically is False


def test_patch_requires_human_approval_when_ops_exist(tmp_path: Path):
    patch = _patch(ProviderRoutingRecommendation("manual.cline", "require_manual_approval", ["risk"], 0, True, False), tmp_path)
    assert patch.requires_human_approval is True
