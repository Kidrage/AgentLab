from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.executors.task_packet import create_task_packet


def _phase(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "project": "DemoProject",
                "phase_id": "phase_001",
                "goal": "Write unit tests for task packet",
                "outputs": ["test_file.py"],
                "acceptance_criteria": ["tests_pass"],
                "evidence_required": ["evidence.yml"],
                "context_summary": "Testing M1 task packets",
                "commands_allowed": ["pytest"],
                "commands_forbidden": ["rm -rf", "git push"],
                "cost_policy": "free_tier",
                "safety_notes": ["No secrets"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_task_packet_schema_and_handoff(tmp_path: Path) -> None:
    phase_plan = _phase(tmp_path / "phase_plan.yml")
    out_dir = tmp_path / "packet_out"

    packet = create_task_packet(phase_plan, "claude_code_handoff", out_dir)

    # Verify task packet fields are fully populated
    tp = packet["task_packet"]
    assert tp["packet_id"] == "DemoProject_phase_001_task"
    assert tp["project_id"] == "DemoProject"
    assert tp["phase_id"] == "phase_001"
    assert tp["executor_type"] == "claude_code_handoff"
    assert tp["objective"] == "Write unit tests for task packet"
    assert tp["context_summary"] == "Testing M1 task packets"
    assert tp["allowed_files"] == ["agent_runtime/**", "tests/**", "docs/**"]
    assert tp["forbidden_files"] == [".env", "agent_runtime/.env", ".git/**"]
    assert tp["required_outputs"] == ["test_file.py"]
    assert tp["acceptance_criteria"] == ["tests_pass"]
    assert tp["commands_allowed"] == ["pytest"]
    assert tp["commands_forbidden"] == ["rm -rf", "git push"]
    assert tp["evidence_required"] == ["evidence.yml"]
    assert tp["rollback_required"] is True
    assert tp["cost_policy"] == "free_tier"
    assert tp["safety_notes"] == ["No secrets"]

    # Verify YAML is written
    tp_file = out_dir / "task_packet.yml"
    assert tp_file.is_file()
    tp_yaml = yaml.safe_load(tp_file.read_text(encoding="utf-8"))
    assert tp_yaml["task_packet"]["packet_id"] == "DemoProject_phase_001_task"

    # Verify handoff markdown generation
    handoff_file = out_dir / "external_execution_handoff.md"
    assert handoff_file.is_file()
    handoff_content = handoff_file.read_text(encoding="utf-8")
    assert "Claude Code Instructions" in handoff_content
    assert "Testing M1 task packets" in handoff_content


def test_task_packet_preserves_structured_governance_route(tmp_path: Path) -> None:
    brain_dir = tmp_path / "project_brain"
    brain_dir.mkdir()
    for name in (
        "project_brief.yml",
        "roadmap.yml",
        "acceptance_history.yml",
        "next_actions.yml",
    ):
        (brain_dir / name).write_text("{}\n", encoding="utf-8")

    phase_plan = tmp_path / "phase_plan.yml"
    phase_plan.write_text(
        yaml.safe_dump(
            {
                "project": "AgentLab",
                "project_type": "codebase_build_project",
                "task_id": "task_narrative_repair_phase0r",
                "phase_id": "phase_0r",
                "goal": "Repair the narrative subsystem from a structured phase plan",
                "project_brain_dir": str(brain_dir),
                "roles": ["Coder"],
                "available_workers": ["claude_code"],
                "approved_workers": ["claude_code"],
                "required_capabilities": ["repo_patch", "test_generation"],
                "assignment_mode": "hybrid_local_company",
                "tier": "performance",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    packet = create_task_packet(phase_plan, "claude_code_handoff", tmp_path / "packet")
    task = packet["task_packet"]

    assert task["project_type"] == "codebase_build_project"
    assert task["task_id"] == "task_narrative_repair_phase0r"
    assert task["roles"] == ["Coder"]
    assert task["available_workers"] == ["claude_code"]
    assert task["approved_workers"] == ["claude_code"]
    assert task["required_capabilities"] == ["repo_patch", "test_generation"]
    assert task["assignment_mode"] == "hybrid_local_company"
    assert task["tier"] == "performance"
