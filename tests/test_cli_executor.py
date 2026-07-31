"""Tests for cli_executor.py — the CLI Agent executor dispatch module.

These tests are fully unit-level and offline: no real subprocesses are spawned
against hermes or claude_code binaries; instead subprocess.run is patched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

_REAL_SUBPROCESS_RUN = subprocess.run

if TYPE_CHECKING:
    from agent_runtime.schemas import WorkflowPlan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(tmp_path: Path, budget_mode: str = "balanced") -> "WorkflowPlan":
    """Build a minimal WorkflowPlan-like object for testing."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from schemas import AgentRoute, WorkflowPlan

    route = AgentRoute(task_size="small", agents=["Supervisor", "Coder"])
    return WorkflowPlan(
        project="TestProject",
        task_id="task_test_001",
        agentlab_root=str(tmp_path),
        project_root=str(tmp_path / "projects" / "TestProject"),
        repo_path=str(tmp_path / "projects" / "TestProject"),
        run_dir=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"),
        user_request_path=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001" / "user_request.md"),
        budget_mode=budget_mode,
        route=route,
    )


def _authorize_external_packet(
    plan: "WorkflowPlan",
    *,
    agent_name: str,
    cli_agent_name: str,
    sealed_messages: list[dict[str, str]] | None = None,
    task_messages: list[dict[str, str]] | None = None,
) -> None:
    """Attach a real detached user signature for one exact outbound packet."""

    from agent_runtime.approval_signature import (
        approval_payload_bytes,
        narrative_outbound_approval_payload,
    )
    from agent_runtime.cli_executor import _task_packet_payload

    root = Path(plan.agentlab_root)
    authority_root = root.parent / f".{root.name}-external-approval"
    authority_root.mkdir(parents=True, exist_ok=True)
    private_key = authority_root / "private.pem"
    public_key = authority_root / "public.pem"
    if not private_key.is_file():
        subprocess.run(
            [
                "/usr/bin/openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
        )

    config_path = root / "config" / "local_private_topology.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if config_path.is_file()
        else {}
    )
    config["external_context_approval_authority"] = {
        "public_key_path": str(public_key),
        "public_key_sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
    }
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    packet_text = json.dumps(
        _task_packet_payload(
            agent_name,
            plan,
            sealed_messages,
            task_messages,
        ),
        indent=2,
        ensure_ascii=False,
    )
    packet_sha256 = hashlib.sha256(packet_text.encode("utf-8")).hexdigest()
    scope_sha256 = hashlib.sha256(
        f"{plan.task_id}:{agent_name}:{cli_agent_name}".encode("utf-8")
    ).hexdigest()
    expires_at = "2999-01-01T00:00:00Z"
    recipient = f"cli_agent:{cli_agent_name}"
    purpose = "bounded role session test"
    payload = narrative_outbound_approval_payload(
        project=str(plan.project),
        task_id=str(plan.task_id),
        recipient=recipient,
        purpose=purpose,
        packet_payload_sha256=packet_sha256,
        scope_sha256=scope_sha256,
        expires_at=expires_at,
    )
    payload_path = authority_root / f"{plan.task_id}-{agent_name}.json"
    payload_path.write_bytes(approval_payload_bytes(payload))
    signature_path = authority_root / f"{plan.task_id}-{agent_name}.sig"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature_path),
            str(payload_path),
        ],
        check=True,
        capture_output=True,
    )
    plan.execution_policy = {
        "external_context_approval_required": True,
        "external_context_payload_sha256_required": True,
        "external_context_scope_sha256_required": True,
        "external_context_scope_contract_valid": True,
        "external_context_scope_sha256": scope_sha256,
        "external_context_approval_signature_path": str(signature_path),
        "external_context_transfer": {
            "recipient": recipient,
            "purpose": purpose,
            "expires_at": expires_at,
        },
    }


def _hermes_supervisor_fixture(
    tmp_path: Path,
    *,
    reasoning_effort: str = "xhigh",
    fallback_providers: list[dict] | None = None,
) -> tuple[dict, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "supervisor_model": {
                        "provider": "hermes_codex_oauth",
                        "runtime_provider": "openai-codex",
                        "cli_provider": "openai-codex",
                        "model_id": "gpt-5.6-sol",
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
                    "hermes_supervisor": {
                        "worker_id": "hermes",
                        "workflow_shell_profile": "agentlabsupervisor",
                        "template": (
                            "hermes -p agentlabsupervisor chat -Q --provider {provider} "
                            "-m {model_id} --ignore-rules --max-turns 6 "
                            "-q \"Read {task_packet_path}\""
                        ),
                        "required_shell_state": {
                            "model.provider": "openai-codex",
                            "model.default": "gpt-5.6-sol",
                            "agent.reasoning_effort": "xhigh",
                            "fallback_providers": [],
                            "fallback_model": None,
                        },
                        "requested_reasoning_label": "extra",
                        "resolved_reasoning_effort": "xhigh",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    hermes_home = tmp_path / "hermes-home"
    profile_dir = hermes_home / "profiles" / "agentlabsupervisor"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {
                    "provider": "openai-codex",
                    "default": "gpt-5.6-sol",
                },
                "agent": {"reasoning_effort": reasoning_effort},
                "fallback_providers": (
                    [] if fallback_providers is None else fallback_providers
                ),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    role_profile = {
        "executor_type": "cli_agent",
        "cli_agent": "hermes",
        "invocation_contract": "hermes_supervisor",
        "default": "supervisor_model",
    }
    return role_profile, hermes_home


def test_qwen_role_contract_maps_dashscope_auth_without_cli_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _contract_process_environment

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(
            {
                "contracts": {
                    "qwen": {
                        "environment": {
                            "api_key_source": "DASHSCOPE_API_KEY",
                            "api_key_target": "OPENAI_API_KEY",
                            "base_url_target": "OPENAI_BASE_URL",
                            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "stale-openai-secret")

    process_env, _ = _contract_process_environment(
        {"cli_agent": "qwen", "invocation_contract": "qwen"},
        tmp_path,
    )

    assert process_env["OPENAI_API_KEY"] == "dashscope-test-secret"
    assert process_env["OPENAI_BASE_URL"] == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


@pytest.mark.parametrize(
    "trailing_override",
    [
        pytest.param(
            " --provider deepseek -m deepseek-v4-pro",
            id="provider-and-model",
        ),
        pytest.param(" -m gpt-5.5", id="duplicate-model"),
        pytest.param(
            " --fallback-model deepseek-v4-pro",
            id="fallback-model",
        ),
    ],
)
def test_hermes_supervisor_rejects_trailing_command_overrides_before_provider(
    tmp_path: Path,
    trailing_override: str,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import run_cli_agent

    plan = _make_plan(tmp_path)
    Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
    role_profile, hermes_home = _hermes_supervisor_fixture(tmp_path)
    contract_path = tmp_path / "config" / "worker_invocation_contracts.yml"
    contracts = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contracts["contracts"]["hermes_supervisor"]["template"] += trailing_override
    contract_path.write_text(
        yaml.safe_dump(contracts, sort_keys=False),
        encoding="utf-8",
    )

    with patch.dict(
        "os.environ",
        {"HERMES_HOME": str(hermes_home)},
        clear=False,
    ), patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/hermes",
    ), patch("cli_executor.subprocess.run") as provider_process:
        result = run_cli_agent(plan, "Supervisor", role_profile)

    provider_process.assert_not_called()
    assert result.status == "blocked_user_decision"
    assert result.error == "supervisor_model_preflight_failed"
    preflight = result.raw_usage["supervisor_model_preflight"]
    assert preflight["command_binding_verified"] is False
    assert "supervisor_command_binding_mismatch" in preflight["issues"]


def test_hermes_alter_profile_preflight_binds_grok_high_state(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _hermes_supervisor_preflight

    hermes_home = tmp_path / "hermes-home"
    profile_dir = hermes_home / "profiles" / "agentlabalter"
    profile_dir.mkdir(parents=True)
    config_path = profile_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "xai-oauth", "default": "grok-4.5"},
                "agent": {"reasoning_effort": "high"},
                "fallback_providers": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    role_profile = {
        "cli_agent": "hermes",
        "invocation_contract": "hermes_alter_high",
        "default": "grok_4_5_hermes_oauth",
        "capacity_route": "AlterCoder",
    }
    argv = [
        "hermes",
        "-p",
        "agentlabalter",
        "chat",
        "-Q",
        "--provider",
        "xai-oauth",
        "-m",
        "grok-4.5",
        "--ignore-rules",
        "--max-turns",
        "90",
        "-q",
        "Read the task packet.",
    ]
    model_values = {
        "provider": "xai-oauth",
        "model_id": "grok-4.5",
        "model_key": "grok_4_5_hermes_oauth",
    }

    preflight = _hermes_supervisor_preflight(
        role_profile,
        Path(__file__).resolve().parents[1],
        {"HERMES_HOME": str(hermes_home)},
        argv,
        model_values,
        agent_name="Coder",
    )
    assert preflight["status"] == "pass"
    assert preflight["role"] == "Coder"
    assert preflight["observed_shell_state"]["agent.reasoning_effort"] == "high"
    assert preflight["command_binding_verified"] is True

    config_path.write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "xai-oauth", "default": "grok-4.5"},
                "agent": {"reasoning_effort": "medium"},
                "fallback_providers": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    drifted = _hermes_supervisor_preflight(
        role_profile,
        Path(__file__).resolve().parents[1],
        {"HERMES_HOME": str(hermes_home)},
        argv,
        model_values,
        agent_name="Coder",
    )
    assert drifted["status"] == "fail"
    assert "profile_state_mismatch:agent.reasoning_effort" in drifted["issues"]

    config_path.write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "xai-oauth", "default": "grok-4.5"},
                "agent": {"reasoning_effort": "high"},
                "fallback_providers": [
                    {"provider": "openrouter", "model": "other-model"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    fallback_drifted = _hermes_supervisor_preflight(
        role_profile,
        Path(__file__).resolve().parents[1],
        {"HERMES_HOME": str(hermes_home)},
        argv,
        model_values,
        agent_name="Coder",
    )
    assert fallback_drifted["status"] == "fail"
    assert "profile_state_mismatch:fallback_providers" in fallback_drifted["issues"]


def test_codex_supervisor_preflight_derives_model_binding_from_config(
    tmp_path: Path,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _hermes_supervisor_preflight

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "worker_invocation_contracts.yml").write_text(
        yaml.safe_dump(
            {
                "contracts": {
                    "codex_supervisor": {
                        "worker_id": "codex",
                        "required_runtime_provider": "codex-cli",
                        "required_model_key": "codex_next_supervisor",
                        "resolved_reasoning_effort": "high",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "codex_next_supervisor": {
                        "provider": "codex_cli_oauth",
                        "runtime_provider": "codex-cli",
                        "model_id": "gpt-next",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    role_profile = {
        "invocation_contract": "codex_supervisor",
        "default": "codex_next_supervisor",
    }
    argv = [
        "codex",
        "exec",
        "--json",
        "--model",
        "gpt-next",
        "-c",
        'model_reasoning_effort="high"',
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        "/sealed/workspace",
        "Read /sealed/workspace/task_packet.json",
    ]

    result = _hermes_supervisor_preflight(
        role_profile,
        tmp_path,
        {},
        argv,
        {
            "provider": "codex-cli",
            "model_id": "gpt-next",
            "model_key": "codex_next_supervisor",
        },
    )

    assert result["status"] == "pass"
    assert result["required_shell_state"] == {
        "model.provider": "codex-cli",
        "model.default": "gpt-next",
        "agent.reasoning_effort": "high",
    }


def _agy_observer_fixture(tmp_path: Path) -> dict:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "observer_model": {
                        "provider": "agy_gemini_oauth",
                        "runtime_provider": "agy-gemini-oauth",
                        "model_id": "gemini-3.5-flash-high",
                        "cli_model_id": "gemini-3.5-flash-high",
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
                    "agy_observer": {
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
    return {
        "executor_type": "cli_agent",
        "cli_agent": "agy",
        "invocation_contract": "agy_observer",
        "default": "observer_model",
        "capacity_selected_route": "ObserverGemini",
        "capacity_pool": "agy_gemini_observer",
    }


def test_contract_env_injects_default_proxy_for_agy_governed_contract_when_missing(
    tmp_path: Path,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _contract_process_environment

    role_profile = _agy_observer_fixture(tmp_path)
    with patch.dict(
        "cli_executor.os.environ",
        {
            "AGENTLAB_DEFAULT_PROXY": "http://127.0.0.1:7890",
            "AGY_OAUTH_SESSION": "s",
        },
        clear=True,
    ):
        process_env, _ = _contract_process_environment(
            role_profile,
            tmp_path,
        )

    assert process_env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert process_env["https_proxy"] == "http://127.0.0.1:7890"
    assert process_env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert process_env["http_proxy"] == "http://127.0.0.1:7890"


def test_contract_env_preserves_explicit_proxy_for_agy_governed_contract(
    tmp_path: Path,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _contract_process_environment

    role_profile = _agy_observer_fixture(tmp_path)
    with patch.dict(
        "cli_executor.os.environ",
        {"HTTPS_PROXY": "http://localhost:49468", "AGY_OAUTH_SESSION": "s"},
        clear=True,
    ):
        process_env, _ = _contract_process_environment(
            role_profile,
            tmp_path,
        )

    assert process_env["HTTPS_PROXY"] == "http://localhost:49468"
    assert process_env.get("HTTP_PROXY") is None


def test_agy_oauth_preflight_reports_proxy_url_and_source(
    tmp_path: Path,
) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
    from cli_executor import _agy_oauth_preflight

    role_profile = _agy_observer_fixture(tmp_path)
    model_values = {
        "provider": "agy-gemini-oauth",
        "model_key": "observer_model",
        "model_id": "gemini-3.5-flash-high",
        "catalog_model_id": "gemini-3.5-flash-high",
    }
    argv = ["agy", "--sandbox", "--model", "gemini-3.5-flash-high"]
    process_env = {
        "HTTPS_PROXY": "http://localhost:49468",
        "AGY_OAUTH_SESSION": "s",
    }
    preflight = _agy_oauth_preflight(role_profile, argv, model_values, process_env)

    assert preflight["proxy_url"] == "http://localhost:49468"
    assert preflight["proxy_source"] == "inherited_from_environment"


def test_agy_oauth_preflight_redacts_proxy_credentials_and_query() -> None:
    from cli_executor import _agy_oauth_preflight

    role_profile = {
        "cli_agent": "agy",
        "invocation_contract": "agy_observer",
        "default": "agy-gemini-3-pro",
    }
    argv = ["agy", "--model", "gemini-3-pro", "--sandbox"]
    model_values = {
        "model_key": "agy-gemini-3-pro",
        "model_id": "gemini-3-pro",
        "catalog_model_id": "gemini-3-pro",
        "provider": "agy-gemini-oauth",
    }
    process_env = {
        "HTTPS_PROXY": (
            "http://demo-user:demo-password@proxy.example:8080/private?token=secret"
        )
    }

    preflight = _agy_oauth_preflight(role_profile, argv, model_values, process_env)

    assert preflight["proxy_url"] == "http://proxy.example:8080"
    rendered = yaml.safe_dump(preflight, sort_keys=False)
    assert "demo-user" not in rendered
    assert "demo-password" not in rendered
    assert "token=secret" not in rendered


def _grok_research_fixture(
    tmp_path: Path,
    *,
    credential_present: bool = True,
    fallback_providers: list[dict] | None = None,
    template: str | None = None,
) -> tuple[dict, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "research_model": {
                        "provider": "hermes_xai_oauth",
                        "runtime_provider": "xai-oauth",
                        "cli_provider": "xai-oauth",
                        "model_id": "grok-4.3",
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
                    "grok_research": {
                        "worker_id": "grok",
                        "invocation_style": "sourced_research_task_packet",
                        "template": template
                        or (
                            'hermes --ignore-rules --provider xai-oauth '
                            '-m {model_id} -t web,x_search -z "Read the AgentLab Researcher '
                            'task packet at {task_packet_path}; return sourced evidence."'
                        ),
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "fallback_providers": (
                    [] if fallback_providers is None else fallback_providers
                )
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    auth_payload = {"version": 1, "providers": {}}
    if credential_present:
        auth_payload["providers"]["xai-oauth"] = {
            "auth_mode": "oauth",
            "tokens": {"id_token": "fixture-secret-must-never-be-recorded"},
        }
    (hermes_home / "auth.json").write_text(
        json.dumps(auth_payload),
        encoding="utf-8",
    )
    return (
        {
            "executor_type": "cli_agent",
            "cli_agent": "grok",
            "invocation_contract": "grok_research",
            "default": "research_model",
            "capacity_selected_route": "Researcher",
            "capacity_pool": "xai_subscription_shared",
            "capacity_attempt_id": "research-attempt-1",
            "capacity_selection_kind": "primary",
        },
        hermes_home,
    )


def _grok_native_fixture(tmp_path: Path) -> dict:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "model_catalog.yml").write_text(
        yaml.safe_dump(
            {
                "models": {
                    "native_grok_model": {
                        "provider": "grok_cli_oauth",
                        "runtime_provider": "grok-cli-oauth",
                        "cli_provider": "grok",
                        "model_id": "grok-4.5",
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
                    "grok_native_high": {
                        "worker_id": "grok",
                        "invocation_style": "bounded_role_task_packet",
                        "template": (
                            "grok --model {model_id} --reasoning-effort high "
                            "--permission-mode plan --disable-web-search "
                            "--no-subagents --no-memory --output-format plain "
                            '--verbatim --single "Read the bounded AgentLab role '
                            "task packet at {task_packet_path}; execute only the "
                            'assigned role contract."'
                        ),
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {
        "executor_type": "cli_agent",
        "cli_agent": "grok",
        "invocation_contract": "grok_native_high",
        "default": "native_grok_model",
        "capacity_selected_route": "ProfessionalGrokSupervisor",
        "capacity_pool": "grok_cli_subscription",
        "capacity_attempt_id": "native-grok-attempt-1",
        "capacity_selection_kind": "direct",
    }


def _sample_profiles(executor_type: str = "cli_agent") -> dict:
    """Return a minimal agent_model_profiles dict."""
    return {
        "schema_version": 3,
        "profiles": {
            "balanced": {
                "supervisor": {
                    "executor_type": executor_type,
                    "cli_agent": "hermes",
                    "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
                    "default": "deepseek_v4_pro",
                    "fallback": "qwen3_6_plus_dashscope",
                },
                "coder": {
                    "executor_type": executor_type,
                    "cli_agent": "claude_code",
                    "cli_command": "claude --task {task_packet_path}",
                    "default": "qwen3_coder_plus_dashscope",
                    "fallback": "deepseek_v4_flash",
                },
            },
            "frugal": {
                "supervisor": {
                    "executor_type": "direct_api",
                    "default": "deepseek_v4_flash",
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# resolve_cli_profile
# ---------------------------------------------------------------------------

class TestResolveCliProfile:
    def test_returns_profile_when_cli_agent(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("cli_agent")
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="balanced")
        assert result is not None
        assert result["cli_agent"] == "hermes"

    def test_returns_none_when_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("direct_api")
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="balanced")
        assert result is None

    def test_returns_none_for_frugal_direct_api(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles()
        result = resolve_cli_profile(profiles, agent_role="supervisor", profile_name="frugal")
        assert result is None

    def test_returns_none_for_unknown_profile(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        result = resolve_cli_profile({}, agent_role="supervisor", profile_name="nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# resolve_cli_profile — schema v4 (modes)
# ---------------------------------------------------------------------------


def _sample_modes_v4(executor_type: str = "cli_agent") -> dict:
    """Return a minimal schema v4 agent_model_profiles dict."""
    return {
        "schema_version": 4.0,
        "default_mode": "full_cli",
        "modes": {
            "full_cli": {
                "tiers": {
                    "full": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_pro",
                        },
                        "coder": {
                            "executor_type": executor_type,
                            "cli_agent": "claude_code",
                            "cli_command": "ccs --output-format json -p \"Read {task_packet_path}\"",
                            "default": "qwen3_coder_plus_dashscope",
                        },
                    },
                    "performance": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_pro",
                        },
                    },
                    "low": {
                        "supervisor": {
                            "executor_type": executor_type,
                            "cli_agent": "hermes",
                            "cli_command": 'hermes -z "Read {task_packet_path}"',
                            "default": "deepseek_v4_flash",
                        },
                        "interface_mapper": "skip",
                        "researcher": "skip",
                        "verifier": "skip",
                    },
                },
            },
            "full_api": {
                "tiers": {
                    "full": {
                        "supervisor": {
                            "executor_type": "direct_api",
                            "default": "deepseek_v4_pro",
                        },
                    },
                },
            },
            "hybrid_ide": {
                "tiers": {
                    "full": {
                        "coder": {
                            "executor_type": "special",
                            "provider": "external_ide_ai",
                        },
                    },
                },
            },
        },
    }


class TestResolveCliProfileSchemaV4:
    """Prove resolve_cli_profile supports schema v4 modes/tiers layout."""

    def test_real_default_full_cli_supervisor_resolves_to_hermes_grok(self):
        """The real default mode/tier keeps Supervisor on Hermes Grok."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        root = Path(__file__).resolve().parents[1]
        profiles = yaml.safe_load((root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8"))

        result = resolve_cli_profile(profiles, agent_role="supervisor")

        assert result is not None
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "alter"
        assert result["cli_agent"] == "hermes"
        assert result["invocation_contract"] == "hermes_alter_high"
        assert result["default"] == "grok_4_5_hermes_oauth"
        assert result["reasoning_effort"] == "high"
        assert result["capacity_route"] == "AlterSupervisor"
        assert "fallback" not in result

    def test_real_default_full_cli_writer_resolves_to_agy_gemini(self):
        """The real default mode/tier selects governed Agy Writer first."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        root = Path(__file__).resolve().parents[1]
        profiles = yaml.safe_load((root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8"))

        result = resolve_cli_profile(profiles, agent_role="writer")

        assert result is not None
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "alter"
        assert result["cli_agent"] == "agy"
        assert result["invocation_contract"] == "agy_writer"
        assert result["default"] == "gemini_3_6_flash_high_agy_oauth"
        assert result["capacity_route"] == "AlterWriter"
        assert "fallback" not in result

    def test_full_cli_full_supervisor_resolves_cli(self):
        """Schema v4 full_cli/full/supervisor returns CLI profile with hermes."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_cli"
        )
        assert result is not None, "full_cli/full/supervisor should resolve to CLI"
        assert result["cli_agent"] == "hermes"
        assert "hermes" in result["cli_command"]
        assert result["default"] == "deepseek_v4_pro"
        assert result["resolved_schema"] == "modes_v4"
        assert result["resolved_mode"] == "full_cli"
        assert result["resolved_tier"] == "full"

    def test_performance_tier_resolves_correct_cli(self):
        """Schema v4 full_cli/performance/supervisor resolves from performance tier."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="performance", mode="full_cli"
        )
        assert result is not None, "performance tier supervisor should resolve to CLI"
        assert result["cli_agent"] == "hermes"
        assert result["resolved_tier"] == "performance"

    def test_low_tier_skip_returns_none(self):
        """Schema v4 low tier with interface_mapper: skip returns None."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="interface_mapper", budget_mode="low", mode="full_cli"
        )
        assert result is None, "interface_mapper: skip should return None"

    def test_direct_api_role_does_not_become_cli(self):
        """Schema v4 full_api/full/supervisor (executor_type: direct_api) returns None."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_api"
        )
        assert result is None, "direct_api role should NOT become CLI"

    def test_legacy_profiles_still_work(self):
        """Old profiles schema still resolves with profile_name kwarg."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_profiles("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", profile_name="balanced"
        )
        assert result is not None
        assert result["cli_agent"] == "hermes"
        assert result["resolved_schema"] == "legacy_profiles"

    def test_no_auto_model_injection_into_cli_command(self):
        """CLI command does NOT contain -m or --model unless template has it."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="full", mode="full_cli"
        )
        assert result is not None
        cli_command = result["cli_command"]
        # Must NOT contain auto-injected -m or --model
        assert "-m deepseek_v4_pro" not in cli_command, (
            f"CLI command must not auto-inject -m: {cli_command}"
        )
        assert "--model deepseek_v4_pro" not in cli_command, (
            f"CLI command must not auto-inject --model: {cli_command}"
        )

    def test_budget_mode_frugal_maps_to_low_tier(self):
        """budget_mode='frugal' maps to 'low' tier via budget_mode_to_tier."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import resolve_cli_profile

        profiles = _sample_modes_v4("cli_agent")
        result = resolve_cli_profile(
            profiles, agent_role="supervisor", budget_mode="frugal", mode="full_cli"
        )
        assert result is not None
        assert result["resolved_tier"] == "low"
        assert result["default"] == "deepseek_v4_flash"

    def test_invocation_contract_resolves_cli_template(self, tmp_path):
        """CLI profiles can reference worker_invocation_contracts.yml."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_invocation_contract_template

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "worker_invocation_contracts.yml").write_text(
            """
contracts:
  hermes:
    template: 'hermes -z "Read {task_packet_path}"'
""",
            encoding="utf-8",
        )

        template = _resolve_invocation_contract_template(
            {
                "executor_type": "cli_agent",
                "cli_agent": "hermes",
                "invocation_contract": "hermes",
            },
            tmp_path,
        )

        assert template == 'hermes -z "Read {task_packet_path}"'


# ---------------------------------------------------------------------------
# _write_task_packet
# ---------------------------------------------------------------------------

class TestWriteTaskPacket:
    def test_writes_json_with_required_fields(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "runs" / "task_test_001"
        run_dir.mkdir(parents=True)

        packet_path = _write_task_packet(run_dir, "Supervisor", plan)
        assert packet_path.exists()

        data = json.loads(packet_path.read_text())
        assert data["agent"] == "Supervisor"
        assert data["project"] == "TestProject"
        assert data["task_id"] == "task_test_001"
        assert "generated_at" in data

    def test_packet_path_uses_agent_name(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "runs"
        run_dir.mkdir(parents=True)

        path = _write_task_packet(run_dir, "Coder", plan)
        assert path.name == "task_packet_coder.json"

    def test_writer_sealed_packet_omits_project_paths(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        messages = [
            {"role": "system", "content": "Use only injected context."},
            {"role": "user", "content": "Write the candidate chapter."},
        ]

        packet_path = _write_task_packet(run_dir, "Writer", plan, sealed_messages=messages)
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

        assert packet["packet_type"] == "agentlab_sealed_role_session"
        assert packet["messages"] == messages
        assert packet["context_policy"]["additional_file_reads_allowed"] is False
        assert "agentlab_root" not in packet
        assert "project_root" not in packet
        assert "run_dir" not in packet
        assert "user_request_path" not in packet

    def test_production_pack_role_packet_is_bounded_to_embedded_contract(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _write_task_packet

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        messages = [
            {"role": "system", "content": "ArtifactProducer contract."},
            {"role": "user", "content": "Return exactly three candidate files."},
        ]

        packet_path = _write_task_packet(
            run_dir,
            "ArtifactProducer",
            plan,
            task_messages=messages,
        )
        packet = json.loads(packet_path.read_text(encoding="utf-8"))

        assert packet["packet_type"] == "agentlab_production_pack_role_session"
        assert packet["messages"] == messages
        assert packet["context_policy"]["returned_artifacts_require_agentlab_materialization"] is True
        assert packet["context_policy"]["read_scope"] == ["this_task_packet"]
        assert packet["context_policy"]["additional_file_reads_allowed"] is False
        assert "agentlab_root" not in packet
        assert "project_root" not in packet
        assert "run_dir" not in packet
        assert "user_request_path" not in packet


# ---------------------------------------------------------------------------
# _render_command
# ---------------------------------------------------------------------------

class TestRenderCommand:
    def test_substitutes_placeholder(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command('hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."', tmp_path / "pkt.json")
        assert argv[0] == "hermes"
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_appends_path_when_no_placeholder(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command("agent-cli --task", tmp_path / "pkt.json")
        assert str(tmp_path / "pkt.json") in argv

    def test_substitutes_workspace_path(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        workspace = tmp_path / "workspace"
        argv = _render_command(
            'codex exec -C "{workspace_path}" "Read {task_packet_path}"',
            tmp_path / "pkt.json",
            workspace_path=workspace,
        )

        assert str(workspace) in argv
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_substitutes_declared_model_placeholders(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        argv = _render_command(
            'hermes --provider {provider} -m {model_id} -z "Read {task_packet_path}"',
            tmp_path / "pkt.json",
            provider="openai-codex",
            model_id="gpt-5.6-sol",
            model_key="codex_gpt_5_6_sol_xhigh_hermes_oauth",
        )

        assert argv[:5] == ["hermes", "--provider", "openai-codex", "-m", "gpt-5.6-sol"]
        assert any(str(tmp_path / "pkt.json") in arg for arg in argv)

    def test_substitutes_narrative_audit_schema_as_one_argv_value(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        schema = json.dumps(
            {"type": "object", "required": ["fiction_review"]},
            separators=(",", ":"),
        )
        argv = _render_command(
            "claude --json-schema '{narrative_audit_schema}' -p audit",
            tmp_path / "pkt.json",
            narrative_audit_schema=schema,
            append_task_packet_path=False,
        )

        assert argv == ["claude", "--json-schema", schema, "-p", "audit"]

    def test_agy_catalog_resolves_cli_model_slug(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _model_invocation_values

        root = Path(__file__).resolve().parents[1]
        values = _model_invocation_values(
            {"default": "gemini_3_5_flash_high_agy_oauth"},
            root,
        )

        assert values["model_id"] == "gemini-3.5-flash-high"

    def test_rejects_unresolved_placeholders(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _render_command

        with pytest.raises(ValueError, match="frontdesk_session_path"):
            _render_command(
                'agy --sandbox -p "Read {frontdesk_session_path}"',
                tmp_path / "pkt.json",
            )


# ---------------------------------------------------------------------------
# run_cli_agent — binary not found
# ---------------------------------------------------------------------------

class TestRunCliAgentBinaryNotFound:
    def test_returns_not_available_when_binary_missing(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": "hermes_binary_does_not_exist_xyz --task {task_packet_path}",
            "default": "deepseek_v4_pro",
        }

        with patch("cli_executor.shutil.which", return_value=None):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert "hermes" in result.cli_agent or "not_found" in result.reason

    def test_returns_not_available_on_filenotfounderror(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
            "default": "deepseek_v4_pro",
        }

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=FileNotFoundError("hermes")):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)


# ---------------------------------------------------------------------------
# run_cli_agent — subprocess success and failure
# ---------------------------------------------------------------------------

class TestRunCliAgentSubprocess:
    def _mock_proc(self, returncode: int, stdout: str = "", stderr: str = ""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_codex_supervisor_writes_verified_model_execution_receipt(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {
                    "contracts": {
                        "codex_supervisor": {
                            "worker_id": "codex",
                            "required_runtime_provider": "codex-cli",
                            "required_model_key": "codex_gpt_5_6_sol_xhigh_cli_oauth",
                            "template": (
                                "codex exec --json --model {model_id} "
                                "-c 'model_reasoning_effort=\"xhigh\"' "
                                "--sandbox read-only --ephemeral --ignore-rules "
                                "--skip-git-repo-check "
                                "-C {workspace_path} 'Read {task_packet_path}'"
                            ),
                            "requested_reasoning_label": "extra",
                            "resolved_reasoning_effort": "xhigh",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            yaml.safe_dump(
                {
                    "models": {
                        "codex_gpt_5_6_sol_xhigh_cli_oauth": {
                            "provider": "codex_cli_oauth",
                            "runtime_provider": "codex-cli",
                            "cli_provider": "codex",
                            "model_id": "gpt-5.6-sol",
                            "reasoning_effort": "xhigh",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "codex",
            "invocation_contract": "codex_supervisor",
            "default": "codex_gpt_5_6_sol_xhigh_cli_oauth",
            "capacity_route": "Supervisor",
        }
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "governed plan"},
            }
        )

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/codex"
        ), patch(
            "cli_executor.subprocess.run",
            return_value=self._mock_proc(0, stdout=stdout),
        ):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["worker"] == "codex"
        assert receipt["invocation_contract"] == "codex_supervisor"
        assert receipt["provider"] == "codex-cli"
        assert receipt["model"] == "gpt-5.6-sol"
        assert receipt["reasoning_effort"] == "xhigh"
        assert receipt["command_binding_verified"] is True
        assert (Path(plan.run_dir) / "model_execution_chain_supervisor.yml").is_file()

    def test_codex_supervisor_model_mismatch_blocks_before_provider_process(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {
                    "contracts": {
                        "codex_supervisor": {
                            "worker_id": "codex",
                            "required_runtime_provider": "codex-cli",
                            "required_model_key": "codex_gpt_5_6_sol_xhigh_cli_oauth",
                            "template": (
                                "codex exec --json --model {model_id} "
                                "-c 'model_reasoning_effort=\"xhigh\"' "
                                "--sandbox read-only --ephemeral --ignore-rules "
                                "--skip-git-repo-check "
                                "-C {workspace_path} 'Read {task_packet_path}'"
                            ),
                            "requested_reasoning_label": "extra",
                            "resolved_reasoning_effort": "xhigh",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            yaml.safe_dump(
                {
                    "models": {
                        "codex_gpt_5_6_sol_xhigh_cli_oauth": {
                            "provider": "hermes_codex_oauth",
                            "runtime_provider": "openai-codex",
                            "model_id": "gpt-5.6-sol",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "codex",
            "invocation_contract": "codex_supervisor",
            "default": "codex_gpt_5_6_sol_xhigh_cli_oauth",
        }

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/codex"
        ), patch("cli_executor.subprocess.run") as provider_process:
            result = run_cli_agent(plan, "Supervisor", role_profile)

        provider_process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "supervisor_model_preflight_failed"
        preflight = result.raw_usage["supervisor_model_preflight"]
        assert "catalog_provider_mismatch" in preflight["issues"]
        assert "Hermes" not in result.content
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["worker"] == "codex"
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is False

    def test_runtime_model_receipts_are_role_scoped_and_do_not_overwrite(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import (
            _write_agy_model_receipt,
            _write_hermes_supervisor_model_receipt,
        )

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        supervisor_path = _write_hermes_supervisor_model_receipt(
            run_dir,
            {
                "applicable": True,
                "status": "pass",
                "issues": [],
                "required_shell_state": {
                    "model.provider": "openai-codex",
                    "model.default": "gpt-5.6-sol",
                },
                "command_binding_verified": True,
                "requested_reasoning_label": "extra",
                "resolved_reasoning_effort": "xhigh",
                "capacity_route": "SupervisorCodex",
                "attempt_id": "supervisor-primary-attempt",
                "selection_kind": "primary",
            },
            status="pass",
            provider_process_started=True,
        )
        base_agy = {
            "applicable": True,
            "status": "pass",
            "issues": [],
            "invocation_contract": "agy_observer",
            "requested_model_key": "gemini_3_5_flash_high_agy_oauth",
            "requested_model_id": "gemini-3.5-flash-high",
            "requested_cli_model_id": "Gemini 3.5 Flash (High)",
            "provider": "agy-gemini-oauth",
            "profile_binding_verified": True,
            "command_binding_verified": True,
            "capacity_route": "ObserverGemini",
            "attempt_id": "observer-primary-attempt",
            "selection_kind": "primary",
        }
        observer_path = _write_agy_model_receipt(
            run_dir,
            "Observer",
            base_agy,
            status="pass",
            provider_process_started=True,
            environment_unset=[],
        )
        reviewer_path = _write_agy_model_receipt(
            run_dir,
            "Reviewer",
            {**base_agy, "invocation_contract": "agy_visual_reviewer"},
            status="pass",
            provider_process_started=True,
            environment_unset=[],
        )

        paths = [Path(supervisor_path), Path(observer_path), Path(reviewer_path)]
        assert paths[0].name.startswith(
            "model_execution_receipt_supervisor_supervisorcodex_"
        )
        assert paths[1].name.startswith(
            "model_execution_receipt_observer_observergemini_"
        )
        assert paths[2].name.startswith(
            "model_execution_receipt_reviewer_observergemini_"
        )
        assert all(path.suffix == ".yml" for path in paths)
        assert all(path.is_file() for path in paths)
        assert [
            yaml.safe_load(path.read_text(encoding="utf-8"))["role"]
            for path in paths
        ] == ["Supervisor", "Observer", "Reviewer"]
        assert (run_dir / "model_execution_chain_supervisor.yml").is_file()
        assert (run_dir / "model_execution_chain_observer.yml").is_file()
        assert (run_dir / "model_execution_chain_reviewer.yml").is_file()

    def test_primary_and_approved_fallback_attempts_are_immutable_in_role_chains(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import (
            _write_agy_model_receipt,
            _write_claude_model_receipt,
            _write_hermes_supervisor_model_receipt,
        )

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        supervisor_primary = {
            "applicable": True,
            "status": "pass",
            "issues": [],
            "required_shell_state": {
                "model.provider": "openai-codex",
                "model.default": "gpt-5.6-sol",
            },
            "command_binding_verified": True,
            "requested_reasoning_label": "extra",
            "resolved_reasoning_effort": "xhigh",
            "capacity_route": "SupervisorCodex",
            "capacity_pool": "openai_codex_agentic",
            "attempt_id": "supervisor-primary",
            "selection_kind": "primary",
        }
        supervisor_primary_path = _write_hermes_supervisor_model_receipt(
            run_dir,
            supervisor_primary,
            status="fail",
            provider_process_started=True,
            extra_issues=["quota_exhausted"],
        )
        supervisor_fallback = {
            "applicable": True,
            "status": "pass",
            "issues": [],
            "invocation_contract": "claude_supervisor_fallback",
            "selected_provider": "deepseek",
            "selected_model_key": "deepseek_v4_pro",
            "selected_model_id": "deepseek-v4-pro",
            "requested_cli_model_id": "deepseek-v4-pro",
            "profile_binding_verified": True,
            "command_binding_verified": True,
            "capacity_route": "SupervisorDeepSeek",
            "capacity_pool": "claude_deepseek_supervisor",
            "attempt_id": "supervisor-fallback",
            "selection_kind": "approved_fallback",
        }
        supervisor_fallback_path = _write_claude_model_receipt(
            run_dir,
            "Supervisor",
            supervisor_fallback,
            status="pass",
            provider_process_started=True,
            usage={
                "usage_source": "external_cli_reported",
                "provider_reported_model_ids": ["deepseek-v4-pro"],
                "provider_reported_session_id": "fallback-session",
            },
        )

        agy_primary = {
            "applicable": True,
            "status": "pass",
            "issues": [],
            "invocation_contract": "agy_observer",
            "requested_model_key": "gemini_3_5_flash_high_agy_oauth",
            "requested_model_id": "gemini-3.5-flash-high",
            "requested_cli_model_id": "Gemini 3.5 Flash (High)",
            "provider": "agy-gemini-oauth",
            "profile_binding_verified": True,
            "command_binding_verified": True,
            "capacity_route": "ObserverGemini",
            "capacity_pool": "agy_gemini_observer",
            "attempt_id": "observer-primary",
            "selection_kind": "primary",
        }
        observer_primary_path = _write_agy_model_receipt(
            run_dir,
            "Observer",
            agy_primary,
            status="fail",
            provider_process_started=True,
            environment_unset=[],
            extra_issues=["quota_exhausted"],
        )
        observer_fallback_path = _write_agy_model_receipt(
            run_dir,
            "Observer",
            {
                **agy_primary,
                "requested_model_key": "claude_sonnet_4_6_agy_oauth",
                "requested_model_id": "claude-sonnet-4-6",
                "requested_cli_model_id": "Claude Sonnet 4.6 (Thinking)",
                "provider": "agy-claude-oauth",
                "capacity_route": "ObserverClaude",
                "capacity_pool": "agy_claude_observer",
                "attempt_id": "observer-fallback",
                "selection_kind": "approved_fallback",
            },
            status="pass",
            provider_process_started=True,
            environment_unset=[],
        )

        all_paths = [
            Path(supervisor_primary_path),
            Path(supervisor_fallback_path),
            Path(observer_primary_path),
            Path(observer_fallback_path),
        ]
        assert len({path.name for path in all_paths}) == 4
        assert all(path.is_file() for path in all_paths)
        supervisor_chain = yaml.safe_load(
            (run_dir / "model_execution_chain_supervisor.yml").read_text(
                encoding="utf-8"
            )
        )
        observer_chain = yaml.safe_load(
            (run_dir / "model_execution_chain_observer.yml").read_text(
                encoding="utf-8"
            )
        )
        assert len(supervisor_chain["attempts"]) == 2
        assert supervisor_chain["fallback_used"] is True
        assert supervisor_chain["final"]["capacity_route"] == "SupervisorDeepSeek"
        assert supervisor_chain["final"]["model"] == "deepseek-v4-pro"
        assert len(observer_chain["attempts"]) == 2
        assert observer_chain["fallback_used"] is True
        assert observer_chain["final"]["capacity_route"] == "ObserverClaude"
        fallback_receipt = yaml.safe_load(
            Path(observer_fallback_path).read_text(encoding="utf-8")
        )
        assert fallback_receipt["fallback_detected"] is True
        assert fallback_receipt["fallback_chain"] == ["ObserverGemini"]

    def test_completed_on_exit_0(self, tmp_path):
        import sys
        import yaml
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"
        run_dir.mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
            "default": "deepseek_v4_pro",
        }

        mock_proc = self._mock_proc(0, stdout="# Supervisor Report\n\nAll good.")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        assert result.provider == "agentlab-cli-executor"
        assert result.model == "hermes"
        assert result.input_tokens is not None
        assert result.output_tokens is not None
        assert result.total_tokens == result.input_tokens + result.output_tokens
        assert result.raw_usage["usage_source"] == "external_cli_estimate"
        assert result.raw_usage["exact_usage_available"] is False
        assert result.raw_usage["exact_cost_available"] is False
        assert result.raw_usage["token_estimation_method"] == "chars_div_4_packet_command_stdout_stderr"
        assert "Supervisor Report" in result.content
        assert "command_id" in result.raw_usage
        assert f"command_id {result.raw_usage['command_id']}" in result.content
        execution_log = yaml.safe_load((run_dir / "execution_log.yml").read_text(encoding="utf-8"))
        assert execution_log["commands"][0]["command_id"] == result.raw_usage["command_id"]
        assert execution_log["commands"][0]["exit_code"] == 0

    def test_external_context_env_cannot_self_approve_without_signature(
        self,
        tmp_path,
        monkeypatch,
    ):
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        scope_sha256 = "a" * 64
        plan.execution_policy = {
            "external_context_approval_required": True,
            "external_context_payload_sha256_required": True,
            "external_context_scope_sha256_required": True,
            "external_context_scope_contract_valid": True,
            "external_context_scope_sha256": scope_sha256,
            "external_context_transfer": {
                "recipient": "cli_agent:hermes;runtime_provider:test",
                "purpose": "bounded test transfer",
                "expires_at": "2999-01-01T00:00:00Z",
            },
        }
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": "hermes --task {task_packet_path}",
            "default": "deepseek_v4_pro",
        }
        monkeypatch.setenv("AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED", "1")
        monkeypatch.setenv(
            "AGENTLAB_ROLE_SESSION_ACCEPTANCE_PAYLOAD_SHA256",
            "b" * 64,
        )
        monkeypatch.setenv(
            "AGENTLAB_ROLE_SESSION_ACCEPTANCE_SCOPE_SHA256",
            scope_sha256,
        )

        with patch(
            "cli_executor.shutil.which",
            return_value="/usr/bin/hermes",
        ), patch("cli_executor.subprocess.run") as process:
            result = run_cli_agent(
                plan,
                "Supervisor",
                role_profile,
                sealed_messages=[
                    {"role": "user", "content": "private context"}
                ],
            )

        assert result.status == "blocked_user_decision"
        assert result.error == "supervisor_outbound_context_gate_blocked"
        process.assert_not_called()

    def test_hermes_supervisor_runtime_binds_extra_to_xhigh_and_writes_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile, hermes_home = _hermes_supervisor_fixture(tmp_path)
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            observed["argv"] = argv
            observed["env"] = kwargs["env"]
            return self._mock_proc(0, stdout="# Governed Supervisor Plan\n")

        with patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}, clear=False), \
             patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        assert observed["argv"][:9] == [
            "hermes",
            "-p",
            "agentlabsupervisor",
            "chat",
            "-Q",
            "--provider",
            "openai-codex",
            "-m",
            "gpt-5.6-sol",
        ]
        assert observed["argv"][9:13] == [
            "--ignore-rules",
            "--max-turns",
            "6",
            "-q",
        ]
        assert result.raw_usage["hermes_profile_preflight"]["status"] == "pass"
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        assert receipt_path.name.startswith(
            "model_execution_receipt_supervisor_direct_"
        )
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "pass"
        assert receipt["requested_reasoning_label"] == "extra"
        assert receipt["reasoning_effort"] == "xhigh"
        assert receipt["provider"] == "openai-codex"
        assert receipt["model"] == "gpt-5.6-sol"
        assert receipt["fallback_chain"] == []
        assert receipt["profile_state_verified"] is True
        assert receipt["command_binding_verified"] is True
        assert receipt["provider_process_started"] is True
        assert receipt["provider_response_metadata_observed"] is False

    def test_grok_research_runs_only_from_read_only_sealed_workspace_and_writes_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        plan.route.agents = ["Supervisor", "Researcher"]
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "mission_contract.yml"
        source.write_text("scope: public_research\n", encoding="utf-8")
        role_profile, hermes_home = _grok_research_fixture(tmp_path)
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            workspace = Path(kwargs["cwd"])
            packet_path = workspace / "task_packet_researcher.json"
            observed["argv"] = list(argv)
            observed["cwd"] = workspace
            observed["cwd_mode"] = workspace.stat().st_mode
            observed["packet_mode"] = packet_path.stat().st_mode
            observed["packet"] = json.loads(packet_path.read_text(encoding="utf-8"))
            return self._mock_proc(0, stdout="# Sourced research\n", stderr="")

        with patch.dict(
            "cli_executor.os.environ",
            {"HERMES_HOME": str(hermes_home)},
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/hermes"
        ), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(
                plan,
                "Researcher",
                role_profile,
                sealed_messages=[
                    {"role": "user", "content": "Collect public evidence only."}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        preflight = result.raw_usage["grok_research_preflight"]
        assert preflight["status"] == "pass"
        assert preflight["credential_present"] is True
        assert preflight["fallback_chain_empty"] is True
        assert preflight["command_binding_verified"] is True
        assert preflight["allowed_toolsets"] == ["web", "x_search"]
        assert preflight["read_only_workspace_verified"] is True
        assert observed["cwd"] != Path(plan.agentlab_root)
        assert observed["cwd_mode"] & 0o222 == 0
        assert observed["packet_mode"] & 0o222 == 0
        packet = observed["packet"]
        assert packet["context_policy"]["workspace_mutation_allowed"] is False
        assert packet["context_policy"]["external_domain_research_allowed"] is True
        assert packet["context_policy"]["read_scope"] == ["this_task_packet"]
        assert packet["declared_sources"] == [
            {
                "path": "projects/TestProject/runs/task_test_001/mission_contract.yml",
                "byte_count": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "delivery": "embedded_in_sealed_messages",
                "local_file_access_allowed": False,
            }
        ]
        assert not Path(observed["cwd"]).exists()
        assert observed["argv"][:6] == [
            "hermes",
            "--ignore-rules",
            "--provider",
            "xai-oauth",
            "-m",
            "grok-4.3",
        ]
        assert observed["argv"][6:9] == ["-t", "web,x_search", "-z"]
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        assert receipt_path.name.startswith(
            "model_execution_receipt_researcher_researcher_"
        )
        receipt_text = receipt_path.read_text(encoding="utf-8")
        assert "fixture-secret-must-never-be-recorded" not in receipt_text
        receipt = yaml.safe_load(receipt_text)
        assert receipt["status"] == "pass"
        assert receipt["provider"] == "xai-oauth"
        assert receipt["model"] == "grok-4.3"
        assert receipt["credential_present"] is True
        assert receipt["allowed_toolsets"] == ["web", "x_search"]
        assert receipt["provider_process_started"] is True
        assert receipt["fallback_chain"] == []
        chain = yaml.safe_load(
            (run_dir / "model_execution_chain_researcher.yml").read_text(
                encoding="utf-8"
            )
        )
        assert len(chain["attempts"]) == 1
        assert chain["final"]["receipt_path"] == str(receipt_path)

    def test_native_grok_success_writes_route_verified_model_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        role_profile = _grok_native_fixture(tmp_path)

        with patch(
            "cli_executor.shutil.which", return_value="/usr/local/bin/grok"
        ), patch(
            "cli_executor.subprocess.run",
            return_value=self._mock_proc(
                0,
                stdout="# Authorial direction\n\nProceed with the locked canon.\n",
            ),
        ):
            result = run_cli_agent(
                plan,
                "Supervisor",
                role_profile,
                sealed_messages=[
                    {
                        "role": "user",
                        "content": "Return the governed authorial direction.",
                    }
                ],
            )

        assert result.status == "completed"
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "pass"
        assert receipt["role"] == "Supervisor"
        assert receipt["worker"] == "grok"
        assert receipt["invocation_contract"] == "grok_native_high"
        assert receipt["provider"] == "grok-cli-oauth"
        assert receipt["model"] == "grok-4.5"
        assert receipt["profile_binding_verified"] is True
        assert receipt["command_binding_verified"] is True
        assert receipt["provider_process_started"] is True
        assert receipt["auth_presence_verified"] is False
        assert receipt["provider_auth_result_observed"] is True
        assert receipt["evidence_source"] == (
            "runtime_verified_argv_profile_workspace_and_process_result"
        )
        assert receipt["fallback_detected"] is False
        assert receipt["issues"] == []

    def test_grok_research_missing_oauth_credential_blocks_before_provider_process(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        source = Path(plan.user_request_path)
        source.write_text("Research public evidence.\n", encoding="utf-8")
        role_profile, hermes_home = _grok_research_fixture(
            tmp_path,
            credential_present=False,
        )

        with patch.dict(
            "cli_executor.os.environ",
            {"HERMES_HOME": str(hermes_home)},
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/hermes"
        ), patch(
            "cli_executor.subprocess.run"
        ) as provider_process:
            result = run_cli_agent(
                plan,
                "Researcher",
                role_profile,
                sealed_messages=[{"role": "user", "content": "Research."}],
                outbound_source_paths=[source],
            )

        provider_process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "grok_research_preflight_failed"
        assert result.raw_usage["provider_process_started"] is False
        assert "xai_oauth_credential_missing" in result.raw_usage[
            "grok_research_preflight"
        ]["issues"]
        receipt_text = Path(
            result.raw_usage["model_execution_receipt"]
        ).read_text(encoding="utf-8")
        assert "fixture-secret-must-never-be-recorded" not in receipt_text
        receipt = yaml.safe_load(receipt_text)
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is False

    def test_grok_research_unsafe_command_blocks_before_provider_process(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        source = Path(plan.user_request_path)
        source.write_text("Research public evidence.\n", encoding="utf-8")
        role_profile, hermes_home = _grok_research_fixture(
            tmp_path,
            template=(
                'hermes --yolo --provider xai-oauth -m {model_id} '
                '-z "Read {task_packet_path}"'
            ),
        )

        with patch.dict(
            "cli_executor.os.environ",
            {"HERMES_HOME": str(hermes_home)},
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/hermes"
        ), patch(
            "cli_executor.subprocess.run"
        ) as provider_process:
            result = run_cli_agent(
                plan,
                "Researcher",
                role_profile,
                sealed_messages=[{"role": "user", "content": "Research."}],
                outbound_source_paths=[source],
            )

        provider_process.assert_not_called()
        issues = result.raw_usage["grok_research_preflight"]["issues"]
        assert "grok_research_command_binding_mismatch" in issues
        assert "grok_research_forbidden_command_flag:--yolo" in issues

    def test_grok_research_missing_binary_writes_preflight_receipt_without_process(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        source = Path(plan.user_request_path)
        source.write_text("Research public evidence.\n", encoding="utf-8")
        role_profile, hermes_home = _grok_research_fixture(tmp_path)

        with patch.dict(
            "cli_executor.os.environ",
            {"HERMES_HOME": str(hermes_home)},
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value=None
        ), patch(
            "cli_executor.subprocess.run"
        ) as provider_process:
            result = run_cli_agent(
                plan,
                "Researcher",
                role_profile,
                sealed_messages=[{"role": "user", "content": "Research."}],
                outbound_source_paths=[source],
            )

        provider_process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert "grok_research_binary_missing" in result.raw_usage[
            "grok_research_preflight"
        ]["issues"]
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is False

    def test_agy_observer_strips_direct_api_keys_and_writes_oauth_model_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = _agy_observer_fixture(tmp_path)
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            observed["argv"] = argv
            observed["env"] = kwargs["env"]
            return self._mock_proc(
                0,
                stdout=(
                    "status: complete\n"
                    "observations:\n"
                    "  - summary: visible evidence\n"
                    "actionable_suggestions:\n"
                    "  - verify the timestamp\n"
                ),
            )

        direct_api_keys = {
            "GEMINI_API_KEY": "gemini-secret",
            "GOOGLE_API_KEY": "google-secret",
            "GOOGLE_GENAI_API_KEY": "genai-secret",
            "GOOGLE_GENERATIVE_AI_API_KEY": "generative-secret",
            "GOOGLE_AI_API_KEY": "ai-secret",
            "GOOGLE_GEMINI_API_KEY": "alternate-secret",
            "GENAI_API_KEY": "generic-secret",
        }
        with patch.dict(
            "cli_executor.os.environ",
            {**direct_api_keys, "AGY_OAUTH_SESSION": "preserved-session"},
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/agy"
        ), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(plan, "Observer", role_profile)

        assert result.status == "completed"
        assert observed["argv"][:4] == [
            "agy",
            "--sandbox",
            "--model",
            "gemini-3.5-flash-high",
        ]
        process_env = observed["env"]
        assert process_env["AGY_OAUTH_SESSION"] == "preserved-session"
        assert all(name not in process_env for name in direct_api_keys)
        assert result.raw_usage["contract_environment_unset"] == sorted(
            direct_api_keys
        )

        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        assert receipt_path.name.startswith(
            "model_execution_receipt_observer_observergemini_"
        )
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "pass"
        assert receipt["role"] == "Observer"
        assert receipt["worker"] == "agy"
        assert receipt["invocation_contract"] == "agy_observer"
        assert receipt["auth_mode"] == "local_agy_oauth_session"
        assert receipt["provider"] == "agy-gemini-oauth"
        assert receipt["requested_model_key"] == "observer_model"
        assert receipt["requested_model_id"] == "gemini-3.5-flash-high"
        assert receipt["requested_cli_model_id"] == "gemini-3.5-flash-high"
        assert receipt["capacity_route"] == "ObserverGemini"
        assert receipt["capacity_pool"] == "agy_gemini_observer"
        assert receipt["profile_binding_verified"] is True
        assert receipt["command_binding_verified"] is True
        assert receipt["provider_process_started"] is True
        assert receipt["provider_response_metadata_observed"] is False
        assert receipt["fallback_detected"] is False
        assert receipt["fallback_chain"] == []

    def test_agy_narrative_planner_governs_subscription_model_and_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from agent_runtime.narrative_delivery import (
            narrative_planner_validation_issues,
            write_narrative_planner_validation,
        )

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = _agy_observer_fixture(tmp_path)
        role_profile.update(
            {
                "invocation_contract": "agy_narrative_planner",
                "capacity_selected_route": "NarrativePlannerAgy",
                "default": "gemini_3_5_flash_high_agy_oauth",
            }
        )
        repo_root = Path(__file__).resolve().parents[1]
        source_catalog = yaml.safe_load(
            (repo_root / "config" / "model_catalog.yml").read_text(encoding="utf-8")
        )
        catalog_path = tmp_path / "config" / "model_catalog.yml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        catalog["models"]["gemini_3_5_flash_high_agy_oauth"] = source_catalog[
            "models"
        ]["gemini_3_5_flash_high_agy_oauth"]
        catalog_path.write_text(
            yaml.safe_dump(catalog, sort_keys=False),
            encoding="utf-8",
        )
        contracts_path = tmp_path / "config" / "worker_invocation_contracts.yml"
        contracts = yaml.safe_load(contracts_path.read_text(encoding="utf-8"))
        source_contracts = yaml.safe_load(
            (repo_root / "config" / "worker_invocation_contracts.yml").read_text(
                encoding="utf-8"
            )
        )
        contracts["contracts"]["agy_narrative_planner"] = source_contracts[
            "contracts"
        ]["agy_narrative_planner"]
        contracts_path.write_text(
            yaml.safe_dump(contracts, sort_keys=False),
            encoding="utf-8",
        )
        planner_document = {
            "schema_version": 1,
            "project": "TestProject",
            "status": "candidate",
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [1, 1],
            "target_character_range": [4500, 5500],
            "hard_character_range": [3000, 8000],
            "chapter_state_plan": [
                {
                    "chapter": 1,
                    "title": "Opening",
                    "volume": "Volume One",
                    "phase": "Opening",
                    "timeline_slot": "day-1",
                    "pov": "Kane",
                    "opening_state": "before",
                    "scene_goal": "complete the first bargain",
                    "irreversible_plot_change": "the bargain is sealed",
                    "character_state_change": "Kane accepts the cost",
                    "relationship_or_worldline_change": "the archive now knows Kane",
                    "foreshadowing_action": "defer the hidden price",
                    "closing_state": "after",
                    "must_not_repeat": ["the opening bargain"],
                }
            ],
            "validation_contract": {
                "exact_chapter_count": 1,
                "ordered_unique_chapters": True,
                "unique_scene_goals": True,
                "unique_irreversible_plot_changes": True,
                "monotonic_story_state": True,
            },
        }
        planner_yaml = yaml.safe_dump(
            planner_document,
            sort_keys=False,
            allow_unicode=True,
        )
        (Path(plan.run_dir) / "narrative_rewrite_contract.yml").write_text(
            yaml.safe_dump({"chapter_range": [1, 1]}),
            encoding="utf-8",
        )

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/agy"
        ), patch(
            "cli_executor.subprocess.run",
            return_value=self._mock_proc(0, stdout=planner_yaml),
        ):
            result = run_cli_agent(plan, "NarrativePlanner", role_profile)

        assert result.status == "completed"
        assert result.content == planner_yaml.strip()
        assert not result.content.startswith("# NarrativePlanner Report")
        output_path = Path(plan.run_dir) / "chapter_state_plan.yml"
        output_path.write_text(result.content, encoding="utf-8")
        validation = write_narrative_planner_validation(
            Path(plan.project_root),
            Path(plan.run_dir),
            output_path,
        )
        assert narrative_planner_validation_issues(validation) == []
        preflight = result.raw_usage["agy_oauth_preflight"]
        assert preflight["governed"] is True
        assert preflight["status"] == "pass"
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["role"] == "NarrativePlanner"
        assert receipt["invocation_contract"] == "agy_narrative_planner"
        assert receipt["provider"] == "agy-gemini-oauth"
        assert receipt["capacity_route"] == "NarrativePlannerAgy"
        assert receipt["capacity_pool"] == "agy_gemini_observer"
        assert receipt["command_binding_verified"] is True

    def test_agy_observer_command_model_mismatch_blocks_before_provider_process(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = _agy_observer_fixture(tmp_path)
        contract_path = tmp_path / "config" / "worker_invocation_contracts.yml"
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        contract["contracts"]["agy_observer"]["template"] = (
            'agy --sandbox --model "Unexpected Model" '
            '-p "Read {task_packet_path}"'
        )
        contract_path.write_text(
            yaml.safe_dump(contract, sort_keys=False),
            encoding="utf-8",
        )

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/agy"
        ), patch("cli_executor.subprocess.run") as provider_process:
            result = run_cli_agent(plan, "Observer", role_profile)

        provider_process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "agy_oauth_model_preflight_failed"
        assert result.raw_usage["provider_process_started"] is False
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["status"] == "fail"
        assert receipt["command_binding_verified"] is False
        assert "agy_command_model_binding_mismatch" in receipt["issues"]

    def test_agy_observer_exec_file_not_found_writes_failure_receipt(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = _agy_observer_fixture(tmp_path)

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/agy"
        ), patch(
            "cli_executor.subprocess.run", side_effect=FileNotFoundError("agy")
        ):
            result = run_cli_agent(plan, "Observer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.raw_usage["provider_process_started"] is False
        assert result.raw_usage["failure_class"] == "binary_unavailable"
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is False
        assert "provider_process_file_not_found" in receipt["issues"]

    def test_agy_observer_timeout_writes_failure_receipt(self, tmp_path):
        import subprocess
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = _agy_observer_fixture(tmp_path)

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/agy"
        ), patch(
            "cli_executor.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd="agy",
                timeout=5,
                output="partial observation",
            ),
        ):
            result = run_cli_agent(plan, "Observer", role_profile, timeout=5)

        assert result.status == "blocked_user_decision"
        assert result.raw_usage["agy_oauth_preflight"]["status"] == "pass"
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is True
        assert receipt["timed_out"] is True
        assert "provider_process_timeout" in receipt["issues"]

    @pytest.mark.parametrize(
        ("reasoning_effort", "fallback_providers", "expected_issue"),
        [
            ("high", None, "profile_state_mismatch:agent.reasoning_effort"),
            (
                "xhigh",
                [{"provider": "deepseek", "model": "deepseek-v4"}],
                "profile_state_mismatch:fallback_providers",
            ),
        ],
    )
    def test_hermes_supervisor_profile_mismatch_blocks_before_provider_process(
        self,
        tmp_path,
        reasoning_effort,
        fallback_providers,
        expected_issue,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile, hermes_home = _hermes_supervisor_fixture(
            tmp_path,
            reasoning_effort=reasoning_effort,
            fallback_providers=fallback_providers,
        )

        with patch.dict("os.environ", {"HERMES_HOME": str(hermes_home)}, clear=False), \
             patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run") as provider_process:
            result = run_cli_agent(plan, "Supervisor", role_profile)

        provider_process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "supervisor_model_preflight_failed"
        assert result.raw_usage["provider_process_started"] is False
        assert expected_issue in result.raw_usage["supervisor_model_preflight"]["issues"]
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(encoding="utf-8")
        )
        assert receipt["status"] == "fail"
        assert receipt["provider_process_started"] is False
        assert expected_issue in receipt["issues"]

    def test_writer_cli_uses_sealed_packet_and_isolated_workspace(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "chapter_packet.yml"
        source.write_text("chapter: 1\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            packet_path = Path(kwargs["cwd"]) / "task_packet_writer.json"
            observed["packet"] = json.loads(packet_path.read_text(encoding="utf-8"))
            observed["workspace"] = Path(kwargs["cwd"])
            observed["packet_path"] = packet_path
            observed["argv"] = argv
            return self._mock_proc(0, stdout="writer output", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "sealed chapter context"}],
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        assert result.raw_usage["sealed_context"] is True
        assert result.raw_usage["execution_workspace_isolated"] is True
        assert observed["workspace"] != Path(plan.agentlab_root)
        assert observed["workspace"] == observed["workspace"].resolve()
        assert observed["packet_path"].parent == observed["workspace"]
        assert observed["packet"]["context_policy"]["read_scope"] == ["this_task_packet"]
        assert not Path(observed["workspace"]).exists()
        argv = observed["argv"]
        prompt = argv[argv.index("-p") + 1]
        assert "sealed chapter context" not in prompt
        assert "task_packet_writer.json" in prompt
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_writer.yml").read_text(encoding="utf-8")
        )
        assert manifest["status"] == "pass"
        assert manifest["payload"]["kind"] == "sealed_cli_role_session_packet"
        assert manifest["context_boundary"]["execution_workspace_isolated"] is True
        execution_log = yaml.safe_load(
            (run_dir / "execution_log.yml").read_text(encoding="utf-8")
        )
        command = execution_log["commands"][0]
        assert "sealed chapter context" not in command["command"]
        assert "sealed chapter context" not in " ".join(command["argv"])
        assert result.raw_usage["inline_sealed_prompt"] is False

    def test_qwen_narrative_audit_reads_sealed_packet_from_stdin_and_extracts_result(
        self,
        tmp_path,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _task_packet_payload, run_cli_agent

        plan = _make_plan(tmp_path)
        plan.route.route_key = "narrative_heavy_audit"
        plan.route.agents = ["Supervisor", "Reviewer", "Scribe", "Verifier"]
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "narrative_audit_context.md"
        source.write_text("complete bounded context\n", encoding="utf-8")
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {
                    "contracts": {
                        "qwen_narrative_audit": {
                            "worker_id": "qwen",
                            "model_profile": "qwen3_6_flash_dashscope",
                            "packet_delivery": "stdin",
                            "structured_output": "narrative_heavy_audit",
                            "environment": {
                                "api_key_source": "DASHSCOPE_API_KEY",
                                "api_key_target": "OPENAI_API_KEY",
                                "base_url_target": "OPENAI_BASE_URL",
                                "base_url": "https://dashscope.example/v1",
                            },
                            "template": (
                                "qwen --bare --auth-type openai "
                                "--openai-base-url https://dashscope.example/v1 "
                                "--model {model_id} --approval-mode default "
                                "--max-session-turns 2 "
                                "--exclude-tools "
                                "edit,write_file,read_file,grep_search,glob,run_shell_command,"
                                "todo_write,save_memory,agent,skill,exit_plan_mode,enter_plan_mode,"
                                "web_fetch,list_directory,lsp,ask_user_question,cron_create,"
                                "cron_list,cron_delete,loop_wakeup,task_stop,task_create,task_update,"
                                "task_list,team_create,team_delete,send_message,monitor,notebook_edit,"
                                "tool_search,enter_worktree,exit_worktree,workflow,artifact "
                                "--max-tool-calls 1 "
                                "--json-schema @narrative_heavy_audit_output.schema.json "
                                "--output-format stream-json"
                            ),
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            yaml.safe_dump(
                {
                    "models": {
                        "qwen3_6_flash_dashscope": {
                            "provider": "dashscope_cn",
                            "model_id": "qwen3.6-flash",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "codex",
            "invocation_contract": "qwen_narrative_audit",
            "default": "deepseek_v4_flash",
        }
        sealed_messages = [
            {"role": "system", "content": "Do not call tools."},
            {"role": "user", "content": "Audit all 20 chapters."},
        ]
        _authorize_external_packet(
            plan,
            agent_name="Reviewer",
            cli_agent_name="qwen",
            sealed_messages=sealed_messages,
        )
        structured_result = {
            "fiction_review": {
                "schema_version": 1,
                "status": "pass",
                "candidate_only": True,
                "production_modified": False,
                "findings": [],
            },
            "continuity_failure_report": {
                "schema_version": 1,
                "status": "pass",
                "candidate_only": True,
                "production_modified": False,
                "blocking_issue_count": 0,
                "failures": [],
            },
            "narrative_quality_scorecard": {
                "schema_version": 1,
                "status": "pass",
                "candidate_only": True,
                "production_modified": False,
                "candidate_sha256": "candidate-sha",
                "chapters": [
                    {
                        "chapter_id": 1,
                        "status": "pass",
                        "dimensions": {
                            name: {
                                "score": 5,
                                "severity": "pass",
                                "evidence": {
                                    "chapter": 1,
                                    "scene": "opening",
                                    "excerpt_or_locator": "paragraph 1",
                                },
                                "reason": "specific evidence",
                                "revision_target": "none",
                            }
                            for name in (
                                "causal_reasoning",
                                "strategic_competence",
                                "character_agency",
                                "dramatic_tension",
                                "reader_curiosity",
                                "non_formulaic_progression",
                            )
                        },
                    }
                ],
            },
        }
        stdout = "\n".join(
            json.dumps(event)
            for event in [
                {"type": "system", "subtype": "init"},
                {
                    "type": "result",
                    "subtype": "success",
                    "result": structured_result,
                    "usage": {
                        "input_tokens": 1234,
                        "output_tokens": 234,
                        "total_tokens": 1468,
                    },
                },
            ]
        )
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            if argv[0] == "/usr/bin/openssl":
                return _REAL_SUBPROCESS_RUN(argv, **kwargs)
            observed["argv"] = list(argv)
            observed["kwargs"] = dict(kwargs)
            observed["packet"] = json.loads(kwargs["input"])
            schema_path = Path(kwargs["cwd"]) / "narrative_heavy_audit_output.schema.json"
            observed["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
            return self._mock_proc(0, stdout=stdout, stderr="")

        with patch.dict(
            "cli_executor.os.environ",
            {
                "DASHSCOPE_API_KEY": "private-test-key",
            },
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/qwen"
        ), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(
                plan,
                "Reviewer",
                role_profile,
                sealed_messages=sealed_messages,
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        assert observed["packet"]["packet_type"] == "agentlab_sealed_role_session"
        kwargs = observed["kwargs"]
        assert "stdin" not in kwargs
        assert kwargs["input"]
        argv = observed["argv"]
        assert argv[0] == "qwen"
        assert argv[argv.index("--model") + 1] == "qwen3.6-flash"
        assert argv[argv.index("--max-tool-calls") + 1] == "1"
        assert "--core-tools" not in argv
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        excluded_tools = set(argv[argv.index("--exclude-tools") + 1].split(","))
        assert "structured_output" not in excluded_tools
        assert {
            "read_file",
            "write_file",
            "edit",
            "grep_search",
            "glob",
            "run_shell_command",
            "list_directory",
            "todo_write",
            "agent",
            "tool_search",
        } <= excluded_tools
        assert argv[argv.index("--json-schema") + 1] == (
            "@narrative_heavy_audit_output.schema.json"
        )
        assert not any(arg.endswith("task_packet_reviewer.json") for arg in argv)
        assert "<!-- AGENTLAB_EDIT: fiction_review.yml -->" in result.content
        assert "<!-- AGENTLAB_EDIT: continuity_failure_report.yml -->" in result.content
        assert "<!-- AGENTLAB_EDIT: narrative_quality_scorecard.yml -->" in result.content
        assert "candidate_only: true" in result.content
        assert '\"type\": \"result\"' not in result.content
        assert result.input_tokens == 1234
        assert result.output_tokens == 234
        assert result.raw_usage["sealed_packet_stdin"] is True
        assert result.raw_usage["cli_agent"] == "qwen"
        assert observed["schema"]["required"] == [
            "fiction_review",
            "continuity_failure_report",
            "narrative_quality_scorecard",
        ]

    def test_qwen_literary_ab_stages_strict_schema_and_extracts_anonymous_result(
        self,
        tmp_path,
    ):
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _task_packet_payload, run_cli_agent
        from agent_runtime.narrative.quality.live_editor import (
            LITERARY_EDITOR_DIMENSIONS,
        )

        plan = _make_plan(tmp_path)
        plan.route.route_key = "narrative_heavy_audit"
        plan.route.agents = ["Reviewer"]
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "narrative_audit_context.md"
        source.write_text("anonymous manuscripts A and B\n", encoding="utf-8")
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {
                    "contracts": {
                        "qwen_narrative_literary_ab": {
                            "worker_id": "qwen",
                            "model_profile": "qwen3_7_max_dashscope",
                            "packet_delivery": "stdin",
                            "structured_output": "narrative_literary_ab",
                            "environment": {
                                "api_key_source": "DASHSCOPE_API_KEY",
                                "api_key_target": "OPENAI_API_KEY",
                                "base_url_target": "OPENAI_BASE_URL",
                                "base_url": "https://dashscope.example/v1",
                            },
                            "template": (
                                "qwen --bare --auth-type openai "
                                "--openai-base-url https://dashscope.example/v1 "
                                "--model {model_id} --approval-mode default "
                                "--exclude-tools read_file,write_file,edit,grep_search,glob,"
                                "run_shell_command,list_directory,agent "
                                "--max-tool-calls 1 "
                                "--json-schema @narrative_literary_ab_output.schema.json "
                                "--output-format stream-json"
                            ),
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            yaml.safe_dump(
                {
                    "models": {
                        "qwen3_7_max_dashscope": {
                            "provider": "dashscope_cn",
                            "model_id": "qwen3.7-max",
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "qwen",
            "invocation_contract": "qwen_narrative_literary_ab",
            "default": "qwen3_7_max_dashscope",
        }
        sealed_messages = [
            {"role": "system", "content": "No tools."},
            {"role": "user", "content": "Judge anonymous A/B."},
        ]
        _authorize_external_packet(
            plan,
            agent_name="Reviewer",
            cli_agent_name="qwen",
            sealed_messages=sealed_messages,
        )
        dimensions = {
            name: {
                "score": 4,
                "severity": "pass",
                "evidence": {
                    "chapter": 25,
                    "scene": "archive bargain",
                    "excerpt_or_locator": "middle decision exchange",
                },
                "reason": f"specific {name} evidence",
                "revision_target": "retain",
            }
            for name in LITERARY_EDITOR_DIMENSIONS
        }
        structured_result = {
            "schema_version": 1,
            "status": "completed",
            "pair_id": "gate1-ch25-pair",
            "anonymous_scorecards": {
                "A": {"status": "pass", "dimensions": dimensions},
                "B": {"status": "pass", "dimensions": dimensions},
            },
            "blind_review": {
                "preferred_version": "B",
                "preference_strength": "strong",
                "reason": "B has clearer causal pressure",
                "comparative_evidence": ["A locator", "B locator"],
            },
        }
        stdout = "\n".join(
            json.dumps(event)
            for event in [
                {"type": "system", "subtype": "init"},
                {
                    "type": "result",
                    "subtype": "success",
                    "result": structured_result,
                    "usage": {
                        "input_tokens": 2000,
                        "output_tokens": 500,
                        "total_tokens": 2500,
                    },
                },
            ]
        )
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            if argv[0] == "/usr/bin/openssl":
                return _REAL_SUBPROCESS_RUN(argv, **kwargs)
            observed["argv"] = list(argv)
            schema_path = Path(kwargs["cwd"]) / "narrative_literary_ab_output.schema.json"
            observed["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
            return self._mock_proc(0, stdout=stdout, stderr="")

        with patch.dict(
            "cli_executor.os.environ",
            {
                "DASHSCOPE_API_KEY": "private-test-key",
            },
            clear=False,
        ), patch(
            "cli_executor.shutil.which", return_value="/usr/bin/qwen"
        ), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(
                plan,
                "Reviewer",
                role_profile,
                sealed_messages=sealed_messages,
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        argv = observed["argv"]
        assert argv[argv.index("--model") + 1] == "qwen3.7-max"
        assert argv[argv.index("--json-schema") + 1] == (
            "@narrative_literary_ab_output.schema.json"
        )
        assert observed["schema"]["properties"]["anonymous_scorecards"][
            "required"
        ] == ["A", "B"]
        assert '"pair_id": "gate1-ch25-pair"' in result.content
        assert '"anonymous_scorecards"' in result.content
        assert '"type": "result"' not in result.content
        assert result.raw_usage["structured_output"] == "narrative_literary_ab"
        assert result.input_tokens == 2000
        assert result.output_tokens == 500


    def test_narrative_heavy_audit_structured_schema_requires_scribe_boundaries(
        self,
    ) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _narrative_heavy_audit_output_schema

        schema = _narrative_heavy_audit_output_schema("Scribe")

        assert "files" not in schema["properties"]
        assert set(schema["required"]) >= {
            "schema_version",
            "status",
            "candidate_only",
            "production_modified",
            "requires_user_promotion",
            "events",
        }
        assert schema["properties"]["candidate_only"] == {
            "enum": [True, "true"]
        }
        assert schema["properties"]["production_modified"] == {
            "enum": [False, "false"]
        }
        assert schema["properties"]["events"]["items"]["properties"][
            "scope"
        ] == {"const": "candidate_only"}

    def test_blocking_verifier_schema_requires_nonempty_direct_rewrite_proposal(
        self,
    ) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import (
            _narrative_heavy_audit_blocks_from_output,
            _narrative_heavy_audit_output_schema,
        )

        schema = _narrative_heavy_audit_output_schema(
            "Verifier",
            blocking_rewrite_required=True,
        )

        assert "files" not in schema["properties"]
        assert schema["properties"]["status"] == {"const": "proposed"}
        assert schema["properties"]["rewrite_required"] == {
            "enum": [True, "true"]
        }
        assert schema["properties"]["proposals"]["minItems"] == 1

        content = {
            "schema_version": "1",
            "candidate_only": "true",
            "production_modified": "false",
            "status": "proposed",
            "rewrite_required": "true",
            "direct_draft_edits": "false",
            "proposals": [{"issue_id": "C001", "action": "Rewrite chapter 58."}],
        }
        stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "structured_result": content,
            }
        )

        blocks = _narrative_heavy_audit_blocks_from_output(stdout, "Verifier")

        assert blocks is not None
        assert "<!-- AGENTLAB_EDIT: revision_or_rewrite_proposal.yml -->" in blocks
        assert "schema_version: 1" in blocks
        assert "candidate_only: true" in blocks
        assert "production_modified: false" in blocks
        assert "rewrite_required: true" in blocks
        assert "direct_draft_edits: false" in blocks
        assert "issue_id: C001" in blocks

    def test_observer_stages_only_manifested_multimodal_input_read_only(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        assigned_image = run_dir / "assigned.png"
        assigned_image.write_bytes(b"not-a-real-png-but-a-bounded-test-input")
        unrelated_image = run_dir / "unrelated.png"
        unrelated_image.write_bytes(b"must-not-be-staged")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            workspace = Path(kwargs["cwd"])
            packet = json.loads(
                (workspace / "task_packet_observer.json").read_text(encoding="utf-8")
            )
            staged = workspace / packet["observer_inputs"][0]["staged_path"]
            observed["packet"] = packet
            observed["staged_bytes"] = staged.read_bytes()
            observed["staged_mode"] = staged.stat().st_mode
            observed["files"] = sorted(
                str(path.relative_to(workspace))
                for path in workspace.rglob("*")
                if path.is_file()
            )
            return self._mock_proc(0, stdout="observation report", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(
                plan,
                "Observer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "inspect assigned input"}],
                outbound_source_paths=[assigned_image],
            )

        packet = observed["packet"]
        assert result.status == "completed"
        assert result.raw_usage["observer_input_count"] == 1
        assert packet["context_policy"]["read_scope"] == [
            "this_task_packet",
            "observer_inputs/*",
        ]
        assert packet["observer_inputs"][0]["source_filename"] == "assigned.png"
        assert len(packet["observer_inputs"][0]["sha256"]) == 64
        assert "_source_path" not in packet["observer_inputs"][0]
        assert observed["staged_bytes"] == assigned_image.read_bytes()
        assert observed["staged_mode"] & 0o222 == 0
        assert all("unrelated.png" not in path for path in observed["files"])

    def test_observer_blocks_if_staged_input_hash_changes_before_execution(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        assigned_image = run_dir / "assigned.png"
        assigned_image.write_bytes(b"original-assigned-input")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
        }

        def tampering_copy(_source, destination):
            Path(destination).write_bytes(b"changed-during-copy")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.shutil.copy2", side_effect=tampering_copy), \
             patch("cli_executor.subprocess.run") as process:
            result = run_cli_agent(
                plan,
                "Observer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "inspect assigned input"}],
                outbound_source_paths=[assigned_image],
            )

        process.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "observer_input_integrity_changed"
        assert result.raw_usage["provider_process_started"] is False

    def test_claude_json_usage_and_ultracode_environment_are_provider_reported(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        plan.included_agents["Writer"] = {
            "ultracode_opt_in": True,
            "writer_mode": "developmental_ultracode",
            "work_type": "revision_plan",
        }
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            """contracts:
  claude_writer_ultracode:
    opt_in_only: true
    requires_task_packet:
      ultracode_opt_in: true
      writer_mode: developmental_ultracode
      work_type: one_of_allowed_work
    allowed_work: [developmental_edit, structure, continuity, revision_plan]
    forbidden_work: [final_prose_draft]
    environment:
      unset: [CLAUDE_CODE_EFFORT_LEVEL]
    template: 'claude --model "{model_id}" --max-budget-usd 2.00 --permission-mode plan --output-format json -p "Read {task_packet_path}"'
""",
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            """models:
  deepseek_v4_pro:
    provider: deepseek_official
    model_id: deepseek-v4-pro
""",
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "invocation_contract": "claude_writer_ultracode",
            "default": "deepseek_v4_pro",
        }
        provider_payload = {
            "type": "result",
            "result": "writer revision plan",
            "session_id": "session-test",
            "total_cost_usd": 0.125,
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 7,
                "output_tokens": 20,
            },
            "modelUsage": {"deepseek-v4-pro": {"outputTokens": 20}},
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            observed["env"] = kwargs["env"]
            return self._mock_proc(0, stdout=json.dumps(provider_payload), stderr="")

        with patch.dict("cli_executor.os.environ", {"CLAUDE_CODE_EFFORT_LEVEL": "max"}), \
             patch("cli_executor.shutil.which", return_value="/usr/bin/claude"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "bounded context"}],
            )

        assert result.status == "completed"
        assert "writer revision plan" in result.content
        assert "CLAUDE_CODE_EFFORT_LEVEL" not in observed["env"]
        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.total_tokens == 137
        assert result.raw_usage["cache_creation_input_tokens"] == 10
        assert result.raw_usage["cache_read_input_tokens"] == 7
        assert result.raw_usage["estimated_cost"] == 0.125
        assert result.raw_usage["exact_cost_available"] is True
        assert result.raw_usage["pricing_source"] == "provider_response"
        assert result.raw_usage["provider_reported_model_ids"] == ["deepseek-v4-pro"]
        assert result.raw_usage["contract_environment_unset"] == [
            "CLAUDE_CODE_EFFORT_LEVEL"
        ]
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        assert receipt_path.name.startswith(
            "model_execution_receipt_writer_direct_"
        )
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "pass"
        assert receipt["role"] == "Writer"
        assert receipt["worker"] == "claude_code"
        assert receipt["selected_provider"] == "deepseek"
        assert receipt["selected_model_key"] == "deepseek_v4_pro"
        assert receipt["selected_model_id"] == "deepseek-v4-pro"
        assert receipt["provider_response_metadata_observed"] is True
        assert receipt["provider_reported_model_ids"] == ["deepseek-v4-pro"]
        assert receipt["provider_reported_session_id"] == "session-test"
        assert receipt["provider_model_binding_verified"] is True
        assert receipt["provider_reported_usage"]["input_tokens"] == 100
        assert receipt["provider_reported_usage"]["estimated_cost"] == 0.125
        assert receipt["fallback_detected"] is False

    @pytest.mark.parametrize(
        ("reported_model", "expected_status", "binding_verified"),
        [
            ("deepseek-v4-pro", "completed", True),
            ("unexpected-provider-model", "blocked_user_decision", False),
        ],
    )
    def test_claude_writer_runtime_receipt_distinguishes_selected_and_observed_model(
        self,
        tmp_path,
        reported_model,
        expected_status,
        binding_verified,
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            """contracts:
  claude_writer:
    template: 'claude --model "{model_id}" --effort max --max-budget-usd 1.00 --permission-mode bypassPermissions --output-format json --tools "" -p "Read {task_packet_path}"'
""",
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            """models:
  deepseek_v4_pro:
    provider: deepseek_official
    model_id: deepseek-v4-pro
""",
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "invocation_contract": "claude_writer",
            "default": "deepseek_v4_pro",
            "capacity_selected_route": "WriterPro",
            "capacity_pool": "claude_deepseek_writer",
        }
        provider_payload = {
            "type": "result",
            "result": "writer candidate envelopes",
            "session_id": "writer-session",
            "usage": {"input_tokens": 40, "output_tokens": 10},
            "modelUsage": {reported_model: {"outputTokens": 10}},
        }

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/claude"
        ), patch(
            "cli_executor.subprocess.run",
            return_value=self._mock_proc(
                0,
                stdout=json.dumps(provider_payload),
                stderr="",
            ),
        ):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[{"role": "user", "content": "bounded draft"}],
            )

        assert result.status == expected_status
        receipt_path = Path(result.raw_usage["model_execution_receipt"])
        assert receipt_path.name.startswith(
            "model_execution_receipt_writer_writerpro_"
        )
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["selected_model_id"] == "deepseek-v4-pro"
        assert receipt["provider_reported_model_ids"] == [reported_model]
        assert receipt["provider_reported_session_id"] == "writer-session"
        assert receipt["provider_response_metadata_observed"] is True
        assert receipt["provider_model_binding_verified"] is binding_verified
        assert receipt["fallback_detected"] is (not binding_verified)
        if binding_verified:
            assert receipt["status"] == "pass"
            assert "writer candidate envelopes" in result.content
        else:
            assert receipt["status"] == "fail"
            assert result.raw_usage["failure_class"] == "model_unavailable"
            assert "provider_reported_model_mismatch" in receipt["issues"]

    def test_real_claude_writer_contract_delivers_sealed_packet_on_stdin(
        self,
        tmp_path,
    ):
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        repository_root = Path(__file__).parent.parent
        real_contracts = yaml.safe_load(
            (repository_root / "config" / "worker_invocation_contracts.yml").read_text(
                encoding="utf-8"
            )
        )
        writer_contract = real_contracts["contracts"]["claude_writer"]
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {"contracts": {"claude_writer": writer_contract}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            """models:
  deepseek_v4_pro:
    provider: deepseek_official
    model_id: deepseek-v4-pro
""",
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "invocation_contract": "claude_writer",
            "default": "deepseek_v4_pro",
            "capacity_selected_route": "Writer",
            "capacity_pool": "deepseek_metered_api",
        }
        provider_payload = {
            "type": "result",
            "result": "writer candidate envelopes",
            "session_id": "writer-stdin-session",
            "usage": {"input_tokens": 40, "output_tokens": 10},
            "modelUsage": {"deepseek-v4-pro": {"outputTokens": 10}},
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            observed["argv"] = list(argv)
            observed["kwargs"] = dict(kwargs)
            return self._mock_proc(
                0,
                stdout=json.dumps(provider_payload),
                stderr="",
            )

        with patch(
            "cli_executor.shutil.which",
            return_value="/usr/bin/claude",
        ), patch(
            "cli_executor.subprocess.run",
            side_effect=fake_run,
        ):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[
                    {"role": "user", "content": "bounded chapter context"}
                ],
            )

        assert result.status == "completed"
        kwargs = observed["kwargs"]
        assert "stdin" not in kwargs
        packet_text = kwargs["input"]
        packet = json.loads(packet_text)
        assert packet["packet_type"] == "agentlab_sealed_role_session"
        assert packet["messages"] == [
            {"role": "user", "content": "bounded chapter context"}
        ]
        argv = observed["argv"]
        assert not any("task_packet_writer.json" in arg for arg in argv)
        assert result.raw_usage["sealed_packet_stdin"] is True

    def test_real_agy_writer_contract_delivers_sealed_packet_on_stdin(
        self,
        tmp_path,
    ):
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        repository_root = Path(__file__).parent.parent
        real_contracts = yaml.safe_load(
            (repository_root / "config" / "worker_invocation_contracts.yml").read_text(
                encoding="utf-8"
            )
        )
        writer_contract = real_contracts["contracts"]["agy_writer"]
        (config_dir / "worker_invocation_contracts.yml").write_text(
            yaml.safe_dump(
                {"contracts": {"agy_writer": writer_contract}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            """models:
  gemini_writer:
    provider: agy_gemini_oauth
    runtime_provider: agy-gemini-oauth
    model_id: gemini-3.5-flash-high
    cli_model_id: gemini-3.5-flash-high
""",
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "invocation_contract": "agy_writer",
            "default": "gemini_writer",
            "capacity_selected_route": "WriterAgy",
            "capacity_pool": "agy_gemini_observer",
        }
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            observed["argv"] = list(argv)
            observed["kwargs"] = dict(kwargs)
            return self._mock_proc(
                0,
                stdout="AGENTLAB_EDIT fiction_draft.md\nbounded prose\nAGENTLAB_END_EDIT\n",
                stderr="",
            )

        with patch(
            "cli_executor.shutil.which",
            return_value="/usr/local/bin/agy",
        ), patch(
            "cli_executor.subprocess.run",
            side_effect=fake_run,
        ):
            result = run_cli_agent(
                plan,
                "Writer",
                role_profile,
                sealed_messages=[
                    {"role": "user", "content": "bounded chapter context"}
                ],
            )

        assert result.status == "completed"
        kwargs = observed["kwargs"]
        packet = json.loads(kwargs["input"])
        assert packet["packet_type"] == "agentlab_sealed_role_session"
        assert packet["messages"] == [
            {"role": "user", "content": "bounded chapter context"}
        ]
        assert observed["argv"][:4] == [
            "agy",
            "--sandbox",
            "--model",
            "gemini-3.5-flash-high",
        ]
        assert result.raw_usage["sealed_packet_stdin"] is True
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["worker"] == "agy"
        assert receipt["invocation_contract"] == "agy_writer"
        assert receipt["command_binding_verified"] is True

    def test_claude_supervisor_fallback_writes_approved_fallback_chain(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "worker_invocation_contracts.yml").write_text(
            """contracts:
  claude_supervisor_fallback:
    template: 'claude --model "{model_id}" --effort max --max-budget-usd 1.00 --permission-mode plan --output-format json --tools "" -p "Read {task_packet_path}"'
""",
            encoding="utf-8",
        )
        (config_dir / "model_catalog.yml").write_text(
            """models:
  deepseek_v4_pro:
    provider: deepseek_official
    model_id: deepseek-v4-pro
""",
            encoding="utf-8",
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "invocation_contract": "claude_supervisor_fallback",
            "default": "deepseek_v4_pro",
            "capacity_selected_route": "SupervisorDeepSeek",
            "capacity_pool": "claude_deepseek_supervisor",
            "capacity_attempt_id": "task:Supervisor:fallback",
            "capacity_selection_kind": "approved_fallback",
        }
        payload = {
            "result": "governed fallback plan",
            "session_id": "supervisor-fallback-session",
            "usage": {"input_tokens": 20, "output_tokens": 5},
            "modelUsage": {"deepseek-v4-pro": {"outputTokens": 5}},
        }

        with patch(
            "cli_executor.shutil.which", return_value="/usr/bin/claude"
        ), patch(
            "cli_executor.subprocess.run",
            return_value=self._mock_proc(0, stdout=json.dumps(payload)),
        ):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["role"] == "Supervisor"
        assert receipt["selection_kind"] == "approved_fallback"
        assert receipt["fallback_detected"] is True
        assert receipt["provider_model_binding_verified"] is True
        chain = yaml.safe_load(
            (run_dir / "model_execution_chain_supervisor.yml").read_text(
                encoding="utf-8"
            )
        )
        assert chain["fallback_used"] is True
        assert chain["final"]["capacity_route"] == "SupervisorDeepSeek"
        assert chain["final"]["provider"] == "deepseek"
        assert chain["final"]["model"] == "deepseek-v4-pro"

    def test_production_pack_cli_blocks_before_subprocess_without_scoped_approval(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }

        with patch.dict(
            "os.environ",
            {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "0"},
            clear=False,
        ), patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), patch(
            "cli_executor.subprocess.run"
        ) as subprocess_run:
            result = run_cli_agent(
                plan,
                "ArtifactProducer",
                role_profile,
                task_messages=[
                    {"role": "user", "content": "Return candidate YAML blocks."}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "blocked_user_decision"
        assert result.error == "artifactproducer_outbound_context_gate_blocked"
        subprocess_run.assert_not_called()
        assert not (run_dir / "task_packet_artifactproducer.json").exists()
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_artifactproducer.yml").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "pending_approval"
        assert manifest["authorization"]["approval_env_name"] == (
            PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
        )

    def test_approved_production_pack_cli_is_packet_only_and_isolated(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        task_messages = [
            {"role": "user", "content": "Return candidate YAML blocks."}
        ]
        _authorize_external_packet(
            plan,
            agent_name="ArtifactProducer",
            cli_agent_name="agy",
            task_messages=task_messages,
        )
        observed: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            if argv[0] == "/usr/bin/openssl":
                return _REAL_SUBPROCESS_RUN(argv, **kwargs)
            packet_path = Path(kwargs["cwd"]) / "task_packet_artifactproducer.json"
            observed["packet"] = json.loads(
                packet_path.read_text(encoding="utf-8")
            )
            observed["workspace"] = Path(kwargs["cwd"])
            return self._mock_proc(0, stdout="candidate blocks", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), patch(
            "cli_executor.subprocess.run", side_effect=fake_run
        ):
            result = run_cli_agent(
                plan,
                "ArtifactProducer",
                role_profile,
                task_messages=task_messages,
                outbound_source_paths=[source],
            )

        assert result.status == "completed"
        assert result.raw_usage["sealed_context"] is True
        assert result.raw_usage["execution_workspace_isolated"] is True
        assert observed["workspace"] != Path(plan.agentlab_root)
        packet = observed["packet"]
        assert isinstance(packet, dict)
        assert packet["packet_type"] == "agentlab_production_pack_role_session"
        assert packet["context_policy"]["read_scope"] == ["this_task_packet"]
        assert "agentlab_root" not in packet
        assert not Path(observed["workspace"]).exists()
        manifest = yaml.safe_load(
            (run_dir / "outbound_context_manifest_artifactproducer.yml").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "pass"
        assert manifest["payload"]["kind"] == (
            "production_pack_cli_role_session_packet"
        )
        assert manifest["source_inventory"]["count"] == 1

    def test_production_pack_cli_blocks_secret_even_with_approval(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent
        from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        source = run_dir / "domain_research_brief.md"
        source.write_text("# Domain research\n", encoding="utf-8")
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read only {task_packet_path}"',
        }
        secret = "sk-" + ("a" * 40)

        with patch.dict(
            "os.environ",
            {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "1"},
            clear=False,
        ), patch("cli_executor.subprocess.run") as subprocess_run:
            result = run_cli_agent(
                plan,
                "Verifier",
                role_profile,
                task_messages=[
                    {"role": "user", "content": f"credential: {secret}"}
                ],
                outbound_source_paths=[source],
            )

        assert result.status == "blocked_user_decision"
        subprocess_run.assert_not_called()
        manifest_text = (
            run_dir / "outbound_context_manifest_verifier.yml"
        ).read_text(encoding="utf-8")
        assert "secret_pattern_detected" in manifest_text
        assert secret not in manifest_text

    def test_completed_uses_reported_usage_sidecar(self, tmp_path):
        import json
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        run_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"
        run_dir.mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "task {task_packet_path}"',
            "default": "deepseek_v4_pro",
        }
        mock_proc = self._mock_proc(0, stdout="# Supervisor Report\n\nAll good.")

        def _write_usage(*args, **kwargs):
            (run_dir / "usage_supervisor.json").write_text(
                json.dumps({
                    "agentlab_usage": {
                        "input_tokens": 111,
                        "output_tokens": 22,
                        "total_tokens": 133,
                        "estimated_cost": 0.0042,
                        "currency": "USD",
                    }
                }),
                encoding="utf-8",
            )
            return mock_proc

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=_write_usage):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.input_tokens == 111
        assert result.output_tokens == 22
        assert result.total_tokens == 133
        assert result.raw_usage["usage_source"] == "external_cli_reported"
        assert result.raw_usage["exact_usage_available"] is True
        assert result.raw_usage["estimated_cost"] == 0.0042

    def test_blocked_on_nonzero_exit(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        mock_proc = self._mock_proc(1, stdout="", stderr="fatal error")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.error is not None

    def test_auth_failure_is_classified_without_raw_stderr_in_decision_reason(
        self, tmp_path
    ):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(
            parents=True, exist_ok=True
        )
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
        }
        stderr = "Authentication required. You are not logged into Antigravity."
        mock_proc = self._mock_proc(1, stdout="", stderr=stderr)

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "ArtifactProducer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.raw_usage["failure_class"] == "auth_required"
        assert result.error == "CLI agent auth_required (exit 1)."
        assert stderr not in result.error

    def test_blocked_on_timeout(self, tmp_path):
        import subprocess
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=600)):
            result = run_cli_agent(plan, "Supervisor", role_profile, timeout=600)

        assert result.status == "blocked_user_decision"
        assert "timeout" in result.content.lower() or "timed out" in result.error.lower()

    def test_exit_127_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        }

        mock_proc = self._mock_proc(127, stdout="", stderr="hermes: command not found")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)

    def test_argparse_usage_error_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": "hermes --task {task_packet_path}",
        }

        mock_proc = self._mock_proc(
            2,
            stdout="",
            stderr="usage: hermes [-h] [-z PROMPT] ...\nhermes: error: unrecognized arguments: --task",
        )

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "invalid_cli_invocation"

    def test_raw_usage_contains_metadata(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "cli_command": "claude --task {task_packet_path}",
        }

        mock_proc = self._mock_proc(0, stdout="# Coder Report\n\nDone.")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/claude"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc):
            result = run_cli_agent(plan, "Coder", role_profile)

        assert "cli_agent" in result.raw_usage
        assert result.raw_usage["exit_code"] == 0
        assert "task_packet_path" in result.raw_usage


# ---------------------------------------------------------------------------
# Missing cli_agent / cli_command fields
# ---------------------------------------------------------------------------

class TestRunCliAgentMissingConfig:
    def test_missing_cli_command_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            # cli_command deliberately missing
        }

        result = run_cli_agent(plan, "Supervisor", role_profile)
        assert isinstance(result, CliAgentNotAvailable)

    def test_unrenderable_invocation_contract_returns_not_available(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config" / "worker_invocation_contracts.yml").write_text(
            """
contracts:
  agy:
    template: 'agy --sandbox -p "Read {frontdesk_session_path}"'
""",
            encoding="utf-8",
        )

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "invocation_contract": "agy",
        }

        result = run_cli_agent(plan, "RepoScout", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "invalid_cli_template"
        assert "frontdesk_session_path" in result.detail


# ---------------------------------------------------------------------------
# _resolve_binary_candidate unit tests
# ---------------------------------------------------------------------------

class TestResolveBinaryCandidate:
    def test_returns_first_available(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": None,
            "ccs": "/usr/bin/ccs",
            "other": "/usr/bin/other",
        }.get(x)):
            result = _resolve_binary_candidate(["claude", "ccs", "other"])
            assert result == "ccs"

    def test_returns_none_when_none_available(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        with patch("cli_executor.shutil.which", return_value=None):
            result = _resolve_binary_candidate(["claude", "ccs"])
            assert result is None

    def test_empty_candidates_returns_none(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import _resolve_binary_candidate

        result = _resolve_binary_candidate([])
        assert result is None


# ---------------------------------------------------------------------------
# binary_candidates resolution in run_cli_agent
# ---------------------------------------------------------------------------

class TestBinaryCandidateResolution:
    """Tests for binary_candidates field in role profiles."""

    def _mock_proc(self, returncode: int, stdout: str = "", stderr: str = ""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_canonical_claude_resolved_first(self, tmp_path):
        """When claude is available, argv[0] is claude, not ccs."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done")

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": "/usr/local/bin/claude",
            "ccs": "/usr/local/bin/ccs",
        }.get(x)), patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Coder", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "claude"
        assert result.raw_usage.get("binary") == "claude"
        assert result.raw_usage.get("binary_candidate_used") == "claude"

    def test_legacy_ccs_fallback_when_claude_absent(self, tmp_path):
        """When claude is missing but ccs exists, fall back to ccs."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done via ccs")

        with patch("cli_executor.shutil.which", side_effect=lambda x: {
            "claude": None,
            "ccs": "/usr/local/bin/ccs",
        }.get(x)), patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Coder", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "ccs"
        assert result.raw_usage.get("binary") == "ccs"
        assert result.raw_usage.get("binary_candidate_used") == "ccs"

    def test_no_candidates_available_returns_not_available(self, tmp_path):
        """When neither claude nor ccs is found, return CliAgentNotAvailable."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import CliAgentNotAvailable, run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "claude_code",
            "binary_candidates": ["claude", "ccs"],
            "cli_command": 'claude -p "Read {task_packet_path}" --output-format json',
            "default": "qwen3_coder_plus_dashscope",
        }

        with patch("cli_executor.shutil.which", return_value=None):
            result = run_cli_agent(plan, "Coder", role_profile)

        assert isinstance(result, CliAgentNotAvailable)
        assert result.reason == "binary_not_found"
        assert "claude" in result.detail
        assert "ccs" in result.detail

    def test_hermes_unaffected_by_candidates(self, tmp_path):
        """Hermes roles with no binary_candidates still work as before."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "hermes",
            "cli_command": 'hermes -z "test"',
            "default": "deepseek_v4_pro",
        }

        mock_proc = self._mock_proc(0, stdout="# Supervisor Report")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/hermes"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Supervisor", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "hermes"
        assert "binary_candidate_used" not in result.raw_usage

    def test_agy_unaffected_by_candidates(self, tmp_path):
        """Agy roles with no binary_candidates still work as before."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "test"',
            "default": "qwen3_6_plus_dashscope",
        }

        mock_proc = self._mock_proc(0, stdout="# Done")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_cli_agent(plan, "Reposcout", role_profile)

        assert result.status == "completed"
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "agy"
        assert "--log-file" in called_argv
        log_path = Path(called_argv[called_argv.index("--log-file") + 1])
        assert log_path.name.startswith("agy_cli_agent_")
        assert log_path.suffix == ".log"
        assert log_path.parent.name == "command_logs"
        assert result.raw_usage.get("cli_log_path") == str(log_path)
        assert "binary_candidate_used" not in result.raw_usage

    def test_agy_empty_stderr_uses_cli_log_excerpt(self, tmp_path):
        """Agy can fail before stderr is wired; capture its local log as evidence."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        (tmp_path / "projects" / "TestProject" / "runs" / "task_test_001").mkdir(parents=True, exist_ok=True)

        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --sandbox -p "test"',
            "default": "qwen3_6_plus_dashscope",
        }

        def fake_run(argv, **_kwargs):
            log_path = Path(argv[argv.index("--log-file") + 1])
            log_path.write_text(
                "CLI failed to start - listen tcp 127.0.0.1:0: bind: operation not permitted",
                encoding="utf-8",
            )
            return self._mock_proc(1, stdout="", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(plan, "Writer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.error is not None
        assert result.error == "CLI agent permission_denied (exit 1)."
        assert "listen tcp 127.0.0.1:0" not in result.error
        assert result.raw_usage["failure_class"] == "permission_denied"
        assert "agy_cli_agent_" in result.content
        assert Path(result.raw_usage.get("cli_log_path", "")).name.startswith(
            "agy_cli_agent_"
        )

    def test_agy_unrecognized_model_cannot_silently_fallback(self, tmp_path):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent_runtime"))
        from cli_executor import run_cli_agent

        plan = _make_plan(tmp_path)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        role_profile = {
            "executor_type": "cli_agent",
            "cli_agent": "agy",
            "cli_command": 'agy --model "Unknown Model" -p "test"',
            "default": "unknown_model",
        }

        def fake_run(argv, **_kwargs):
            log_path = Path(argv[argv.index("--log-file") + 1])
            log_path.write_text(
                "Failed to resolve model flag Unknown Model: model is not recognized as a known model",
                encoding="utf-8",
            )
            return self._mock_proc(0, stdout="AGENTLAB_AGY_CLI_SMOKE_OK", stderr="")

        with patch("cli_executor.shutil.which", return_value="/usr/bin/agy"), \
             patch("cli_executor.subprocess.run", side_effect=fake_run):
            result = run_cli_agent(plan, "Writer", role_profile)

        assert result.status == "blocked_user_decision"
        assert result.error == "CLI agent model_unavailable (exit 0)."
        assert result.raw_usage["failure_class"] == "model_unavailable"
        assert result.raw_usage["model_resolution_failed"] is True
        assert "blocked its silent default-model substitution" in result.content
        receipt = yaml.safe_load(
            Path(result.raw_usage["model_execution_receipt"]).read_text(
                encoding="utf-8"
            )
        )
        assert receipt["status"] == "fail"
        assert receipt["fallback_detected"] is True
        assert receipt["provider_response_metadata_observed"] is False
        assert "model_resolution_fallback_detected" in receipt["issues"]
