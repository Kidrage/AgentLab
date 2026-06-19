from __future__ import annotations

import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.recovery.alternative_route_planner import build_s6_recovery_brain_packet  # noqa: E402
from agent_runtime.recovery.capability_gap_resolver import build_capability_gap_decision_card  # noqa: E402
from agent_runtime.recovery.fake_evidence_detector import detect_fake_evidence  # noqa: E402
from agent_runtime.recovery.strategy_search import search_recovery_strategy  # noqa: E402
from run_task import app  # noqa: E402


def test_evidence_missing_hard_fails() -> None:
    report = detect_fake_evidence({"facts_allowed": True, "sources": []})
    assert report["verdict"] == "fail"
    assert report["hard_fail"] is True
    assert "facts_allowed_without_sources" in report["issues"]


def test_line_start_end_counts_as_line_refs() -> None:
    report = detect_fake_evidence(
        {
            "facts_allowed": True,
            "sources": [
                {
                    "content_hash": "abc123",
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        }
    )
    assert report["verdict"] == "pass"
    assert report["hard_fail"] is False


def test_skill_missing_recommends_skill_search() -> None:
    strategy = search_recovery_strategy("skill_missing")
    assert strategy.next_action == "search_skill"
    assert strategy.requires_human_approval is True
    assert strategy.safe_to_auto_execute is False


def test_capability_gap_generates_decision_card() -> None:
    card = build_capability_gap_decision_card(
        {
            "required_capabilities": [
                {"capability": "vision"},
                {"capability": "audio"},
            ]
        },
        available_capabilities=["local_search"],
    )
    assert card["status"] == "blocked"
    assert card["human_decision_required"] is True
    assert "vision" in card["missing_capabilities"]
    assert "audio" in card["missing_capabilities"]


def test_s6_packet_writes_route_and_ledger(tmp_path: Path) -> None:
    mission = tmp_path / "mission_contract.yml"
    mission.write_text(
        yaml.safe_dump(
            {
                "mission_id": "mission_s6",
                "task_type": "multimodal",
                "user_goal": "Analyze an uploaded image",
                "required_capabilities": [{"capability": "vision"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence_ledger.yml"
    evidence.write_text(yaml.safe_dump({"facts_allowed": True, "sources": []}), encoding="utf-8")

    result = build_s6_recovery_brain_packet(
        out_dir=tmp_path / "s6",
        mission_contract_path=mission,
        evidence_ledger_path=evidence,
    )
    assert result["ok"] is True
    assert result["failure_type"] == "evidence_missing"
    assert result["next_action"] == "stop_safely"

    route = yaml.safe_load((tmp_path / "s6" / "alternative_route_plan.yml").read_text(encoding="utf-8"))
    ledger = yaml.safe_load((tmp_path / "s6" / "recovery_strategy_ledger.yml").read_text(encoding="utf-8"))
    fake = yaml.safe_load((tmp_path / "s6" / "fake_evidence_report.yml").read_text(encoding="utf-8"))
    card = yaml.safe_load((tmp_path / "s6" / "capability_gap_decision_card.yml").read_text(encoding="utf-8"))
    acceptance = yaml.safe_load((tmp_path / "s6" / "phase_acceptance_evidence.yml").read_text(encoding="utf-8"))

    assert route["no_infinite_retry"] is True
    assert ledger["entries"][0]["failure_type"] == "evidence_missing"
    assert fake["hard_fail"] is True
    assert "vision" in card["missing_capabilities"]
    assert acceptance["acceptance"]["evidence_missing_hard_fails"] is True


def test_s6_cli_command_works_offline(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence_ledger.yml"
    evidence.write_text(yaml.safe_dump({"facts_allowed": False, "sources": []}), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "recovery-brain-plan",
            "--failure-type",
            "provider_failed",
            "--evidence-ledger",
            str(evidence),
            "--out",
            str(tmp_path / "packet"),
        ],
    )
    assert result.exit_code == 0, result.output
    plan = yaml.safe_load((tmp_path / "packet" / "recovery_strategy_plan.yml").read_text(encoding="utf-8"))
    assert plan["failure_type"] == "provider_failed"
    assert plan["strategy"]["next_action"] == "retry_with_stronger_model"