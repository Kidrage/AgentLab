from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.media_series_scaffold_audit import build_media_series_scaffold_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_media_series_scaffold_audit_marks_removed_legacy_runtime_retired(
    private_crown_project_root: Path,
) -> None:
    report = build_media_series_scaffold_audit(private_crown_project_root)
    by_id = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "retired"
    assert by_id["legacy_scaffold_retired"]["status"] == "pass"
    assert report["summary"]["live_generation"] is False
    assert report["summary"]["active_candidate_available"] is False


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
    assert report["status"] == "retired"
