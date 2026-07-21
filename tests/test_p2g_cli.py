from pathlib import Path
from typer.testing import CliRunner
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))
sys.modules.pop("atomic_io", None)
from run_task import app  # noqa: E402
from agent_runtime.knowledge_system.storage import KnowledgeStore  # noqa: E402


def test_context_commands_help_and_write(
    isolated_agentlab_root: Path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTLAB_ROOT", str(isolated_agentlab_root))
    runner = CliRunner()
    for cmd in ["context-profile", "context-budget", "context-pack", "context-show", "context-audit", "context-build"]:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0
    task_id = "task_p2g_cli"
    run_dir = isolated_agentlab_root / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "user_request.md").write_text("csv table dataframe", encoding="utf-8")
    result = runner.invoke(app, ["context-show", "--project", "AgentLab", "--task-id", task_id, "--write"])
    assert result.exit_code == 0, result.output
    assert "Context Governance Summary" in result.output
    assert (run_dir / "context_pack.yml").exists()

    build_result = runner.invoke(
        app,
        [
            "context-build",
            "--project",
            "AgentLab",
            "--task-id",
            task_id,
            "--request",
            "csv table dataframe",
        ],
    )
    assert build_result.exit_code == 0, build_result.output
    assert "Context artifacts built" in build_result.output
    assert (run_dir / "compression_trace.yml").exists()


def test_knowledge_commands_build_activate_validate_and_search(
    isolated_agentlab_root: Path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTLAB_ROOT", str(isolated_agentlab_root))
    source = isolated_agentlab_root / "agent_runtime" / "knowledge_fixture.py"
    source.write_text("CLI-RAG-SCAFFOLD-EVIDENCE\n", encoding="utf-8")
    brain = isolated_agentlab_root / "projects" / "AgentLab" / "project_brain"
    brain.mkdir(parents=True)
    (brain / "architecture.yml").write_text(
        "fact: CLI-RAG-SCAFFOLD-EVIDENCE\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    help_result = runner.invoke(app, ["knowledge", "--help"])
    assert help_result.exit_code == 0, help_result.output
    for command in ("build", "status", "activate", "validate", "search", "doctor"):
        assert command in help_result.output
    build_help = runner.invoke(app, ["knowledge", "build", "--help"])
    assert build_help.exit_code == 0, build_help.output
    assert "allowlisted project" in build_help.output

    built = runner.invoke(app, ["knowledge", "build", "--all-projects"])
    assert built.exit_code == 0, built.output
    assert "BUILT" in built.output
    shadow = runner.invoke(
        app,
        [
            "knowledge", "activate", "--mode", "shadow", "--actor", "tester",
            "--reason", "observe governed retrieval",
        ],
    )
    assert shadow.exit_code == 0, shadow.output
    validated = runner.invoke(
        app,
        [
            "knowledge", "validate", "--project", "AgentLab",
            "--task-id", "task_cli_shadow", "--domain", "code_engineering",
            "--request", "CLI-RAG-SCAFFOLD-EVIDENCE",
        ],
    )
    assert validated.exit_code == 0, validated.output
    assert "PASS" in validated.output
    assist = runner.invoke(
        app,
        [
            "knowledge", "activate", "--mode", "assist", "--actor", "tester",
            "--reason", "inject governed evidence",
        ],
    )
    assert assist.exit_code == 0, assist.output
    search = runner.invoke(
        app,
        [
            "knowledge", "search", "--project", "AgentLab",
            "--task-id", "task_cli_search", "--domain", "code_engineering",
            "--query", "CLI-RAG-SCAFFOLD-EVIDENCE",
        ],
    )
    assert search.exit_code == 0, search.output
    assert "READY" in search.output
    status = runner.invoke(app, ["knowledge", "status"])
    assert status.exit_code == 0, status.output
    assert "mode: assist" in status.output
    doctor = runner.invoke(app, ["knowledge", "doctor"])
    assert doctor.exit_code == 0, doctor.output
    assert "PASS" in doctor.output

    store = KnowledgeStore(
        isolated_agentlab_root,
        ".agentlab_runtime/knowledge",
        "auto",
    )
    store.mark_stale("project.AgentLab")
    stale_doctor = runner.invoke(app, ["knowledge", "doctor"])
    assert stale_doctor.exit_code == 1
    assert "knowledge_spaces_fresh: false" in stale_doctor.output
