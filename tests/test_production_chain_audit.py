from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.production_chain_audit import build_production_chain_audit
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_production_chain_audit_covers_representative_chains() -> None:
    report = build_production_chain_audit(ROOT)
    by_id = {item["scenario_id"]: item for item in report["scenarios"]}

    assert report["status"] == "pass"
    assert report["pack_catalog_audit"]["status"] == "pass"
    assert report["pack_catalog_audit"]["issues"] == []
    assert all(item["state_governance"]["status"] == "pass" for item in report["scenarios"])
    assert all(item["agent_lifecycle_coverage"]["status"] == "pass" for item in report["scenarios"])
    assert any(
        "lifecycle nodes, memory contract, task-state records, quality gates, and artifact intent" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        "audit-only routes do not activate generation nodes" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        "every route agent" in invariant and "effective lifecycle node" in invariant
        for invariant in report["invariants"]
    )
    assert any(
        item["route"] == "media_generation_task"
        and item["status"] == "selector_disjoint"
        and set(item["pack_ids"]) == {"media_series_production", "media_generation"}
        for item in report["pack_catalog_audit"]["selector_overlaps"]
    )
    assert by_id["code_factory_web_ui"]["production_pack"]["pack_id"] == "code_factory"
    assert "Coder" in by_id["code_factory_web_ui"]["agents"]
    assert by_id["narrative_light_chapter"]["agents"] == ["Supervisor", "Writer"]
    assert by_id["narrative_light_chapter"]["agent_lifecycle_coverage"]["coverage"]["Supervisor"] == [
        "SUPERVISOR_PLAN"
    ]
    assert by_id["narrative_light_chapter"]["agent_lifecycle_coverage"]["coverage"]["Writer"] == [
        "WRITER_DRAFT"
    ]
    assert by_id["narrative_light_chapter"]["production_pack"]["pack_id"] == "narrative_longform"
    assert "chapter_packet.yml" in by_id["narrative_light_chapter"]["active_task_state"]
    assert by_id["narrative_light_chapter"]["state_governance"]["has_memory_contract"] is True
    assert by_id["narrative_light_chapter"]["state_governance"]["has_task_state_records"] is True
    assert by_id["narrative_light_chapter"]["state_governance"]["has_quality_gates"] is True
    assert by_id["article_light_draft"]["production_pack"]["pack_id"] == "article_light"
    assert by_id["article_light_draft"]["state_governance"]["has_artifact_intent"] is True
    assert by_id["article_light_draft"]["state_governance"]["has_task_state_records"] is True
    assert by_id["narrative_heavy_audit"]["production_pack"]["pack_id"] == "narrative_longform"
    assert "WRITER_DRAFT" in by_id["narrative_heavy_audit"]["production_pack"]["lifecycle_nodes"]
    assert "WRITER_DRAFT" not in by_id["narrative_heavy_audit"]["production_pack"]["effective_lifecycle_nodes"]
    assert "WRITER_DRAFT" in by_id["narrative_heavy_audit"]["production_pack"]["inactive_route_lifecycle_nodes"]
    assert by_id["narrative_heavy_audit"]["agent_lifecycle_coverage"]["coverage"]["Reviewer"] == [
        "FICTION_REVIEW"
    ]
    assert by_id["narrative_heavy_audit"]["agent_lifecycle_coverage"]["coverage"]["Scribe"] == [
        "SCRIBE_LEDGER"
    ]
    assert by_id["narrative_heavy_audit"]["agent_lifecycle_coverage"]["coverage"][
        "NarrativePlanner"
    ] == ["NARRATIVE_REWRITE_PLAN"]
    assert by_id["narrative_heavy_audit"]["agents"] == [
        "Supervisor",
        "Reviewer",
        "Scribe",
        "NarrativePlanner",
        "Verifier",
    ]
    assert "Writer" not in by_id["narrative_heavy_audit"]["agents"]
    assert by_id["media_series_production"]["production_pack"]["pack_id"] == "media_series_production"
    assert "Coder" not in by_id["media_series_production"]["agents"]
    assert by_id["media_series_production"]["state_governance"]["has_lifecycle_nodes"] is True
    assert by_id["media_series_production"]["state_governance"]["has_task_state_records"] is True
    assert by_id["unknown_non_code_pack_synthesis"]["production_pack"]["pack_id"] == "pack_synthesis_candidate"
    assert by_id["unknown_non_code_pack_synthesis"]["state_governance"]["has_task_state_records"] is True
    assert by_id["unknown_non_code_pack_synthesis"]["agents"] == [
        "Supervisor",
        "Researcher",
        "ArtifactProducer",
        "Verifier",
    ]


def test_production_chain_audit_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "production_chain_audit.yml"

    result = runner.invoke(app, ["production-chain-audit", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_production_chain_audit"
    assert report["status"] == "pass"
