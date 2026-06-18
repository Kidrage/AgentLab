from __future__ import annotations

import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.intelligence.s5_planner import build_s5_research_packet  # noqa: E402
from agent_runtime.local_search.document import Document  # noqa: E402
from agent_runtime.local_search.storage import save_index  # noqa: E402
from run_task import app  # noqa: E402


def _write_fixture_index(root: Path) -> Path:
    docs = root / "docs"
    docs.mkdir()
    (docs / "RECOVERY.md").write_text(
        "# Recovery Policy\n\nS5 requires evidence ledgers before factual claims.\n",
        encoding="utf-8",
    )
    index_path = root / ".agentlab_runtime" / "local_search.jsonl"
    save_index(
        [
            Document.from_file(
                rel_path="docs/RECOVERY.md",
                text=(docs / "RECOVERY.md").read_text(encoding="utf-8"),
                source_category="docs",
                size_bytes=(docs / "RECOVERY.md").stat().st_size,
            )
        ],
        index_path,
    )
    return index_path


def test_s5_packet_generates_evidence_and_recovery_artifacts(tmp_path: Path) -> None:
    mission = tmp_path / "mission_contract.yml"
    mission.write_text(
        yaml.safe_dump(
            {
                "mission_id": "mission_s5",
                "task_type": "research",
                "user_goal": "Research S5 recovery evidence policy",
                "required_capabilities": [{"capability": "local_search"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    s4_dir = tmp_path / "s4"
    s4_dir.mkdir()
    (s4_dir / "promotion_eligibility.yml").write_text(
        yaml.safe_dump({"eligible": True, "blocked_reasons": []}, sort_keys=False),
        encoding="utf-8",
    )
    index_path = _write_fixture_index(tmp_path)

    result = build_s5_research_packet(
        mission_contract_path=mission,
        s4_report_dir=s4_dir,
        local_index_path=index_path,
        out_dir=tmp_path / "s5",
    )

    assert result["ok"] is True
    assert result["local_evidence_count"] >= 1

    evidence = yaml.safe_load((tmp_path / "s5" / "evidence_ledger.yml").read_text(encoding="utf-8"))
    recovery = yaml.safe_load((tmp_path / "s5" / "recovery_packet.yml").read_text(encoding="utf-8"))
    acceptance = yaml.safe_load((tmp_path / "s5" / "phase_acceptance_evidence.yml").read_text(encoding="utf-8"))

    assert evidence["facts_allowed"] is True
    assert evidence["citation_policy"]["no_sources_no_factual_claims"] is True
    assert recovery["status"] == "ready_for_review"
    assert acceptance["acceptance"]["no_network_used"] is True


def test_s5_packet_blocks_factual_claims_without_sources(tmp_path: Path) -> None:
    result = build_s5_research_packet(
        topic="No source research task",
        out_dir=tmp_path / "s5",
    )
    evidence = yaml.safe_load((tmp_path / "s5" / "evidence_ledger.yml").read_text(encoding="utf-8"))
    recovery = yaml.safe_load((tmp_path / "s5" / "recovery_packet.yml").read_text(encoding="utf-8"))

    assert result["local_evidence_count"] == 0
    assert evidence["facts_allowed"] is False
    assert "no_local_evidence" in recovery["blocked_reasons"]


def test_s5_cli_commands_work_offline(tmp_path: Path) -> None:
    index_path = _write_fixture_index(tmp_path)
    runner = CliRunner()

    query_result = runner.invoke(
        app,
        [
            "local-search-query",
            "--root",
            str(tmp_path),
            "--index",
            str(index_path),
            "--query",
            "evidence ledger",
            "--out",
            "query_results.yml",
        ],
    )
    assert query_result.exit_code == 0, query_result.output
    assert (tmp_path / "query_results.yml").exists()

    plan_result = runner.invoke(
        app,
        [
            "web-research-plan",
            "--topic",
            "S5 recovery evidence policy",
            "--local-index",
            str(index_path),
            "--out",
            str(tmp_path / "packet"),
        ],
    )
    assert plan_result.exit_code == 0, plan_result.output
    assert (tmp_path / "packet" / "research_plan.yml").exists()
