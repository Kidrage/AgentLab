import subprocess
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_run_pipeline_dry_run_shows_context_stages(isolated_agentlab_cli_root: Path):
    root = isolated_agentlab_cli_root
    env = {**os.environ, "AGENTLAB_ROOT": str(root), "DEFAULT_PROJECT": "AgentLab"}
    task_id = "task_p2g_pipeline"
    run_dir = root / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "user_request.md").write_text("Summarize short prompt", encoding="utf-8")
    result = subprocess.run([str(root / "agentlab.sh"), "run-pipeline", "--project", "AgentLab", "--task-id", task_id, "--dry-run"], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert "Traceback" not in result.stderr
    assert "CONTEXT_PROFILE" in result.stdout
    assert (run_dir / "context_profile.yml").exists()
    assert (run_dir / "context_budget.yml").exists()
    assert (run_dir / "context_pack.yml").exists()
    assert (run_dir / "compression_trace.yml").exists()
    yaml.safe_load((run_dir / "context_pack.yml").read_text())


def test_prepare_write_plan_includes_context_summary(isolated_agentlab_cli_root: Path):
    root = isolated_agentlab_cli_root
    env = {**os.environ, "AGENTLAB_ROOT": str(root), "DEFAULT_PROJECT": "AgentLab"}
    task_id = "task_p2g_prepare"
    run_dir = root / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "user_request.md").write_text("architecture strategy roadmap compare tradeoff", encoding="utf-8")
    result = subprocess.run([str(root / "agentlab.sh"), "prepare", "--project", "AgentLab", "--task-id", task_id, "--write-plan", "--overwrite-plan"], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    plan = yaml.safe_load((run_dir / "workflow_plan.yml").read_text())
    assert "context_governance" in plan
    assert "Context Governance Summary" in plan["context_governance"]["summary"]
    assert "mission_contract" not in plan
    mission = yaml.safe_load((run_dir / "mission_contract.yml").read_text())
    assert mission["task_id"] == task_id
    assert mission["compiler_source"] == "rule_based"
    assert (run_dir / "required_capabilities.yml").exists()
    assert (run_dir / "artifact_contracts.yml").exists()
    assert (run_dir / "acceptance_gates.yml").exists()
