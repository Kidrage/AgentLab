from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.crown_candidate_audit import build_crown_live_candidate_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_crown_live_candidate_audit_checks_candidate_integrity(
    private_crown_project_root: Path,
) -> None:
    report = build_crown_live_candidate_audit(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "pass"
    assert by_id["required_files_present"]["status"] == "pass"
    assert by_id["delivery_protocol_valid"]["status"] == "pass"
    assert by_id["draft_substantial"]["metrics"]["lines"] >= 100
    assert by_id["chapter_packet_reset_baseline"]["status"] == "pass"
    assert by_id["state_transition_candidate_only"]["status"] == "pass"
    assert by_id["production_manuscript_not_modified"]["status"] == "pass"
    assert report["summary"]["candidate_only"] is True


def test_crown_live_candidate_audit_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "crown_live_candidate_audit.yml"

    result = runner.invoke(app, ["crown-live-candidate-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_crown_live_candidate_audit"
    assert report["status"] == "pass"
