"""Offline postflight coverage for governed staged visual inputs."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agent_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from cli_executor import run_cli_agent  # noqa: E402
from schemas import AgentRoute, WorkflowPlan  # noqa: E402


def _governed_visual_runtime(
    tmp_path: Path,
    *,
    agent_name: str,
) -> tuple[WorkflowPlan, dict[str, object], Path]:
    task_id = f"task_{agent_name.lower()}_visual_postflight"
    project_root = tmp_path / "projects" / "VisualProject"
    run_dir = project_root / "runs" / task_id
    run_dir.mkdir(parents=True)
    request = run_dir / "user_request.md"
    request.write_text("Inspect the exact assigned visual input.", encoding="utf-8")
    source = run_dir / "assigned.png"
    source.write_bytes(b"bounded-visual-input")

    contract_name = (
        "agy_observer" if agent_name == "Observer" else "agy_visual_reviewer"
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "visual_model": {
                        "provider": "agy_gemini_oauth",
                        "runtime_provider": "agy-gemini-oauth",
                        "model_id": "gemini-3.5-flash-high",
                        "cli_model_id": "Gemini 3.5 Flash (High)",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(
            {
                "contracts": {
                    contract_name: {
                        "worker_id": "agy",
                        "invocation_style": "read_only_multimodal_task_packet",
                        "template": (
                            'agy --sandbox --model "{model_id}" '
                            '-p "Read {task_packet_path}"'
                        ),
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    plan = WorkflowPlan(
        project="VisualProject",
        task_id=task_id,
        agentlab_root=str(tmp_path),
        project_root=str(project_root),
        repo_path=str(project_root),
        run_dir=str(run_dir),
        user_request_path=str(request),
        route=AgentRoute(
            route_key=(
                "observation_task"
                if agent_name == "Observer"
                else "media_generation_task"
            ),
            task_size="small",
            agents=[agent_name],
        ),
    )
    profile: dict[str, object] = {
        "executor_type": "cli_agent",
        "cli_agent": "agy",
        "invocation_contract": contract_name,
        "default": "visual_model",
        "capacity_selected_route": (
            "Observer" if agent_name == "Observer" else "VisualReviewer"
        ),
        "capacity_pool": "agy_gemini_observer",
    }
    return plan, profile, source


def test_observer_provider_mutation_blocks_result_and_fails_receipts(
    tmp_path: Path,
) -> None:
    plan, profile, source = _governed_visual_runtime(
        tmp_path,
        agent_name="Observer",
    )

    def mutating_provider(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        workspace = Path(str(kwargs["cwd"]))
        packet = json.loads(
            (workspace / "task_packet_observer.json").read_text(encoding="utf-8")
        )
        staged = workspace / packet["observer_inputs"][0]["staged_path"]
        assert stat.S_IMODE(staged.stat().st_mode) == 0o400
        staged.chmod(0o600)
        staged.write_bytes(b"provider-mutated-input")
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="status: complete\nobservations: []\n",
            stderr="",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/agy",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=mutating_provider,
    ):
        result = run_cli_agent(
            plan,
            "Observer",
            profile,
            sealed_messages=[{"role": "user", "content": "Inspect the image."}],
            outbound_source_paths=[source],
        )

    assert result.status == "blocked_user_decision"
    assert result.raw_usage["failure_class"] == "validation_failed"
    assert result.raw_usage["staged_input_postflight_issue"] in {
        "staged_input_mode_mutated",
        "staged_input_integrity_mismatch",
    }
    manifest_path = Path(result.raw_usage["staged_input_manifest"])
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "fail"
    assert manifest["phase"] == "postflight"
    assert manifest["provider_process_started"] is True
    receipt = yaml.safe_load(
        Path(result.raw_usage["model_execution_receipt"]).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "fail"
    assert receipt["provider_process_started"] is True
    assert any(
        issue.startswith("staged_input_postflight_failed:")
        for issue in receipt["issues"]
    )


def test_visual_reviewer_timeout_rechecks_and_rejects_symlink_replacement(
    tmp_path: Path,
) -> None:
    plan, profile, source = _governed_visual_runtime(
        tmp_path,
        agent_name="Reviewer",
    )

    def timing_out_provider(argv: list[str], **kwargs: object):
        workspace = Path(str(kwargs["cwd"]))
        packet = json.loads(
            (workspace / "task_packet_reviewer.json").read_text(encoding="utf-8")
        )
        staged = workspace / packet["visual_inputs"][0]["staged_path"]
        staged.parent.chmod(0o700)
        staged.unlink()
        replacement = workspace / "replacement.png"
        replacement.write_bytes(b"provider-owned-replacement")
        try:
            staged.symlink_to(replacement)
        except OSError as exc:  # pragma: no cover - unsupported host filesystem
            pytest.skip(f"symlink unavailable: {exc}")
        staged.parent.chmod(0o500)
        raise subprocess.TimeoutExpired(
            cmd=argv,
            timeout=5,
            output="partial visual review",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/agy",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=timing_out_provider,
    ):
        result = run_cli_agent(
            plan,
            "Reviewer",
            profile,
            timeout=5,
            sealed_messages=[{"role": "user", "content": "Review the image."}],
            outbound_source_paths=[source],
        )

    assert result.status == "blocked_user_decision"
    assert result.raw_usage["staged_input_postflight_issue"] == (
        "staged_input_symlink_not_allowed"
    )
    manifest = yaml.safe_load(
        Path(result.raw_usage["staged_input_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "fail"
    assert manifest["phase"] == "provider_timeout_postflight"
    assert manifest["role"] == "Reviewer"
    assert manifest["provider_process_started"] is True
    receipt = yaml.safe_load(
        Path(result.raw_usage["model_execution_receipt"]).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "fail"
    assert receipt["role"] == "Reviewer"
    assert receipt["timed_out"] is True
    assert (
        "staged_input_postflight_failed:staged_input_symlink_not_allowed"
        in receipt["issues"]
    )


def test_visual_verifier_uses_the_same_staged_input_postflight_boundary(
    tmp_path: Path,
) -> None:
    plan, _profile, source = _governed_visual_runtime(
        tmp_path,
        agent_name="Verifier",
    )
    profile = {
        "executor_type": "cli_agent",
        "cli_agent": "offline_verifier",
        "cli_command": "offline-verifier {task_packet_path}",
    }

    def chmodding_verifier(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        workspace = Path(str(kwargs["cwd"]))
        packet = json.loads(
            (workspace / "task_packet_verifier.json").read_text(encoding="utf-8")
        )
        staged = workspace / packet["visual_inputs"][0]["staged_path"]
        assert staged.parent.name == "verifier_visual_inputs"
        staged.chmod(0o600)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="status: pass\nchecks: []\n",
            stderr="",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/offline-verifier",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=chmodding_verifier,
    ):
        result = run_cli_agent(
            plan,
            "Verifier",
            profile,
            sealed_messages=[{"role": "user", "content": "Verify evidence."}],
            outbound_source_paths=[source],
        )

    assert result.status == "blocked_user_decision"
    assert result.raw_usage["staged_input_postflight_issue"] == (
        "staged_input_mode_mutated"
    )
    manifest = yaml.safe_load(
        Path(result.raw_usage["staged_input_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "fail"
    assert manifest["role"] == "Verifier"
    assert manifest["provider_process_started"] is True


def test_unchanged_visual_reviewer_input_keeps_truthful_pass_receipts(
    tmp_path: Path,
) -> None:
    plan, profile, source = _governed_visual_runtime(
        tmp_path,
        agent_name="Reviewer",
    )

    def read_only_provider(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        workspace = Path(str(kwargs["cwd"]))
        packet = json.loads(
            (workspace / "task_packet_reviewer.json").read_text(encoding="utf-8")
        )
        staged = workspace / packet["visual_inputs"][0]["staged_path"]
        assert staged.read_bytes() == source.read_bytes()
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="status: pass\ncandidates: []\n",
            stderr="",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/agy",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=read_only_provider,
    ):
        result = run_cli_agent(
            plan,
            "Reviewer",
            profile,
            sealed_messages=[{"role": "user", "content": "Review the image."}],
            outbound_source_paths=[source],
        )

    assert result.status == "completed"
    manifest = yaml.safe_load(
        Path(result.raw_usage["staged_input_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "pass"
    assert manifest["phase"] == "postflight"
    assert manifest["provider_process_started"] is True
    receipt = yaml.safe_load(
        Path(result.raw_usage["model_execution_receipt"]).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "pass"
    assert receipt["provider_process_started"] is True
