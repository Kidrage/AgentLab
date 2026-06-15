from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_skill_draft_cli_flow(tmp_path: Path) -> None:
    project = "CliDemo"
    task_id = "task_cli"
    project_dir = ROOT / "projects" / project
    run_dir = project_dir / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project_memory.md").write_text("# Memory\n- CLI distill reusable step.\n", encoding="utf-8")
    (run_dir / "07_validation_report.md").write_text("pytest pass\n", encoding="utf-8")
    try:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "agent_runtime"))
        distill = subprocess.run(["bash", "agentlab.sh", "skill-distill", "--project", project, "--task-id", task_id], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert distill.returncode == 0, distill.stderr + distill.stdout
        list_result = subprocess.run(["bash", "agentlab.sh", "skill-draft-list", "--project", project], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert list_result.returncode == 0
        pointer_paths = list(run_dir.glob("skill_drafts/*/POINTER.yml"))
        assert pointer_paths
        pointer = yaml.safe_load(pointer_paths[0].read_text(encoding="utf-8"))
        draft_id = pointer["skill_id"]
        metadata_path = ROOT / "memory" / "global" / "skills" / "drafts" / draft_id / "metadata.yml"
        assert metadata_path.exists()
        approve = subprocess.run(["bash", "agentlab.sh", "skill-draft-approve", "--project", project, "--draft-id", draft_id], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert approve.returncode == 0, approve.stderr + approve.stdout
        approved_metadata = ROOT / "memory" / "global" / "skills" / "approved" / draft_id / "metadata.yml"
        data = yaml.safe_load(approved_metadata.read_text(encoding="utf-8"))
        assert data["status"] == "approved"
        assert not (ROOT / "skills" / "active" / draft_id).exists()
    finally:
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)
        shutil.rmtree(ROOT / "memory" / "global" / "skills", ignore_errors=True)
