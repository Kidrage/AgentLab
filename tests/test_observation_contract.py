"""Offline end-to-end coverage for governed Observer attachments."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agent_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from agent_runner import observer_context_source_files  # noqa: E402
from cli_executor import run_cli_agent  # noqa: E402
from agent_runtime.observation_contract import (  # noqa: E402
    ObservationContractError,
    materialize_observation_contract,
)
from workflow_plan import build_workflow_plan  # noqa: E402


@pytest.mark.parametrize(
    "request_text",
    [
        "Create a summary of the attached PDF.",
        "Make a transcript of attached audio.",
        "Produce OCR transcript of this image.",
    ],
)
def test_common_attached_input_wording_selects_read_only_observation_pack(
    tmp_path: Path,
    request_text: str,
) -> None:
    request = tmp_path / "request.md"
    request.write_text(request_text, encoding="utf-8")

    plan = build_workflow_plan(
        ROOT,
        "AgentLab",
        "task_observation_wording_probe",
        user_request_path=request,
    )

    assert plan.route.route_key == "observation_task"
    assert plan.route.agents == ["Supervisor", "Observer"]
    assert plan.production_pack["pack_id"] == "read_only_observation"
    assert "ArtifactProducer" not in plan.included_agents


def _observation_plan(tmp_path: Path):
    request = tmp_path / "request.md"
    request.write_text(
        "Create a summary of the attached PDF and cite its pages.",
        encoding="utf-8",
    )
    plan = build_workflow_plan(
        ROOT,
        "AgentLab",
        "task_observation_attachment_e2e",
        user_request_path=request,
    )
    project_root = tmp_path / "projects" / "AgentLab"
    run_dir = project_root / "runs" / plan.task_id
    plan.agentlab_root = str(tmp_path)
    plan.project_root = str(project_root)
    plan.repo_path = str(project_root / "repo")
    plan.run_dir = str(run_dir)
    plan.user_request_path = str(request)
    return plan


def test_route_workflow_contract_and_observer_stage_exact_attachment(
    tmp_path: Path,
) -> None:
    plan = _observation_plan(tmp_path)
    assert plan.route.route_key == "observation_task"
    assert plan.route.agents == ["Supervisor", "Observer"]
    assert plan.production_pack["pack_id"] == "read_only_observation"

    attachment = tmp_path / "evidence.pdf"
    attachment.write_bytes(b"%PDF-1.4\nexact bounded observation evidence\n%%EOF\n")
    expected_hash = hashlib.sha256(attachment.read_bytes()).hexdigest()
    contract_path = materialize_observation_contract(plan, [attachment])
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    assigned = contract["assigned_inputs"][0]
    assert assigned["sha256"] == expected_hash
    assert assigned["size_bytes"] == attachment.stat().st_size
    assert assigned["read_only"] is True

    output_path = Path(plan.run_dir) / "observation_report.yml"
    context_files = observer_context_source_files(tmp_path, plan, output_path)
    sealed_attachment = Path(plan.run_dir) / assigned["path"]
    assert sealed_attachment in context_files
    assert sealed_attachment.stat().st_mode & 0o222 == 0

    observed: dict[str, object] = {}

    def fake_run(_argv, **kwargs):
        workspace = Path(kwargs["cwd"])
        packet = json.loads(
            (workspace / "task_packet_observer.json").read_text(encoding="utf-8")
        )
        staged = workspace / packet["observer_inputs"][0]["staged_path"]
        observed["packet_hash"] = packet["observer_inputs"][0]["sha256"]
        observed["staged_hash"] = hashlib.sha256(staged.read_bytes()).hexdigest()
        observed["staged_bytes"] = staged.read_bytes()
        observed["staged_mode"] = staged.stat().st_mode
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "status: complete\n", "stderr": ""},
        )()

    role_profile = {
        "executor_type": "cli_agent",
        "cli_agent": "agy",
        "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
    }
    with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), patch(
        "cli_executor.subprocess.run", side_effect=fake_run
    ):
        result = run_cli_agent(
            plan,
            "Observer",
            role_profile,
            sealed_messages=[{"role": "user", "content": "inspect assigned input"}],
            outbound_source_paths=context_files,
        )

    assert result.status == "completed"
    assert observed["packet_hash"] == expected_hash
    assert observed["staged_hash"] == expected_hash
    assert observed["staged_bytes"] == attachment.read_bytes()
    assert int(observed["staged_mode"]) & 0o222 == 0


def test_contract_hash_drift_blocks_before_observer_context_is_built(
    tmp_path: Path,
) -> None:
    plan = _observation_plan(tmp_path)
    attachment = tmp_path / "evidence.pdf"
    attachment.write_bytes(b"original")
    contract_path = materialize_observation_contract(plan, [attachment])
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    sealed_attachment = Path(plan.run_dir) / contract["assigned_inputs"][0]["path"]
    sealed_attachment.chmod(0o600)
    sealed_attachment.write_bytes(b"tampered")
    sealed_attachment.chmod(0o400)

    with pytest.raises(ObservationContractError, match="integrity mismatch"):
        observer_context_source_files(
            tmp_path,
            plan,
            Path(plan.run_dir) / "observation_report.yml",
        )


def test_contract_boundary_drift_blocks_before_observer_context_is_built(
    tmp_path: Path,
) -> None:
    plan = _observation_plan(tmp_path)
    attachment = tmp_path / "evidence.pdf"
    attachment.write_bytes(b"original")
    contract_path = materialize_observation_contract(plan, [attachment])
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["production_modified"] = True
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ObservationContractError, match="read-only boundary"):
        observer_context_source_files(
            tmp_path,
            plan,
            Path(plan.run_dir) / "observation_report.yml",
        )
