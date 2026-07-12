from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.production_pack_synthesis_smoke import run_production_pack_synthesis_smoke
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_production_pack_synthesis_smoke_generates_valid_candidate(tmp_path: Path) -> None:
    report = run_production_pack_synthesis_smoke(
        ROOT,
        task_id="task_pytest_pack_synthesis_smoke",
        out=tmp_path / "smoke.yml",
    )

    assert report["status"] == "pass"
    assert report["production_pack"]["status"] == "synthesis_candidate"
    assert report["synthesis_shell"]["pack_id"] == "pack_synthesis_candidate"
    assert report["agents"] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    assert report["proposal_validation"]["valid"] is True
    assert report["proposal_validation"]["pack"]["pack_id"].startswith("synth_")
    assert report["validated_candidate_pack"]["pack_id"] == report["proposal_validation"]["pack"]["pack_id"]
    assert report["validated_candidate_pack"]["pack_id"] != report["synthesis_shell"]["pack_id"]
    resource_contract = report["validated_candidate_pack"]["resource_contract"]
    assert "approved_external_research" in resource_contract["allowed_sources"]
    assert resource_contract["external_research_requires_approval"] is True
    assert resource_contract["external_research_may_not_write_project_memory"] is True
    assert resource_contract["evidence_to_memory_promotion_requires_review"] is True
    assert "resource_evidence_ledger" in resource_contract["external_research_outputs"]
    assert report["pack_identity_boundary"]["status"] == "pass"
    assert report["pack_identity_boundary"]["synthesis_shell_pack_id"] == "pack_synthesis_candidate"
    assert report["pack_identity_boundary"]["validated_candidate_pack_id"].startswith("synth_")
    assert report["generated_artifacts"]["missing"] == []
    assert report["promotion"]["attempted"] is False
    checks = {check["id"]: check for check in report["semantic_checks"]}
    assert checks["pack_identity_boundary"]["status"] == "pass"
    assert checks["research_brief_resource_contract"]["status"] == "pass"
    assert checks["research_brief_external_resource_boundary"]["status"] == "pass"
    assert checks["proposal_resource_contract"]["status"] == "pass"
    assert checks["proposal_external_resource_boundary"]["status"] == "pass"
    assert checks["proposal_promotion_policy"]["status"] == "pass"
    assert checks["memory_contract_closed_loop"]["status"] == "pass"
    assert checks["candidate_fact_boundary"]["status"] == "pass"
    assert checks["lifecycle_excludes_code_shell"]["status"] == "pass"
    assert checks["quality_gates_cover_governance"]["status"] == "pass"


def test_production_pack_synthesis_smoke_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "production_pack_synthesis_smoke.yml"

    result = runner.invoke(
        app,
        [
            "production-pack-synthesis-smoke",
            "--task-id",
            "task_pytest_pack_synthesis_smoke_cli",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_production_pack_synthesis_smoke"
    assert report["status"] == "pass"
    assert report["proposal_validation"]["valid"] is True
    assert report["pack_identity_boundary"]["status"] == "pass"
    assert all(check["status"] == "pass" for check in report["semantic_checks"])
