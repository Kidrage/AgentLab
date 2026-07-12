from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.media_series_scaffold_audit import build_media_series_scaffold_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_media_series_scaffold_audit_checks_candidate_integrity(
    private_crown_project_root: Path,
) -> None:
    report = build_media_series_scaffold_audit(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "pass"
    assert by_id["active_route_uses_media_pack"]["status"] == "pass"
    assert by_id["active_agents_are_media_chain"]["status"] == "pass"
    assert by_id["artifact_manifest_passes"]["status"] == "pass"
    assert by_id["required_media_artifacts_are_valid_yaml"]["status"] == "pass"
    assert by_id["media_artifacts_are_candidate_only"]["status"] == "pass"
    assert by_id["delivery_receipt_blocks_promotion"]["status"] == "pass"
    assert by_id["backend_preflight_is_safe_and_explainable"]["status"] == "pass"
    assert by_id["project_media_production_not_modified"]["status"] == "pass"
    assert "block_reason" not in by_id["backend_preflight_is_safe_and_explainable"]
    assert report["summary"]["pack_id"] == "media_series_production"
    assert report["summary"]["live_generation"] is False
    assert "backend_block_reason" not in report["summary"]


def test_media_series_scaffold_audit_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "media_series_scaffold_audit.yml"

    result = runner.invoke(app, ["media-series-scaffold-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_media_series_scaffold_audit"
    assert report["status"] == "pass"
