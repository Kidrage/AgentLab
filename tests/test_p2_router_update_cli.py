from pathlib import Path

from scripts.p2_router_update_check import main


FIXTURES = Path("tests/fixtures/p2_router_update")


def test_router_update_cli_stage_writes_patch_and_approval(tmp_path: Path):
    code = main(["stage", "--recommendations", str(FIXTURES / "routing_recommendations_quarantine.yml"), "--router-policy", str(FIXTURES / "router_policy.yml"), "--output", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "router_policy_patch.yml").is_file()
    assert (tmp_path / "approval_request.yml").is_file()


def test_router_update_cli_apply_copy_requires_approval(tmp_path: Path):
    main(["stage", "--recommendations", str(FIXTURES / "routing_recommendations_quarantine.yml"), "--router-policy", str(FIXTURES / "router_policy.yml"), "--output", str(tmp_path)])
    code = main(["apply-copy", "--router-policy", str(FIXTURES / "router_policy.yml"), "--patch", str(tmp_path / "router_policy_patch.yml"), "--output", str(tmp_path / "patched.yml"), "--approval-dir", str(tmp_path)])
    assert code == 1
    assert not (tmp_path / "patched.yml").exists()


def test_router_update_cli_apply_copy_with_approval_succeeds(tmp_path: Path):
    main(["stage", "--recommendations", str(FIXTURES / "routing_recommendations_quarantine.yml"), "--router-policy", str(FIXTURES / "router_policy.yml"), "--output", str(tmp_path)])
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    code = main(["apply-copy", "--router-policy", str(FIXTURES / "router_policy.yml"), "--patch", str(tmp_path / "router_policy_patch.yml"), "--output", str(tmp_path / "patched.yml"), "--approval-dir", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "patched.yml").is_file()


def test_router_update_cli_validate_patched_policy(tmp_path: Path):
    main(["stage", "--recommendations", str(FIXTURES / "routing_recommendations_watchlist.yml"), "--router-policy", str(FIXTURES / "router_policy.yml"), "--output", str(tmp_path)])
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    main(["apply-copy", "--router-policy", str(FIXTURES / "router_policy.yml"), "--patch", str(tmp_path / "router_policy_patch.yml"), "--output", str(tmp_path / "patched.yml"), "--approval-dir", str(tmp_path)])
    assert main(["validate", "--router-policy", str(tmp_path / "patched.yml")]) == 0


def test_router_update_cli_never_modifies_config_executor_router(tmp_path: Path):
    original = Path("config/executor_router.yml").read_text(encoding="utf-8")
    main(["stage", "--recommendations", "docs/archive/historical_runs/governance_runs/p2_provider_governance_demo/routing_recommendations.yml", "--router-policy", "config/executor_router.yml", "--output", str(tmp_path)])
    (tmp_path / "APPROVE_ROUTER_PATCH").write_text("APPROVED\n", encoding="utf-8")
    main(["apply-copy", "--router-policy", "config/executor_router.yml", "--patch", str(tmp_path / "router_policy_patch.yml"), "--output", str(tmp_path / "patched.yml"), "--approval-dir", str(tmp_path)])
    assert Path("config/executor_router.yml").read_text(encoding="utf-8") == original
