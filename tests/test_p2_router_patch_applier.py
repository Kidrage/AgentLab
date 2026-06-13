from pathlib import Path

import yaml

from agent_runtime.governance.models import ProviderRoutingRecommendation
from agent_runtime.router_update.patch_applier import apply_router_policy_patch, validate_router_policy
from agent_runtime.router_update.patch_builder import build_router_policy_patch
from agent_runtime.router_update.recommendation_loader import load_router_policy, load_router_update_policy
from agent_runtime.router_update.report_writer import write_router_patch_artifacts


FIXTURES = Path("tests/fixtures/p2_router_update")


def _stage_patch(tmp_path: Path, recommendation: ProviderRoutingRecommendation | None = None) -> Path:
    policy = load_router_policy(FIXTURES / "router_policy.yml")
    update_policy = load_router_update_policy(Path("config/router_update_policy.yml"))
    rec = recommendation or ProviderRoutingRecommendation("manual.cline", "require_manual_approval", ["risk"], 0, True, False)
    patch = build_router_policy_patch([rec], policy, update_policy, tmp_path)
    write_router_patch_artifacts(tmp_path, patch, policy)
    return tmp_path / "router_policy_patch.yml"


def test_apply_patch_without_approval_is_blocked(tmp_path: Path):
    patch_path = _stage_patch(tmp_path)
    result = apply_router_policy_patch(FIXTURES / "router_policy.yml", patch_path, Path("config/router_update_policy.yml"), tmp_path / "patched.yml", tmp_path)
    assert result.status == "APPROVAL_REQUIRED"
    assert not (tmp_path / "patched.yml").exists()


def test_apply_patch_with_approval_writes_copy(tmp_path: Path):
    patch_path = _stage_patch(tmp_path)
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    result = apply_router_policy_patch(FIXTURES / "router_policy.yml", patch_path, Path("config/router_update_policy.yml"), tmp_path / "patched.yml", tmp_path)
    assert result.status == "APPLIED_TO_COPY"
    assert (tmp_path / "patched.yml").is_file()


def test_apply_patch_never_overwrites_production_policy(tmp_path: Path):
    router = tmp_path / "executor_router.yml"
    router.write_text((FIXTURES / "router_policy.yml").read_text(encoding="utf-8"), encoding="utf-8")
    patch_path = _stage_patch(tmp_path)
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    result = apply_router_policy_patch(router, patch_path, Path("config/router_update_policy.yml"), router, tmp_path)
    assert result.status == "BLOCKED"


def test_apply_patch_generates_rollback_plan(tmp_path: Path):
    patch_path = _stage_patch(tmp_path)
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    apply_router_policy_patch(FIXTURES / "router_policy.yml", patch_path, Path("config/router_update_policy.yml"), tmp_path / "patched.yml", tmp_path)
    assert (tmp_path / "rollback_plan.yml").is_file()


def test_apply_patch_validates_provider_ids_unique():
    policy = load_router_policy(FIXTURES / "router_policy.yml")
    policy["executor_router"]["providers"].append(dict(policy["executor_router"]["providers"][0]))
    assert "provider_id values must be unique" in validate_router_policy(policy)


def test_apply_patch_does_not_enable_auto_execution():
    policy = load_router_policy(FIXTURES / "router_policy.yml")
    policy["executor_router"]["routing"]["allow_auto_execution"] = True
    assert "auto execution must not be enabled" in validate_router_policy(policy)


def test_apply_patch_does_not_enable_disabled_external_provider():
    original = load_router_policy(FIXTURES / "router_policy.yml")
    patched = load_router_policy(FIXTURES / "router_policy.yml")
    for provider in patched["executor_router"]["providers"]:
        if provider["provider_id"] == "api.deepseek":
            provider["enabled"] = True
    assert "disabled external provider enabled: api.deepseek" in validate_router_policy(patched, original)


def test_apply_patch_does_not_empty_provider_priority():
    policy = load_router_policy(FIXTURES / "router_policy.yml")
    policy["executor_router"]["provider_priority"]["repo_patch"] = []
    assert "provider_priority for repo_patch must not be empty" in validate_router_policy(policy)


def test_apply_patch_round_trip_yaml(tmp_path: Path):
    patch_path = _stage_patch(tmp_path)
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    apply_router_policy_patch(FIXTURES / "router_policy.yml", patch_path, Path("config/router_update_policy.yml"), tmp_path / "patched.yml", tmp_path)
    assert yaml.safe_load((tmp_path / "patched.yml").read_text(encoding="utf-8"))
