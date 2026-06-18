from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_plan_cli_generates_yaml_and_markdown(tmp_path: Path) -> None:
    out_dir = tmp_path / "workflow_plan_demo"
    completed = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "workflow-plan",
            "--mission-contract",
            str(ROOT / "examples" / "mission_contracts" / "coding_bug.yml"),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    yaml_path = out_dir / "workflow_plan.yml"
    md_path = out_dir / "workflow_plan.md"
    assert yaml_path.exists()
    assert md_path.exists()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["template_id"] == "coding_software_engineering"
    assert "# Workflow Plan" in md_path.read_text(encoding="utf-8")


def test_workflow_plan_cli_missing_contract_fails_cleanly(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "workflow-plan",
            "--mission-contract",
            str(tmp_path / "missing.yml"),
            "--out",
            str(tmp_path / "out"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    combined = completed.stdout + completed.stderr
    assert "mission contract does not exist" in combined
    assert "Traceback" not in combined
