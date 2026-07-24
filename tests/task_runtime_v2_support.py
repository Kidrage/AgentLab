from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from agent_runtime.task_runtime_v2 import RoleAttemptExecutor, TaskRuntime


_ROLES = {
    "Supervisor": {
        "profile_key": "supervisor",
        "worker": "codex",
        "invocation_contract": "codex_supervisor",
        "model_key": "supervisor-model",
        "provider": "codex-cli",
        "model_id": "gpt-test-supervisor",
    },
    "Writer": {
        "profile_key": "writer",
        "worker": "claude_code",
        "invocation_contract": "claude_writer",
        "model_key": "writer-model",
        "provider": "deepseek",
        "model_id": "deepseek-test-writer",
    },
}


def execute_role_with_output(
    runtime: TaskRuntime,
    tmp_path: Path,
    *,
    task_id: str,
    work_item_id: str,
    attempt_id: str,
    role: str,
    output: dict,
) -> dict:
    role_config = _ROLES[role]
    _write_role_config(tmp_path)

    def fake_cli(plan, called_role, profile, **kwargs):
        assert called_role == role
        model_receipt = Path(plan.run_dir) / "model_execution_receipt.yml"
        model_receipt.write_text(
            yaml.safe_dump(
                {
                    "status": "pass",
                    "role": role,
                    "worker": role_config["worker"],
                    "invocation_contract": role_config["invocation_contract"],
                    "selected_provider": role_config["provider"],
                    "selected_model_key": role_config["model_key"],
                    "selected_model_id": role_config["model_id"],
                    "profile_binding_verified": True,
                    "command_binding_verified": True,
                    "provider_model_binding_verified": True,
                    "fallback_detected": False,
                    "provider_process_started": True,
                    "exit_code": 0,
                    "issues": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            status="completed",
            provider="agentlab-cli-executor",
            model=role_config["worker"],
            content=yaml.safe_dump(output, sort_keys=False, allow_unicode=True),
            error=None,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            raw_usage={
                "cli_agent": role_config["worker"],
                "cli_model_key": role_config["model_key"],
                "cli_model_id": role_config["model_id"],
                "cli_catalog_model_id": role_config["model_id"],
                "cli_runtime_provider": role_config["provider"],
                "exit_code": 0,
                "model_resolution_failed": False,
                "provider_model_mismatch": False,
                "qwen_provider_model_mismatch": False,
                "grok_provider_model_mismatch": False,
                "model_execution_receipt": str(model_receipt),
            },
        )

    result = RoleAttemptExecutor(
        tmp_path, project="Demo", cli_runner=fake_cli
    ).execute(
        task_id=task_id,
        work_item_id=work_item_id,
        attempt_id=attempt_id,
        role=role,
        messages=[{"role": "user", "content": "Execute the governed test role."}],
        idempotency_key=attempt_id,
    )
    return result["projection"]["attempts"][attempt_id]["outcome"]


def _write_role_config(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    profiles = {
        role["profile_key"]: {
            "executor_type": "cli_agent",
            "cli_agent": role["worker"],
            "invocation_contract": role["invocation_contract"],
            "default": role["model_key"],
        }
        for role in _ROLES.values()
    }
    (config / "agent_model_profiles.yml").write_text(
        yaml.safe_dump(
            {
                "modes": {
                    "full_cli": {"tiers": {"performance": profiles}}
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
                    role["model_key"]: {
                        "runtime_provider": role["provider"],
                        "model_id": role["model_id"],
                    }
                    for role in _ROLES.values()
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
