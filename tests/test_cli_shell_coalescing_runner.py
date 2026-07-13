from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.cli_shell_coalescing import write_cli_shell_coalescing_plan
from agent_runtime.cli_shell_coalescing_request import write_cli_shell_coalescing_runner_request
from agent_runtime.cli_shell_coalescing_runner import (
    _execute_command,
    provision_hermes_profiles,
    run_cli_shell_coalescing_request,
)
from agent_runtime.cli_shell_coalescing_status import (
    build_cli_shell_coalescing_status,
    write_cli_shell_coalescing_status,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_cli_shell_command_executor_uses_isolated_working_directory(tmp_path: Path) -> None:
    result = _execute_command(["/bin/pwd"], timeout=5, cwd=tmp_path)

    assert result["exit_code"] == 0
    assert Path(result["stdout"].strip()).resolve() == tmp_path.resolve()


def _request_fixture(tmp_path: Path) -> tuple[Path, Path]:
    plan_path = tmp_path / "cli_shell_coalescing_plan.yml"
    status_path = tmp_path / "cli_shell_coalescing_status.yml"
    request_path = tmp_path / "cli_shell_coalescing_runner_request.yml"
    write_cli_shell_coalescing_plan(ROOT, plan_path, mode="full_cli", tier="performance")
    write_cli_shell_coalescing_status(ROOT, status_path, plan_path=plan_path)
    write_cli_shell_coalescing_runner_request(
        ROOT,
        request_path,
        plan_path=plan_path,
        status_path=status_path,
    )
    return plan_path, request_path


def test_cli_shell_coalescing_runner_defaults_to_nonexecuting_plan(tmp_path: Path) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    report = run_cli_shell_coalescing_request(ROOT, request_path=request_path)

    assert report["status"] == "ready_for_trusted_runner"
    assert report["execute_requested"] is False
    assert report["provider_calls_executed"] is False
    assert report["secret_values_rendered"] is False
    assert report["acceptance_scope"] == "synthetic_native_surface_smoke"
    assert report["private_project_context_loaded"] is False
    assert report["isolated_execution_workspace_required"] is True
    assert report["project_read_tools_allowed"] is False
    assert {item["backend"] for item in report["backend_results"]} == {"claude_code", "hermes"}
    assert all(item["status"] == "planned" for item in report["backend_results"])
    assert all(item["command_preview"] for item in report["backend_results"])


def test_cli_shell_coalescing_runner_requires_trusted_env_before_execute(tmp_path: Path) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    called = False

    def executor(_argv: list[str], _timeout: int) -> dict:
        nonlocal called
        called = True
        return {"exit_code": 0, "stdout": "{}", "stderr": ""}

    report = run_cli_shell_coalescing_request(
        ROOT,
        request_path=request_path,
        execute=True,
        env={},
        executor=executor,
    )

    assert report["status"] == "trusted_runner_env_required"
    assert report["provider_calls_executed"] is False
    assert called is False


def test_cli_shell_coalescing_runner_cli_writes_nonexecuting_report(tmp_path: Path) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    out = tmp_path / "runner_result.yml"

    result = runner.invoke(
        app,
        [
            "cli-shell-coalescing-runner",
            "--request",
            str(request_path),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["status"] == "ready_for_trusted_runner"
    assert report["execute_requested"] is False
    assert report["provider_calls_executed"] is False


def test_cli_shell_coalescing_runner_materializes_role_receipts_from_native_surfaces(
    tmp_path: Path,
) -> None:
    plan_path, request_path = _request_fixture(tmp_path)
    hermes_home = tmp_path / "hermes-home"
    profile_configs = {
        "agentlabsupervisor": {
            "model": {
                "provider": "openai-codex",
                "default": "gpt-5.6-sol",
                "base_url": "https://chatgpt.com/backend-api/codex",
            },
            "agent": {"reasoning_effort": "xhigh"},
            "fallback_providers": [],
        },
        "agentlabpromptengineer": {
            "model": {
                "provider": "deepseek",
                "default": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com",
            },
            "agent": {"reasoning_effort": ""},
            "fallback_providers": [],
        },
    }
    for profile, config in profile_configs.items():
        profile_dir = hermes_home / "profiles" / profile
        profile_dir.mkdir(parents=True)
        (profile_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    hermes_task_roles: dict[str, str] = {}
    commands: list[list[str]] = []

    def executor(argv: list[str], _timeout: int) -> dict:
        commands.append(argv)
        if argv[0] == "claude":
            payload = {
                "structured_output": {
                    "role_results": [
                        {
                            "role": "Coder",
                            "status": "pass",
                            "findings": "Collector execution contract is deterministic.",
                            "validation": ["read scope preserved", "no production writes"],
                        },
                        {
                            "role": "Archivist",
                            "status": "pass",
                            "findings": "Evidence hashes and promotion boundary are present.",
                            "validation": ["evidence paths checked", "promotion blocked"],
                        },
                    ]
                }
            }
            return {"exit_code": 0, "stdout": json.dumps(payload), "stderr": ""}
        if argv[:4] == ["hermes", "kanban", "boards", "list"]:
            return {
                "exit_code": 0,
                "stdout": json.dumps([{"slug": "agentlab-cli-shell-acceptance"}]),
                "stderr": "",
            }
        if "create" in argv:
            title = argv[argv.index("create") + 1]
            role = "Supervisor" if "Supervisor" in title else "PromptEngineer"
            task_id = f"task-{role.lower()}"
            hermes_task_roles[task_id] = role
            return {"exit_code": 0, "stdout": json.dumps({"id": task_id}), "stderr": ""}
        if "dispatch" in argv:
            return {"exit_code": 0, "stdout": json.dumps({"spawned": list(hermes_task_roles)}), "stderr": ""}
        if "show" in argv:
            task_id = argv[-2] if argv[-1] == "--json" else argv[-1]
            role = hermes_task_roles[task_id]
            return {
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "id": task_id,
                        "status": "done",
                        "workspace": "/" + "Users/saintpeter/.hermes/kanban/synthetic-workspace",
                        "result": f"{role} completed the bounded governance review.",
                    }
                ),
                "stderr": "",
            }
        if "runs" in argv:
            task_id = argv[-2] if argv[-1] == "--json" else argv[-1]
            return {
                "exit_code": 0,
                "stdout": json.dumps([{"task_id": task_id, "status": "done", "outcome": "success"}]),
                "stderr": "",
            }
        raise AssertionError(f"unexpected command: {argv}")

    report = run_cli_shell_coalescing_request(
        ROOT,
        request_path=request_path,
        execute=True,
        env={"AGENTLAB_TRUSTED_CLI_SHELL_RUNNER": "1"},
        executor=executor,
        hermes_home=hermes_home,
    )

    assert report["status"] == "pass"
    assert report["provider_calls_executed"] is True
    claude_command = next(argv for argv in commands if argv[0] == "claude")
    assert "--safe-mode" in claude_command
    assert "--no-session-persistence" in claude_command
    assert claude_command[claude_command.index("--tools") + 1] == "Agent"
    hermes_create_commands = [argv for argv in commands if argv[0] == "hermes" and "create" in argv]
    assert hermes_create_commands
    assert all(argv[argv.index("--workspace") + 1] == "scratch" for argv in hermes_create_commands)
    assert all(str(ROOT) not in " ".join(argv) for argv in hermes_create_commands)
    idempotency_keys = [argv[argv.index("--idempotency-key") + 1] for argv in hermes_create_commands]
    assert len(set(idempotency_keys)) == len(idempotency_keys)
    assert all(key.startswith("agentlab-") for key in idempotency_keys)
    assert {item["native_surface_used"] for item in report["backend_results"]} == {
        "claude_inline_agents",
        "hermes_kanban",
    }
    status = build_cli_shell_coalescing_status(ROOT, plan_path=plan_path)
    assert status["status"] == "pass"
    assert status["accepted_packet_count"] == 2
    assert status["accepted_role_count"] == 4
    assert status["missing_returned_files"] == []
    assert status["failures"] == []

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    for packet_text in plan["materialized_session_packets"]:
        packet_path = Path(packet_text)
        if not packet_path.is_absolute():
            packet_path = ROOT / packet_path
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        for role in packet["delegated_roles"]:
            receipt = yaml.safe_load((packet_path.parent / role["receipt_path"]).read_text(encoding="utf-8"))
            assert receipt["role"] == role["role"]
            assert receipt["production_promotion_attempted"] is False
            assert receipt["acceptance_scope"] == "synthetic_native_surface_smoke"
            assert receipt["private_project_context_loaded"] is False
            assert len(receipt["source_packet_sha256"]) == 64
            assert receipt["returned_artifacts"]
            artifact_path = ROOT / receipt["returned_artifacts"][0]
            assert "/" + "Users/" not in artifact_path.read_text(encoding="utf-8")

    for packet_text in plan["materialized_session_packets"]:
        packet_path = Path(packet_text)
        if not packet_path.is_absolute():
            packet_path = ROOT / packet_path
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
        receipt_name = (
            "shell_board_sync_receipt.yml"
            if packet["coalescing_mode"] == "board_mediated"
            else "shell_subagent_delegation_receipt.yml"
        )
        shell_receipt = yaml.safe_load((packet_path.parent / receipt_name).read_text(encoding="utf-8"))
        assert shell_receipt["provider_calls_executed_by_shell_session"] is True
        assert len(shell_receipt["source_packet_sha256"]) == 64


def test_cli_shell_coalescing_runner_refuses_wrong_hermes_profiles_before_dispatch(
    tmp_path: Path,
) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    called = False

    def executor(_argv: list[str], _timeout: int) -> dict:
        nonlocal called
        called = True
        return {"exit_code": 0, "stdout": "{}", "stderr": ""}

    report = run_cli_shell_coalescing_request(
        ROOT,
        request_path=request_path,
        backend="hermes",
        execute=True,
        env={"AGENTLAB_TRUSTED_CLI_SHELL_RUNNER": "1"},
        executor=executor,
        hermes_home=tmp_path / "missing-hermes-home",
    )

    assert report["status"] == "fail"
    assert report["provider_calls_executed"] is False
    assert report["backend_results"][0]["status"] == "profile_preflight_failed"
    assert set(report["backend_results"][0]["profile_issues"]) == {
        "agentlabpromptengineer:profile_missing",
        "agentlabsupervisor:profile_missing",
    }
    assert called is False


def test_cli_shell_coalescing_runner_provisions_isolated_hermes_role_profiles(
    tmp_path: Path,
) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    packet = next(item for item in request["packets"] if item["backend"] == "hermes")
    hermes_home = tmp_path / "hermes-home"
    commands: list[list[str]] = []

    def executor(argv: list[str], _timeout: int) -> dict:
        commands.append(argv)
        if argv[:3] == ["hermes", "profile", "create"]:
            profile = argv[3]
            profile_dir = hermes_home / "profiles" / profile
            profile_dir.mkdir(parents=True)
            (profile_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
            return {"exit_code": 0, "stdout": "created", "stderr": ""}
        if argv[:2] == ["hermes", "-p"] and argv[3:5] == ["config", "set"]:
            profile = argv[2]
            key = argv[5]
            value = argv[6]
            config_path = hermes_home / "profiles" / profile / "config.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            target = config
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            return {"exit_code": 0, "stdout": "updated", "stderr": ""}
        raise AssertionError(f"unexpected command: {argv}")

    report = provision_hermes_profiles(
        packet,
        hermes_home=hermes_home,
        executor=executor,
        timeout=60,
    )

    assert report["status"] == "pass"
    assert set(report["profiles"]) == {"agentlabsupervisor", "agentlabpromptengineer"}
    assert any(argv[:3] == ["hermes", "profile", "create"] for argv in commands)
    assert any("model.provider" in argv for argv in commands)
    assert any("model.base_url" in argv for argv in commands)
    supervisor = yaml.safe_load(
        (hermes_home / "profiles" / "agentlabsupervisor" / "config.yaml").read_text(encoding="utf-8")
    )
    assert supervisor["model"] == {
        "provider": "openai-codex",
        "default": "gpt-5.6-sol",
        "base_url": "https://chatgpt.com/backend-api/codex",
    }
    assert supervisor["agent"]["reasoning_effort"] == "xhigh"
    assert supervisor["fallback_providers"] == []
    assert "fallback_model" not in supervisor


def test_cli_shell_coalescing_runner_provision_only_never_dispatches_provider(
    tmp_path: Path,
) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    hermes_home = tmp_path / "hermes-home"
    commands: list[list[str]] = []

    def executor(argv: list[str], _timeout: int) -> dict:
        commands.append(argv)
        if argv[:3] == ["hermes", "profile", "create"]:
            profile_dir = hermes_home / "profiles" / argv[3]
            profile_dir.mkdir(parents=True)
            (profile_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
            return {"exit_code": 0, "stdout": "created", "stderr": ""}
        if argv[:2] == ["hermes", "-p"] and argv[3:5] == ["config", "set"]:
            profile = argv[2]
            key = argv[5]
            value = argv[6]
            config_path = hermes_home / "profiles" / profile / "config.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            target = config
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            return {"exit_code": 0, "stdout": "updated", "stderr": ""}
        raise AssertionError(f"provider dispatch attempted: {argv}")

    report = run_cli_shell_coalescing_request(
        ROOT,
        request_path=request_path,
        backend="hermes",
        execute=True,
        env={"AGENTLAB_TRUSTED_CLI_SHELL_RUNNER": "1"},
        executor=executor,
        hermes_home=hermes_home,
        provision_profiles=True,
        provision_only=True,
    )

    assert report["status"] == "pass"
    assert report["provision_only_requested"] is True
    assert report["provider_calls_executed"] is False
    assert report["backend_results"][0]["status"] == "profiles_provisioned"
    assert commands
    assert all("kanban" not in argv for argv in commands)


def test_cli_shell_coalescing_runner_accepts_profile_materialized_after_nonzero_create(
    tmp_path: Path,
) -> None:
    _plan_path, request_path = _request_fixture(tmp_path)
    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    packet = next(item for item in request["packets"] if item["backend"] == "hermes")
    hermes_home = tmp_path / "hermes-home"

    def executor(argv: list[str], _timeout: int) -> dict:
        if argv[:3] == ["hermes", "profile", "create"]:
            profile_dir = hermes_home / "profiles" / argv[3]
            profile_dir.mkdir(parents=True)
            (profile_dir / "config.yaml").write_text("{}\n", encoding="utf-8")
            return {"exit_code": 1, "stdout": "", "stderr": "post-create cleanup failed"}
        if argv[:2] == ["hermes", "-p"] and argv[3:5] == ["config", "set"]:
            profile = argv[2]
            key = argv[5]
            value = argv[6]
            config_path = hermes_home / "profiles" / profile / "config.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            target = config
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            return {"exit_code": 0, "stdout": "updated", "stderr": ""}
        raise AssertionError(f"unexpected command: {argv}")

    report = provision_hermes_profiles(
        packet,
        hermes_home=hermes_home,
        executor=executor,
        timeout=60,
    )

    assert report["status"] == "pass"
    assert all(item["created"] is True for item in report["profiles"].values())
