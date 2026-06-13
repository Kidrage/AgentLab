from pathlib import Path

import yaml

from agent_runtime.governance.ledger_reader import discover_governance_inputs


def test_discover_governance_inputs_from_retry_runs(tmp_path: Path):
    run = tmp_path / "retry_runs" / "task"
    run.mkdir(parents=True)
    (run / "provider_scorecard.yml").write_text("providers: []\n", encoding="utf-8")
    bundle = discover_governance_inputs(tmp_path)
    assert len(bundle.provider_scorecards) == 1
    assert bundle.manifest["provider_scorecards"] == ["retry_runs/task/provider_scorecard.yml"]


def test_missing_input_dirs_warn_not_crash(tmp_path: Path):
    bundle = discover_governance_inputs(tmp_path)
    assert bundle.execution_ledgers == []
    assert any("missing input directory" in warning for warning in bundle.warnings)


def test_bad_yaml_warns_not_crash(tmp_path: Path):
    run = tmp_path / "executor_runs" / "bad"
    run.mkdir(parents=True)
    (run / "execution_ledger.yml").write_text("entries: [\n", encoding="utf-8")
    bundle = discover_governance_inputs(tmp_path)
    assert bundle.execution_ledgers == []
    assert any("bad yaml" in warning for warning in bundle.warnings)


def test_ledger_reader_redacts_absolute_paths(tmp_path: Path):
    run = tmp_path / "executor_runs" / "path"
    run.mkdir(parents=True)
    (run / "execution_ledger.yml").write_text(
        yaml.safe_dump({"entries": [{"provider_id": "p", "artifacts": [str(tmp_path / "secret.txt")]}]}),
        encoding="utf-8",
    )
    bundle = discover_governance_inputs(tmp_path)
    assert bundle.execution_ledgers[0]["entries"][0]["artifacts"][0] == "[REDACTED_ROOT]/secret.txt"


def test_ledger_reader_does_not_read_secret_files(tmp_path: Path):
    run = tmp_path / "executor_runs" / "secrets"
    run.mkdir(parents=True)
    (run / "execution_ledger.yml").write_text("entries:\n- provider_id: should_not_read\n", encoding="utf-8")
    bundle = discover_governance_inputs(tmp_path)
    assert bundle.execution_ledgers == []
    assert any("skipped secret-like file" in warning for warning in bundle.warnings)
