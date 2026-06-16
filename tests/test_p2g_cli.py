from pathlib import Path
from typer.testing import CliRunner
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))
sys.modules.pop("atomic_io", None)
from run_task import app  # noqa: E402


def test_context_commands_help_and_write():
    runner = CliRunner()
    for cmd in ["context-profile", "context-budget", "context-pack", "context-show", "context-audit"]:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0
    task_id = "task_p2g_cli"
    run_dir = ROOT / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "user_request.md").write_text("csv table dataframe", encoding="utf-8")
    result = runner.invoke(app, ["context-show", "--project", "AgentLab", "--task-id", task_id, "--write"])
    assert result.exit_code == 0, result.output
    assert "Context Governance Summary" in result.output
    assert (run_dir / "context_pack.yml").exists()
