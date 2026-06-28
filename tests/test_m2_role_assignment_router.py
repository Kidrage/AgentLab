from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.routing.role_assignment import RoleAssignmentEngine
from agent_runtime.routing.worker_router import route_task_packet
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]


def test_role_preferences_and_coder_fallback() -> None:
    engine = RoleAssignmentEngine(ROOT)
    repo = engine.assign("RepoScout", available_workers=["rg", "claude_code"])
    assert repo.selected_worker == "rg"

    mapper = engine.assign("InterfaceMapper", available_workers=["ast_grep", "claude_code"])
    assert mapper.selected_worker == "ast_grep"

    verifier = engine.assign("Verifier", available_workers=["ruff", "claude_code"])
    assert verifier.selected_worker == "ruff"

    primary_coder = engine.assign("Coder", available_workers=["claude_code", "agy", "aider"])
    assert primary_coder.selected_worker == "claude_code"
    assert primary_coder.fallback_workers == ["agy", "aider"]

    coder = engine.assign("Coder", available_workers=["agy", "aider"])
    assert coder.selected_worker == "agy"
    assert "aider" in coder.fallback_workers
    assert coder.approval_required is True
    assert any(item.worker == "claude_code" for item in coder.rejected_workers)


def test_route_task_writes_explainable_evidence(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "config").symlink_to(ROOT / "config", target_is_directory=True)
    packet = tmp_path / "task_packet.yml"
    packet.write_text(yaml.safe_dump({
        "task_packet": {
            "project_id": "DemoProject",
            "phase_id": "phase1",
            "packet_id": "task_route_1",
            "role": "Coder",
            "available_workers": ["agy", "aider"],
            "allowed_files": ["agent_runtime/**"],
        }
    }), encoding="utf-8")
    result = route_task_packet(packet, root)
    decision = result["route_plan"]["decisions"][0]
    assert decision["selected_worker"] == "agy"
    evidence = Path(decision["evidence_paths"][0])
    assert evidence.exists()
    assert "claude_code" in evidence.read_text(encoding="utf-8")


def test_router_cli_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    assigned = runner.invoke(app, [
        "assign-role", "--role", "Coder", "--available-worker", "agy", "--available-worker", "aider",
    ])
    assert assigned.exit_code == 0
    assert "selected_worker: agy" in assigned.stdout

    decision = tmp_path / "decision.yml"
    payload = RoleAssignmentEngine(ROOT).assign("RepoScout", available_workers=["rg"])
    payload.write(decision)
    explained = runner.invoke(app, ["route-explain", "--decision", str(decision)])
    assert explained.exit_code == 0
    assert "Selected worker: rg" in explained.stdout
