from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.evaluation.generalization_suite import (
    REQUIRED_FIXTURE_DOMAINS,
    evaluate_fixture,
    load_generalization_fixtures,
    run_generalization_suite,
    run_pipeline_replay,
)
from agent_runtime.run_task import app


def test_s10_fixtures_cover_required_domains_without_external_execution() -> None:
    root = Path(__file__).resolve().parents[1]
    fixtures = load_generalization_fixtures(root)

    assert {fixture.domain for fixture in fixtures} == REQUIRED_FIXTURE_DOMAINS
    assert len(fixtures) >= 11
    for fixture in fixtures:
        assert fixture.offline_only is True
        assert fixture.allow_external_execution is False
        assert fixture.expected_route
        assert fixture.required_artifacts


def test_s10_evaluator_scores_fixture_deterministically(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = load_generalization_fixtures(root)[0]

    first = evaluate_fixture(fixture, out_dir=tmp_path / "first")
    second = evaluate_fixture(fixture, out_dir=tmp_path / "second")

    assert first["fixture_id"] == second["fixture_id"]
    assert first["pass"] is True
    assert first["external_execution"] == "blocked"
    assert first["score"] == 1.0
    assert first["artifacts_present"] == fixture.required_artifacts


def test_s10_suite_writes_results_and_report(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]

    summary = run_generalization_suite(root, out_dir=tmp_path)

    assert summary["verdict"] == "PASS"
    assert summary["passed"] == summary["total"]
    assert summary["offline_only"] is True
    results_path = tmp_path / "generalization_results.yml"
    report_path = tmp_path / "S10_GENERALIZATION_EVAL_REPORT.md"
    assert results_path.exists()
    assert report_path.exists()
    loaded = yaml.safe_load(results_path.read_text())
    assert loaded["verdict"] == "PASS"
    assert "api_key" not in results_path.read_text().lower()
    assert "password" not in results_path.read_text().lower()
    assert "token" not in results_path.read_text().lower()


def test_s10_suite_results_are_reproducible(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    first = tmp_path / "first"
    second = tmp_path / "second"

    run_generalization_suite(root, out_dir=first)
    run_generalization_suite(root, out_dir=second)

    assert (first / "generalization_results.yml").read_text(encoding="utf-8") == (
        second / "generalization_results.yml"
    ).read_text(encoding="utf-8")


def test_s10_ci_gate_policy_includes_generalization_and_s9_checks() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = yaml.safe_load((root / "config/ci_gate_policy.yml").read_text())

    commands = [gate["command"] for gate in policy["gates"]]
    assert "python -m pytest -q tests/test_s9_capability_fabric.py tests/test_s10_generalization_eval.py" in commands
    assert "./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval" in commands
    assert "python scripts/audit_text_integrity.py --fail-on-suspicious" in commands
    assert policy["offline_only"] is True
    assert policy["allow_external_execution"] is False


def test_s10_cli_runs_generalization_and_ci_gates(tmp_path: Path) -> None:
    runner = CliRunner()

    eval_result = runner.invoke(app, ["eval-generalization", "--out", str(tmp_path / "eval")])
    assert eval_result.exit_code == 0
    assert (tmp_path / "eval" / "generalization_results.yml").exists()

    gates_result = runner.invoke(app, ["ci-gates", "--dry-run"])
    assert gates_result.exit_code == 0
    assert "eval-generalization" in gates_result.stdout
    assert "pytest" in gates_result.stdout


def test_s10_pipeline_replay_generates_required_artifacts_through_agentlab_chain(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = load_generalization_fixtures(root)[0]

    replay = run_pipeline_replay(root, tmp_path, fixture)

    assert replay["pass"] is True
    assert replay["external_execution"] == "blocked"
    assert replay["artifacts_present"] == replay["required_artifacts"]
    assert replay["generated_by_agentlab_chain"] == [
        "create_task_packet",
        "route_task_packet",
        "accept_phase",
        "project_brain_acceptance_writeback",
    ]


def test_s10_cli_can_run_pipeline_replay_mode(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["eval-generalization", "--out", str(tmp_path / "eval"), "--replay-pipeline"])

    assert result.exit_code == 0
    assert "pipeline_replay" in result.stdout
    assert (tmp_path / "eval" / "pipeline_replay").exists()
