from pathlib import Path

import yaml

from scripts.p2_provider_governance_check import main


def _write_router(root: Path, provider_id: str = "p", cost_mode: str = "none") -> Path:
    path = root / "executor_router.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "executor_router": {
                    "providers": [{"provider_id": provider_id, "provider_type": "mock_executor", "cost_mode": cost_mode}],
                    "provider_priority": {"repo_patch": [provider_id]},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_policy(root: Path) -> Path:
    path = root / "provider_governance.yml"
    path.write_text("provider_governance:\n  enabled: true\n", encoding="utf-8")
    return path


def _write_scorecard(root: Path, provider_id: str, blocked: int = 0) -> None:
    run = root / "retry_runs" / "task"
    run.mkdir(parents=True)
    attempts = 3 if blocked else 2
    run.joinpath("provider_scorecard.yml").write_text(
        yaml.safe_dump(
            {
                "providers": [
                    {
                        "provider_id": provider_id,
                        "provider_type": "mock_executor",
                        "attempts": attempts,
                        "passes": attempts - blocked,
                        "blocked": blocked,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_provider_governance_cli_writes_reports(tmp_path: Path):
    _write_scorecard(tmp_path, "p")
    output = tmp_path / "governance"
    code = main(
        [
            "--input-root",
            str(tmp_path),
            "--output",
            str(output),
            "--policy",
            str(_write_policy(tmp_path)),
            "--router-policy",
            str(_write_router(tmp_path)),
        ]
    )
    assert code == 0
    assert (output / "provider_governance_report.md").is_file()
    assert (output / "routing_recommendations.yml").is_file()


def test_provider_governance_cli_quarantine_exits_nonzero(tmp_path: Path):
    _write_scorecard(tmp_path, "p", blocked=1)
    code = main(
        [
            "--input-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "governance"),
            "--policy",
            str(_write_policy(tmp_path)),
            "--router-policy",
            str(_write_router(tmp_path)),
        ]
    )
    assert code == 1


def test_provider_governance_cli_allow_quarantine_exits_zero(tmp_path: Path):
    _write_scorecard(tmp_path, "p", blocked=1)
    code = main(
        [
            "--input-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "governance"),
            "--policy",
            str(_write_policy(tmp_path)),
            "--router-policy",
            str(_write_router(tmp_path)),
            "--allow-quarantine-recommendations",
        ]
    )
    assert code == 0
