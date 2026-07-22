from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from agent_runtime.task_runtime_v2 import RoleAttemptExecutor, TaskRuntime


def test_role_executor_dispatches_recorded_route_and_pins_attempt_receipt(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "agent_model_profiles.yml").write_text(
        yaml.safe_dump(
            {
                "modes": {
                    "full_cli": {
                        "tiers": {
                            "performance": {
                                "writer": {
                                    "executor_type": "cli_agent",
                                    "cli_agent": "claude_code",
                                    "invocation_contract": "claude_writer",
                                    "default": "writer-model",
                                }
                            }
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "writer-model": {
                        "runtime_provider": "deepseek",
                        "model_id": "deepseek-v4-pro",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-role",
        title="One worker role",
        user_goal="Dispatch one governed local Writer.",
        input_profile={
            "kind": "creative_patch",
            "scope": "localized",
            "target_count": 1,
            "canon_impact": "candidate",
            "risk_flags": [],
        },
        idempotency_key="create-role",
    )
    runtime.create_work_item(
        "task-role",
        job_id="job-main",
        work_item_id="writer",
        kind="patch",
        title="Writer patch",
        idempotency_key="work-writer",
    )
    calls: list[dict] = []

    def fake_cli(plan, role, profile, **kwargs):
        calls.append(
            {
                "plan": plan,
                "role": role,
                "profile": profile,
                "kwargs": kwargs,
            }
        )
        return SimpleNamespace(
            status="completed",
            provider="deepseek",
            model="deepseek-v4-pro",
            content="候选文本",
            error=None,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            raw_usage={"model_execution_receipt": "receipt.yml"},
        )

    result = RoleAttemptExecutor(
        tmp_path, project="Demo", cli_runner=fake_cli
    ).execute(
        task_id="task-role",
        work_item_id="writer",
        attempt_id="writer-attempt-001",
        role="Writer",
        messages=[{"role": "user", "content": "Write the assigned patch."}],
        idempotency_key="writer-attempt-001",
    )

    attempt = result["projection"]["attempts"]["writer-attempt-001"]
    assert attempt["status"] == "succeeded"
    assert attempt["execution_contract"]["input_tier"] == "L1"
    assert attempt["execution_contract"]["route"] == "single_worker"
    assert calls[0]["role"] == "Writer"
    assert calls[0]["profile"]["invocation_contract"] == "claude_writer"
    assert calls[0]["kwargs"]["sealed_messages"][0]["content"].startswith("Write")
    assert Path(result["output_path"]).read_text(encoding="utf-8") == "候选文本"
    receipt = yaml.safe_load(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "task-runtime-role-attempt-receipt/v1"
    assert receipt["output_sha256"]
