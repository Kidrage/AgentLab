"""Offline contract tests for governed Claude runtime preflight.

The tests exercise :func:`run_cli_agent` through its public boundary.  Each
negative case starts from the repository's real invocation contract and model
catalog, changes one command binding, and proves the provider subprocess must
not start.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from agent_runtime.cli_executor import run_cli_agent
from agent_runtime.schemas import AgentRoute, WorkflowPlan


REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_plan(runtime_root: Path) -> WorkflowPlan:
    run_dir = runtime_root / "projects" / "TestProject" / "runs" / "task_test_001"
    return WorkflowPlan(
        project="TestProject",
        task_id="task_test_001",
        agentlab_root=str(runtime_root),
        project_root=str(runtime_root / "projects" / "TestProject"),
        repo_path=str(runtime_root / "projects" / "TestProject"),
        run_dir=str(run_dir),
        user_request_path=str(run_dir / "user_request.md"),
        route=AgentRoute(task_size="small", agents=["Supervisor", "Writer"]),
    )


def _ultracode_plan(
    runtime_root: Path,
    *,
    opt_in: bool = True,
    writer_mode: str = "developmental_ultracode",
    work_type: str = "revision_plan",
) -> WorkflowPlan:
    plan = _make_plan(runtime_root)
    plan.included_agents["Writer"] = {
        "ultracode_opt_in": opt_in,
        "writer_mode": writer_mode,
        "work_type": work_type,
    }
    return plan


ULTRACODE_SEALED_MESSAGES = [
    {"role": "user", "content": "Prepare a bounded revision plan."}
]
PURE_WRITER_SEALED_MESSAGES = [
    {"role": "user", "content": "Write the bounded final chapter candidate."}
]
REVIEWER_SEALED_MESSAGES = [
    {"role": "user", "content": "Audit the bounded chapter candidates."}
]


def _runtime_from_real_config(
    tmp_path: Path,
    contract_name: str,
    *,
    replace: tuple[str, str] | None = None,
    inject_after_binary: str | None = None,
) -> Path:
    """Copy real config and apply one intentional command-contract mutation."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    contracts = yaml.safe_load(
        (REPO_ROOT / "config" / "worker_invocation_contracts.yml").read_text(
            encoding="utf-8"
        )
    )
    template = contracts["contracts"][contract_name]["template"]
    if replace is not None:
        old, new = replace
        assert old in template, f"real {contract_name} template lost expected token {old!r}"
        template = template.replace(old, new, 1)
    if inject_after_binary is not None:
        assert template.startswith("claude ")
        template = template.replace("claude ", f"claude {inject_after_binary} ", 1)
    contracts["contracts"][contract_name]["template"] = template
    (config_dir / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(contracts, sort_keys=False),
        encoding="utf-8",
    )
    (config_dir / "model_catalog.yml").write_text(
        (REPO_ROOT / "config" / "model_catalog.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp_path


def _role_profile(contract_name: str) -> dict[str, str]:
    return {
        "executor_type": "cli_agent",
        "cli_agent": "claude_code",
        "invocation_contract": contract_name,
        "default": "deepseek_v4_pro",
        "capacity_selected_route": (
            "SupervisorDeepSeek"
            if contract_name == "claude_supervisor_fallback"
            else "Writer"
        ),
        "capacity_pool": "deepseek_metered_api",
    }


def test_narrative_reviewer_contract_requires_exact_sealed_runtime_binding(
    tmp_path: Path,
) -> None:
    runtime_root = _runtime_from_real_config(tmp_path, "claude_narrative_audit")
    plan = _make_plan(runtime_root)
    plan.route.route_key = "narrative_heavy_audit"
    profile = _role_profile("claude_narrative_audit")

    with patch.dict(
        "agent_runtime.cli_executor.os.environ",
        {"AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED": "1"},
        clear=False,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run"
    ) as provider_process:
        blocked = run_cli_agent(
            plan,
            "Reviewer",
            profile,
            sealed_messages=REVIEWER_SEALED_MESSAGES,
        )

    provider_process.assert_not_called()
    assert blocked.status == "blocked_user_decision"
    manifest = yaml.safe_load(
        (
            Path(plan.run_dir) / "outbound_context_manifest_reviewer.yml"
        ).read_text(encoding="utf-8")
    )

    with patch.dict(
        "agent_runtime.cli_executor.os.environ",
        {
            "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED": "1",
            "AGENTLAB_ROLE_SESSION_ACCEPTANCE_PAYLOAD_SHA256": manifest[
                "payload"
            ]["sha256"],
        },
        clear=False,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as run:
        result = run_cli_agent(
            plan,
            "Reviewer",
            profile,
            sealed_messages=REVIEWER_SEALED_MESSAGES,
        )

    assert result.status == "completed"
    preflight = result.raw_usage["claude_model_preflight"]
    assert preflight["status"] == "pass"
    assert preflight["command_binding_verified"] is True
    argv = run.call_args.args[0]
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "$schema" not in schema
    assert schema["required"] == [
        "fiction_review",
        "continuity_failure_report",
        "narrative_quality_scorecard",
    ]


def _provider_result() -> SimpleNamespace:
    payload = {
        "type": "result",
        "result": "bounded offline result",
        "session_id": "offline-test-session",
        "usage": {"input_tokens": 3, "output_tokens": 2},
        "modelUsage": {"deepseek-v4-pro": {"outputTokens": 2}},
    }
    return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def _assert_blocked_before_provider(
    result,
    process,
    *,
    expect_command_binding_failure: bool = True,
) -> None:
    # Avoid Mock.assert_not_called(): on failure it renders every subprocess
    # kwarg, including the deliberately unmodified child environment.
    assert process.call_count == 0, "provider subprocess started before preflight passed"
    assert result.status == "blocked_user_decision"
    assert result.error == "claude_model_preflight_failed"
    assert result.raw_usage["provider_process_started"] is False
    assert result.raw_usage["claude_model_preflight"]["status"] == "fail"
    receipt_path = Path(result.raw_usage["model_execution_receipt"])
    receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "fail"
    assert receipt["provider_process_started"] is False
    assert receipt["command_binding_verified"] is (
        not expect_command_binding_failure
    )
    assert "claude_model_preflight_failed" in receipt["issues"]


WRITER_AND_FALLBACK_MUTATIONS = [
    pytest.param(("--effort max ", ""), id="effort-missing"),
    pytest.param(("--effort max", "--effort high"), id="effort-weakened"),
    pytest.param(("--max-budget-usd 1.00 ", ""), id="budget-missing"),
    pytest.param(
        ("--max-budget-usd 1.00", "--max-budget-usd 0.50"),
        id="budget-weakened",
    ),
    pytest.param(("--permission-mode plan ", ""), id="permission-missing"),
    pytest.param(
        ("--permission-mode plan", "--permission-mode acceptEdits"),
        id="permission-weakened",
    ),
    pytest.param(("--output-format json ", ""), id="json-output-missing"),
    pytest.param(
        ("--output-format json", "--output-format text"),
        id="json-output-weakened",
    ),
    pytest.param(('--tools "" ', ""), id="empty-tools-missing"),
    pytest.param(('--tools ""', '--tools "Web"'), id="empty-tools-weakened"),
    pytest.param(('--model "{model_id}" ', ""), id="model-missing"),
    pytest.param(
        ('--model "{model_id}"', '--model "unapproved-model"'),
        id="model-weakened",
    ),
]


@pytest.mark.parametrize(
    "contract_name,agent_name",
    [
        pytest.param("claude_writer", "Writer", id="writer"),
        pytest.param(
            "claude_supervisor_fallback",
            "Supervisor",
            id="supervisor-fallback",
        ),
    ],
)
@pytest.mark.parametrize("mutation", WRITER_AND_FALLBACK_MUTATIONS)
def test_writer_and_supervisor_fallback_reject_missing_or_weakened_runtime_binding(
    tmp_path: Path,
    contract_name: str,
    agent_name: str,
    mutation: tuple[str, str],
) -> None:
    if contract_name == "claude_writer" and mutation[0].startswith(
        "--permission-mode"
    ):
        mutation = (mutation[0].replace("plan", "bypassPermissions"), mutation[1])
    runtime_root = _runtime_from_real_config(
        tmp_path,
        contract_name,
        replace=mutation,
    )

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        result = run_cli_agent(
            _make_plan(runtime_root),
            agent_name,
            _role_profile(contract_name),
            **(
                {"sealed_messages": PURE_WRITER_SEALED_MESSAGES}
                if contract_name == "claude_writer"
                else {}
            ),
        )

    _assert_blocked_before_provider(result, process)


ULTRACODE_REQUIRED_BINDING_MUTATIONS = [
    pytest.param(("--max-budget-usd 2.00 ", ""), id="budget-missing"),
    pytest.param(
        ("--max-budget-usd 2.00", "--max-budget-usd 1.00"),
        id="budget-weakened",
    ),
    pytest.param(("--permission-mode plan ", ""), id="permission-missing"),
    pytest.param(
        ("--permission-mode plan", "--permission-mode acceptEdits"),
        id="permission-weakened",
    ),
    pytest.param(("--output-format json ", ""), id="json-output-missing"),
    pytest.param(
        ("--output-format json", "--output-format text"),
        id="json-output-weakened",
    ),
    pytest.param(('--model "{model_id}" ', ""), id="model-missing"),
    pytest.param(
        ('--model "{model_id}"', '--model "unapproved-model"'),
        id="model-weakened",
    ),
]


@pytest.mark.parametrize("mutation", ULTRACODE_REQUIRED_BINDING_MUTATIONS)
def test_ultracode_rejects_missing_or_weakened_runtime_binding(
    tmp_path: Path,
    mutation: tuple[str, str],
) -> None:
    runtime_root = _runtime_from_real_config(
        tmp_path,
        "claude_writer_ultracode",
        replace=mutation,
    )

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        result = run_cli_agent(
            _ultracode_plan(runtime_root),
            "Writer",
            _role_profile("claude_writer_ultracode"),
            sealed_messages=ULTRACODE_SEALED_MESSAGES,
        )

    _assert_blocked_before_provider(result, process)


@pytest.mark.parametrize(
    "forbidden_flag",
    [
        pytest.param("--dangerously-skip-permissions", id="skip-permissions"),
        pytest.param("--fallback-model unapproved-model", id="fallback-model"),
        pytest.param("--remote https://unapproved.invalid", id="remote"),
        pytest.param("--chrome", id="chrome"),
        pytest.param("--browser chrome", id="browser"),
    ],
)
def test_ultracode_rejects_dangerous_fallback_remote_and_browser_flags(
    tmp_path: Path,
    forbidden_flag: str,
) -> None:
    runtime_root = _runtime_from_real_config(
        tmp_path,
        "claude_writer_ultracode",
        inject_after_binary=forbidden_flag,
    )

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        result = run_cli_agent(
            _ultracode_plan(runtime_root),
            "Writer",
            _role_profile("claude_writer_ultracode"),
            sealed_messages=ULTRACODE_SEALED_MESSAGES,
        )

    _assert_blocked_before_provider(result, process)


@pytest.mark.parametrize(
    "writer_plan,expected_issue",
    [
        pytest.param({}, "claude_ultracode_explicit_opt_in_missing", id="no-opt-in"),
        pytest.param(
            {
                "ultracode_opt_in": False,
                "writer_mode": "developmental_ultracode",
                "work_type": "revision_plan",
            },
            "claude_ultracode_explicit_opt_in_missing",
            id="opt-in-false",
        ),
        pytest.param(
            {
                "ultracode_opt_in": True,
                "writer_mode": "ordinary_writer",
                "work_type": "revision_plan",
            },
            "claude_ultracode_writer_mode_mismatch",
            id="wrong-mode",
        ),
        pytest.param(
            {
                "ultracode_opt_in": True,
                "writer_mode": "developmental_ultracode",
                "work_type": "final_prose_draft",
            },
            "claude_ultracode_forbidden_work_type",
            id="final-prose",
        ),
        pytest.param(
            {
                "ultracode_opt_in": True,
                "writer_mode": "developmental_ultracode",
                "work_type": "unregistered_work",
            },
            "claude_ultracode_work_type_not_allowed",
            id="unregistered-work",
        ),
    ],
)
def test_ultracode_requires_explicit_developmental_packet_authorization(
    tmp_path: Path,
    writer_plan: dict[str, object],
    expected_issue: str,
) -> None:
    runtime_root = _runtime_from_real_config(tmp_path, "claude_writer_ultracode")
    plan = _make_plan(runtime_root)
    if writer_plan:
        plan.included_agents["Writer"] = writer_plan

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        result = run_cli_agent(
            plan,
            "Writer",
            _role_profile("claude_writer_ultracode"),
            sealed_messages=ULTRACODE_SEALED_MESSAGES,
        )

    _assert_blocked_before_provider(
        result,
        process,
        expect_command_binding_failure=False,
    )
    assert expected_issue in result.raw_usage["claude_model_preflight"]["issues"]
    activation_path = Path(result.raw_usage["ultracode_activation_receipt"])
    activation = yaml.safe_load(activation_path.read_text(encoding="utf-8"))
    assert activation["status"] == "fail"
    assert activation["final_prose_authorized"] is False
    assert expected_issue in activation["issues"]


def test_ultracode_rejects_unsealed_packet_even_with_valid_opt_in(
    tmp_path: Path,
) -> None:
    runtime_root = _runtime_from_real_config(tmp_path, "claude_writer_ultracode")

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        result = run_cli_agent(
            _ultracode_plan(runtime_root),
            "Writer",
            _role_profile("claude_writer_ultracode"),
        )

    _assert_blocked_before_provider(
        result,
        process,
        expect_command_binding_failure=False,
    )
    assert "claude_ultracode_sealed_writer_packet_missing" in result.raw_usage[
        "claude_model_preflight"
    ]["issues"]


@pytest.mark.parametrize(
    "contract_name,agent_name,expected_budget,expected_permission,requires_effort_and_empty_tools",
    [
        pytest.param(
            "claude_writer",
            "Writer",
            "1.00",
            "bypassPermissions",
            True,
            id="writer",
        ),
        pytest.param(
            "claude_supervisor_fallback",
            "Supervisor",
            "1.00",
            "plan",
            True,
            id="supervisor-fallback",
        ),
        pytest.param(
            "claude_writer_ultracode",
            "Writer",
            "2.00",
            "plan",
            False,
            id="ultracode",
        ),
    ],
)
def test_real_claude_contract_executes_only_with_exact_runtime_binding(
    tmp_path: Path,
    contract_name: str,
    agent_name: str,
    expected_budget: str,
    expected_permission: str,
    requires_effort_and_empty_tools: bool,
) -> None:
    runtime_root = _runtime_from_real_config(tmp_path, contract_name)

    with patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/claude"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", return_value=_provider_result()
    ) as process:
        plan = (
            _ultracode_plan(runtime_root)
            if contract_name == "claude_writer_ultracode"
            else _make_plan(runtime_root)
        )
        result = run_cli_agent(
            plan,
            agent_name,
            _role_profile(contract_name),
            **(
                {"sealed_messages": ULTRACODE_SEALED_MESSAGES}
                if contract_name == "claude_writer_ultracode"
                else {"sealed_messages": PURE_WRITER_SEALED_MESSAGES}
                if contract_name == "claude_writer"
                else {}
            ),
        )

    assert result.status == "completed"
    process.assert_called_once()
    argv = process.call_args.args[0]
    assert argv[argv.index("--model") + 1] == "deepseek-v4-pro"
    assert argv[argv.index("--max-budget-usd") + 1] == expected_budget
    assert argv[argv.index("--permission-mode") + 1] == expected_permission
    assert argv[argv.index("--output-format") + 1] == "json"
    if requires_effort_and_empty_tools:
        assert argv[argv.index("--effort") + 1] == "max"
        assert argv[argv.index("--tools") + 1] == ""
    if contract_name == "claude_writer":
        kwargs = process.call_args.kwargs
        assert "stdin" not in kwargs
        packet = json.loads(kwargs["input"])
        assert packet["messages"] == PURE_WRITER_SEALED_MESSAGES
        assert result.raw_usage["sealed_packet_stdin"] is True
    assert "--dangerously-skip-permissions" not in argv
    assert "--fallback-model" not in argv
    assert "--remote" not in argv
    assert "--chrome" not in argv
    assert "--browser" not in argv
    if contract_name == "claude_writer_ultracode":
        activation_path = Path(result.raw_usage["ultracode_activation_receipt"])
        activation = yaml.safe_load(activation_path.read_text(encoding="utf-8"))
        assert activation["status"] == "pass"
        assert activation["explicit_opt_in"] is True
        assert activation["work_type"] == "revision_plan"
        assert activation["final_prose_authorized"] is False
