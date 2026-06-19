from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.ops_console import (
    build_ops_console_snapshot,
    validate_dashboard_policy,
    write_ops_console_snapshot,
)
from agent_runtime.service_factory import (
    build_delivery_package,
    estimate_quote,
    load_service_catalog,
    match_service,
    write_service_factory_artifacts,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]


def test_s11_ops_console_snapshot_is_read_only_redacted_and_local_only(tmp_path: Path) -> None:
    policy = validate_dashboard_policy(ROOT / "config" / "ops_console_policy.yml")
    assert policy["bind_host"] == "127.0.0.1"
    assert policy["default_mode"] == "read_only"
    assert policy["redact_secrets"] is True

    snapshot = build_ops_console_snapshot(ROOT, project="AgentLab")
    assert snapshot["console"]["stage"] == "S11"
    assert snapshot["console"]["bind_host"] == "127.0.0.1"
    assert snapshot["project"]["name"] == "AgentLab"
    assert snapshot["capabilities"]["total"] >= 18
    assert "image_understanding" in snapshot["capabilities"]["ids"]
    assert snapshot["skills"]["request_counts"]
    assert snapshot["decisions"]["supported_actions"] == ["approve", "reject", "resume", "request_replanning"]
    assert snapshot["security"]["secrets_displayed"] is False
    assert all("/Users/" not in yaml.safe_dump(section) for section in snapshot.values())

    out = write_ops_console_snapshot(ROOT, project="AgentLab", out_dir=tmp_path)
    assert out.name == "ops_console_snapshot.yml"
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert written["console"]["read_only"] is True


def test_s11_cli_writes_status_and_rejects_public_bind(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ops-console-status", "--project", "AgentLab", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "ops_console_snapshot.yml" in result.output
    assert (tmp_path / "ops_console_snapshot.yml").exists()

    unsafe = runner.invoke(app, ["ops-console-serve", "--host", "0.0.0.0", "--dry-run"])
    assert unsafe.exit_code != 0
    assert "127.0.0.1" in unsafe.output

    safe = runner.invoke(app, ["ops-console-serve", "--host", "127.0.0.1", "--dry-run"])
    assert safe.exit_code == 0, safe.output
    assert "read_only" in safe.output


def test_s12_service_catalog_quote_and_delivery_package(tmp_path: Path) -> None:
    catalog = load_service_catalog(ROOT / "config" / "service_catalog.yml")
    assert len(catalog) >= 10
    assert {item.service_id for item in catalog} >= {"repo_cleanup", "longform_novel_blueprint", "company_research_report"}

    service = match_service("客户想做一个本地文件整理助手，给报价、周期和交付方案。", catalog)
    assert service.service_id == "local_file_organization"
    quote = estimate_quote(service, complexity="medium")
    assert quote["service_id"] == service.service_id
    assert quote["quote_band"] in {"small", "medium", "large", "enterprise"}
    assert quote["timeline"]["estimated_phases"] == service.estimated_phases
    assert quote["human_approval_count"] == len(service.human_approval_points)

    package_dir = build_delivery_package(tmp_path, service, quote)
    expected = {
        "final_summary.md",
        "acceptance_history.md",
        "risks_and_limitations.md",
        "reproduction_commands.md",
        "next_steps.md",
    }
    assert expected <= {path.name for path in package_dir.iterdir()}
    assert (package_dir / "artifacts").is_dir()
    assert (package_dir / "evidence").is_dir()


def test_s12_cli_writes_factory_artifacts_without_private_paths(tmp_path: Path) -> None:
    runner = CliRunner()
    prompt = "客户想做一个本地文件整理助手，给报价、周期和交付方案。"
    result = runner.invoke(app, ["service-factory-plan", "--prompt", prompt, "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    for name in ["service_match.yml", "quote_estimate.yml", "timeline_estimate.yml"]:
        path = tmp_path / name
        assert path.exists(), name
        assert "/Users/" not in path.read_text(encoding="utf-8")
    assert (tmp_path / "delivery_package" / "final_summary.md").exists()

    data = write_service_factory_artifacts(ROOT, prompt=prompt, out_dir=tmp_path / "direct")
    assert data["service_match"]["service_id"] == "local_file_organization"
    assert data["delivery_package"].endswith("delivery_package")
