from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.crown_scale_governance_audit import build_crown_scale_governance_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_crown_scale_governance_audit_passes_without_prose_claim() -> None:
    report = build_crown_scale_governance_audit(ROOT)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["report_type"] == "crown_scale_governance_audit"
    assert report["status"] == "pass"
    assert report["chapter_count"] == 1500
    assert report["target_total_chapters"] == 1500
    assert report["text_generation_claimed"] is False
    assert by_id["target_chapter_count"]["status"] == "pass"
    assert by_id["governance_only_scope"]["status"] == "pass"
    assert by_id["ledger_files_present"]["status"] == "pass"


def test_crown_scale_governance_audit_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "crown_scale_governance_audit.yml"

    result = runner.invoke(app, ["crown-scale-governance-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["scope"] == "governance_ledger_only"
