from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from agent_runtime.media_backend_adapter import (
    build_grok_cli_payload_plan,
    build_xai_payload_plan,
    execute_media_contract,
    preflight_media_contract,
    validate_media_live_role_session,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _contract() -> dict:
    return {
        "schema_version": 1,
        "contract_type": "media_generation_contract",
        "project_id": "Crown_of_Ash",
        "task_id": "task_media_adapter",
        "modality": "image",
        "prompt": "Generate image: a cinematic Crown of Ash poster.",
        "selected_backend": "grok_direct",
        "delivery_constraints": {"aspect_ratio": "16:9"},
    }


def _oauth_contract() -> dict:
    contract = _contract()
    contract["selected_backend"] = "hermes_grok_oauth"
    return contract


def _artifact_role_session(contract: dict | None = None) -> dict:
    contract = contract or _contract()
    return {
        "packet_type": "agentlab_role_session",
        "schema_version": 1,
        "role": "ArtifactProducer",
        "worker": "agy",
        "binding": {"allowed": True, "reason": "role binding allowed"},
        "project": contract.get("project_id"),
        "task_id": contract.get("task_id"),
    }


def test_preflight_blocks_grok_direct_without_xai_key() -> None:
    with patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False):
        report = preflight_media_contract(_contract(), ROOT)

    assert report["status"] == "blocked"
    assert report["block_reason"] == "missing_auth"
    assert report["adapter_kind"] == "xai_imagine_rest"
    assert report["api_key_configured"] is False
    auth_check = next(check for check in report["checks"] if check["id"] == "auth_secret_present")
    assert auth_check["accepted_env"] == ["XAI_API_KEY", "GROK_API_KEY"]


def test_preflight_blocks_grok_direct_with_xai_key_until_explicit_approval() -> None:
    with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}, clear=False):
        report = preflight_media_contract(_contract(), ROOT)

    assert report["status"] == "blocked"
    assert report["block_reason"] == "approval_required"
    assert report["executable"] is False
    assert report["api_key_configured"] is True
    assert report["backend"]["fallback_only"] is True
    assert report["backend"]["approval_required"] is True
    auth_check = next(check for check in report["checks"] if check["id"] == "auth_secret_present")
    assert auth_check["accepted_env"] == ["XAI_API_KEY", "GROK_API_KEY"]


def test_preflight_blocks_grok_direct_with_grok_key_alias_until_explicit_approval() -> None:
    with patch.dict(os.environ, {"XAI_API_KEY": "", "GROK_API_KEY": "test-key"}, clear=False):
        report = preflight_media_contract(_contract(), ROOT)

    assert report["status"] == "blocked"
    assert report["block_reason"] == "approval_required"
    assert report["api_key_configured"] is True


def test_preflight_allows_local_grok_cli_without_api_key() -> None:
    report = preflight_media_contract(_oauth_contract(), ROOT)

    assert report["status"] == "ready"
    assert report["adapter_kind"] == "local_grok_cli"
    assert report["api_key_configured"] is False
    assert "block_reason" not in report
    assert "api_key_env" not in report
    assert report["backend"]["execution_kernel"] == "hermes_workflow_shell"
    assert report["backend"]["orchestration_scope"] == "bounded_role_session_backend"
    assert report["backend"]["workflow_shell_registry"] == "config/cli_workflow_shells.yml"
    assert "structured_output_and_qc" in report["backend"]["workflow_shell_capability_families"]
    local_cli_check = next(check for check in report["checks"] if check["id"] == "local_cli_available")
    assert local_cli_check["command"] == "hermes"


def test_local_grok_cli_execution_writes_text_handoff_not_media_asset(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        assert args[:5] == ["hermes", "--ignore-rules", "--provider", "xai-oauth", "-m"]
        assert "-z" in args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="GROK_CLI_SMOKE_OK\n", stderr="")

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=fake_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "completed_text_handoff"
    assert result["execution_scope"] == "internal_local_cli_worker"
    assert result["generated_assets"] == []
    assert result["artifact_generation_verified"] is False
    response = tmp_path / "grok_cli_response.md"
    assert response.read_text(encoding="utf-8").strip() == "GROK_CLI_SMOKE_OK"
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["text_artifacts"] == [str(response)]
    assert ledger["generated_assets"] == []
    assert ledger["artifact_generation_verified"] is False


def test_local_grok_cli_execution_collects_reported_assets_under_out_dir(tmp_path: Path) -> None:
    asset = tmp_path / "poster.png"

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        prompt = args[args.index("-z") + 1] if "-z" in args else args[args.index("-p") + 1]
        assert "AGENTLAB_GENERATED_ASSET:" in prompt
        assert str(tmp_path) in prompt
        asset.write_bytes(b"fake-png")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="done\nAGENTLAB_GENERATED_ASSET: poster.png\n",
            stderr="",
        )

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=fake_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "completed"
    assert result["generated_assets"] == [str(asset.resolve())]
    assert result["artifact_generation_verified"] is True
    assert result["asset_claims"] == ["poster.png"]
    assert result["asset_claims_rejected"] == []
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["status"] == "completed"
    assert ledger["generated_assets"] == [str(asset.resolve())]
    assert ledger["artifact_generation_verified"] is True
    assert ledger["asset_return_contract"]["marker"] == "AGENTLAB_GENERATED_ASSET:"
    manifest = yaml.safe_load((tmp_path / "outbound_context_manifest_media.yml").read_text(encoding="utf-8"))
    assert manifest["status"] == "pass"
    assert manifest["payload"]["secret_pattern_hit_count"] == 0
    assert len(manifest["payload"]["sha256"]) == 64


def test_local_grok_cli_secret_gate_blocks_before_command(tmp_path: Path) -> None:
    contract = _oauth_contract()
    secret = "sk-" + ("b" * 40)
    contract["prompt"] = f"Generate a poster with credential: {secret}"
    calls: list[list[str]] = []

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="unexpected", stderr="")

    result = execute_media_contract(
        contract,
        ROOT,
        tmp_path,
        live=True,
        command_runner=fake_runner,
        role_session=_artifact_role_session(contract),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "media_outbound_context_gate_blocked"
    assert calls == []
    manifest = yaml.safe_load((tmp_path / "outbound_context_manifest_media.yml").read_text(encoding="utf-8"))
    assert manifest["status"] == "blocked"
    assert secret not in yaml.safe_dump(manifest, sort_keys=False)


def test_local_grok_cli_timeout_writes_generation_ledger(tmp_path: Path) -> None:
    def timeout_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, timeout, output=b"partial stdout", stderr=b"partial stderr")

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=timeout_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "local_cli_timeout"
    assert result["reason"] == "grok_cli_timeout"
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["status"] == "local_cli_timeout"
    assert ledger["block_reason"] == "grok_cli_timeout"
    assert ledger["timeout_seconds"] == 60
    assert ledger["stdout_excerpt"] == "partial stdout"
    assert ledger["stderr_excerpt"] == "partial stderr"
    assert ledger["settings_fetch_failed"] is False


def test_local_grok_cli_timeout_classifies_settings_fetch_failure(tmp_path: Path) -> None:
    def timeout_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            args,
            timeout,
            output=b"",
            stderr=b"ERROR Settings fetch failed after 3 attempts",
        )

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=timeout_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "local_cli_timeout"
    assert result["reason"] == "grok_cli_settings_fetch_failed"
    assert result["settings_fetch_failed"] is True
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["block_reason"] == "grok_cli_settings_fetch_failed"
    assert ledger["settings_fetch_failed"] is True


def test_local_grok_cli_nonzero_classifies_settings_fetch_failure(tmp_path: Path) -> None:
    def failed_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="ERROR Settings fetch failed after 3 attempts",
        )

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=failed_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "local_cli_error"
    assert result["reason"] == "grok_cli_settings_fetch_failed"
    assert result["settings_fetch_failed"] is True
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["block_reason"] == "grok_cli_settings_fetch_failed"
    assert ledger["settings_fetch_failed"] is True


def test_local_grok_cli_nonzero_classifies_transport_failure(tmp_path: Path) -> None:
    def failed_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr=(
                "ERROR Settings fetch failed after 3 attempts\n"
                "request error: error sending request for url (https://cli-chat-proxy.grok.com/v1/responses)"
            ),
        )

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=failed_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "local_cli_error"
    assert result["reason"] == "grok_cli_transport_or_proxy_failed"
    assert result["failure_scope"] == "local_grok_network_or_proxy"
    assert result["settings_fetch_failed"] is True
    assert result["transport_failure_marker_present"] is True
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["block_reason"] == "grok_cli_transport_or_proxy_failed"
    assert ledger["failure_scope"] == "local_grok_network_or_proxy"
    assert ledger["settings_fetch_failed"] is True
    assert ledger["transport_failure_marker_present"] is True


def test_local_grok_cli_successful_exit_with_connection_error_is_not_text_handoff(tmp_path: Path) -> None:
    def failed_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="API call failed after 3 retries: Connection error.\n",
            stderr="",
        )

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=failed_runner,
        role_session=_artifact_role_session(_oauth_contract()),
    )

    assert result["status"] == "local_cli_error"
    assert result["reason"] == "grok_cli_transport_or_proxy_failed"
    assert result["failure_scope"] == "local_grok_network_or_proxy"
    assert result["artifact_generation_verified"] is False
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["status"] == "local_cli_error"
    assert ledger["block_reason"] == "grok_cli_transport_or_proxy_failed"
    assert ledger["transport_failure_marker_present"] is True
    assert ledger["generated_assets"] == []


def test_live_media_execution_blocks_without_artifact_producer_role_session(tmp_path: Path) -> None:
    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        raise AssertionError("live backend should not be called without role-session evidence")

    result = execute_media_contract(
        _oauth_contract(),
        ROOT,
        tmp_path,
        live=True,
        command_runner=fake_runner,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "missing_role_session"
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["status"] == "blocked"


def test_media_backend_execute_cli_generates_role_session_from_worker(tmp_path: Path) -> None:
    contract_path = tmp_path / "media_generation_contract.yml"
    contract_path.write_text(yaml.safe_dump(_contract(), sort_keys=False), encoding="utf-8")
    out_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "media-backend-execute",
            "--contract",
            str(contract_path),
            "--out-dir",
            str(out_dir),
            "--live",
            "--role",
            "ArtifactProducer",
            "--worker",
            "agy",
            "--project",
            "Crown_of_Ash",
            "--run-id",
            "task_media_adapter",
        ],
        env={"XAI_API_KEY": "", "GROK_API_KEY": ""},
    )

    assert result.exit_code == 0
    response = yaml.safe_load(result.output)
    assert response["status"] == "blocked"
    assert response["reason"] == "missing_auth"
    assert response["reason"] != "missing_role_session"


def test_media_live_role_session_validation_rejects_frontdesk_packet() -> None:
    result = validate_media_live_role_session(
        _oauth_contract(),
        {
            "packet_type": "agentlab_frontdesk_session",
            "role": "frontdesk",
            "binding": {"allowed": True},
        },
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "invalid_role_session"
    assert "role-session" in result["message"]


def test_build_grok_cli_payload_plan_records_no_media_artifact_claim() -> None:
    backend = preflight_media_contract(_oauth_contract(), ROOT)["backend"]
    plan = build_grok_cli_payload_plan(_oauth_contract(), backend)

    assert plan["adapter_kind"] == "local_grok_cli"
    assert plan["command"] == "hermes"
    assert plan["args"][:5] == ["hermes", "--ignore-rules", "--provider", "xai-oauth", "-m"]
    assert "grok-build-0.1" in plan["args"]
    assert "-z" in plan["args"]
    assert "--oauth" not in plan["args"]
    assert plan["artifact_generation_verified"] is False
    assert plan["artifact_return_contract"]["marker"] == "AGENTLAB_GENERATED_ASSET:"
    assert plan["artifact_return_contract"]["text_handoff_is_not_media_artifact"] is True
    assert plan["auth_mode"] == "local_authenticated_cli_session"


def test_literal_private_api_key_is_not_written_to_preflight_but_executes(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "media_generation_backends.yml").write_text(
        """
backends:
  grok_direct:
    display_name: Grok Direct
    adapter_state: configured
    adapter_kind: xai_imagine_rest
    api_key: literal-test-key
    base_url: https://api.x.ai/v1
    endpoints:
      image_generation: /images/generations
    models:
      image: grok-imagine-image-quality
    approval_required: false
""",
        encoding="utf-8",
    )

    report = preflight_media_contract(_contract(), root)

    assert report["status"] == "ready"
    assert report["api_key_configured"] is True
    assert "api_key" not in report["backend"]

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int) -> dict:
        assert headers["Authorization"] == "Bearer literal-test-key"
        return {"data": [{"b64_json": "ZmFrZS1wbmc="}]}

    result = execute_media_contract(
        _contract(),
        root,
        tmp_path / "out",
        live=True,
        http_post=fake_post,
        role_session=_artifact_role_session(_contract()),
    )

    assert result["status"] == "completed"


def test_dry_run_writes_preflight_payload_and_generation_ledger(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False):
        result = execute_media_contract(_contract(), ROOT, tmp_path, live=False)

    assert result["status"] == "dry_run"
    assert (tmp_path / "media_backend_preflight.yml").exists()
    assert (tmp_path / "media_backend_payload_plan.yml").exists()
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["live"] is False
    assert ledger["status"] == "dry_run"
    assert ledger["generated_assets"] == []


def test_build_xai_payload_plan_uses_imagine_image_endpoint() -> None:
    backend = preflight_media_contract(_contract(), ROOT)["backend"]
    plan = build_xai_payload_plan(_contract(), backend)

    assert plan["adapter_kind"] == "xai_imagine_rest"
    assert plan["endpoint"].endswith("/images/generations")
    assert plan["payload"]["model"] == "grok-imagine-image-quality"
    assert plan["payload"]["aspect_ratio"] == "16:9"


def test_live_image_execution_with_stubbed_xai_response_writes_asset(tmp_path: Path) -> None:
    root = tmp_path / "AgentLab"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "media_generation_backends.yml").write_text(
        """
backends:
  grok_direct:
    display_name: Grok Direct API Test Fixture
    adapter_state: configured
    adapter_kind: xai_imagine_rest
    api_key: env:XAI_API_KEY
    api_key_env: XAI_API_KEY
    base_url: https://api.x.ai/v1
    endpoints:
      image_generation: /images/generations
    models:
      image: grok-imagine-image-quality
    approval_required: false
""",
        encoding="utf-8",
    )

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int) -> dict:
        assert url.endswith("/images/generations")
        assert headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "grok-imagine-image-quality"
        return {"data": [{"b64_json": "ZmFrZS1wbmc="}]}

    with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}, clear=False):
        result = execute_media_contract(
            _contract(),
            root,
            tmp_path,
            live=True,
            http_post=fake_post,
            role_session=_artifact_role_session(_contract()),
        )

    assert result["status"] == "completed"
    asset = tmp_path / "generated_image_01.png"
    assert asset.exists()
    assert asset.read_bytes() == b"fake-png"
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["live"] is True
    assert ledger["generated_assets"] == [str(asset)]
