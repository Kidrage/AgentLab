from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from agent_runtime.media_backend_adapter import (
    build_claude_skill_payload_plan,
    build_hermes_ark_payload_plan,
    build_grok_cli_payload_plan,
    build_xai_payload_plan,
    execute_media_contract,
    preflight_media_contract,
    validate_media_live_role_session,
)
from agent_runtime.run_task import app
from agent_runtime.pipeline_runner import (
    _execute_media_backend_role_outputs,
    _write_media_backend_dry_run_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_media_dry_run_keeps_root_and_nested_receipts_identical(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "route": {"route_key": "media_generation_task"},
                "production_pack": {"pack_id": "media_generation"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(_oauth_contract(), sort_keys=False),
        encoding="utf-8",
    )

    written = _write_media_backend_dry_run_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-dry",
    )

    for filename in (
        "role_session_receipt.yml",
        "generation_ledger.yml",
        "generation_receipt.yml",
        "generated_assets_manifest.yml",
    ):
        assert (run_dir / filename).read_bytes() == (
            run_dir / "artifacts" / "media_backend" / filename
        ).read_bytes()
        assert f"artifacts/media_backend/{filename}" in written


def test_pipeline_execute_materializes_verified_media_role_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(_oauth_contract(), sort_keys=False),
        encoding="utf-8",
    )

    def fake_execute(contract, root, out_dir, *, live, role_session):
        assert live is True
        assert role_session["role"] == "ArtifactProducer"
        out_dir.mkdir(parents=True, exist_ok=True)
        asset = out_dir / "poster.png"
        asset.write_bytes(b"verified-media")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        asset_row = {
            "candidate_id": "asset-verified",
            "path": asset.relative_to(run_dir).as_posix(),
            "media_type": "image",
            "sha256": digest,
            "size_bytes": asset.stat().st_size,
        }
        (out_dir / "generation_ledger.yml").write_text(
            yaml.safe_dump({"status": "completed", "generated_assets": [str(asset)]}),
            encoding="utf-8",
        )
        (out_dir / "role_session_receipt.yml").write_text(
            yaml.safe_dump(
                {
                    "status": "complete",
                    "role_session_id": role_session["role_session_id"],
                    "execution_id": "media_exec_test",
                }
            ),
            encoding="utf-8",
        )
        (out_dir / "generation_receipt.yml").write_text(
            yaml.safe_dump(
                {
                    "status": "complete",
                    "producer": {
                        "role": "ArtifactProducer",
                        "id": role_session["role_session_id"],
                        "execution_id": "media_exec_test",
                    },
                    "backend": "hermes_grok_oauth",
                    "model": "grok-imagine-image-quality",
                    "prompt_parameters": {"prompt_sha256": "a" * 64},
                    "reference_assets": [],
                }
            ),
            encoding="utf-8",
        )
        (out_dir / "generated_assets_manifest.yml").write_text(
            yaml.safe_dump({"status": "complete", "assets": [asset_row]}),
            encoding="utf-8",
        )
        return {"status": "completed", "artifact_generation_verified": True}

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fake_execute,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media",
        pack_id="media_generation",
    )

    assert result["status"] == "complete"
    assert (run_dir / "generation_receipt.yml").is_file()
    assert (run_dir / "generated_assets_manifest.yml").is_file()
    delivery = yaml.safe_load((run_dir / "media_delivery_receipt.yml").read_text())
    assert delivery["status"] == "candidate_ready_for_independent_review"
    assert delivery["generated_assets"][0]["sha256"]
    capacity_receipt = yaml.safe_load(
        (run_dir / "media_capacity_route_receipt.yml").read_text(encoding="utf-8")
    )
    assert capacity_receipt["status"] == "complete"
    assert capacity_receipt["route_id"] == "ArtifactProducer"
    assert capacity_receipt["pool_id"] == "xai_subscription_shared"
    assert capacity_receipt["media_backend"] == "hermes_grok_oauth"
    capacity_ledger = yaml.safe_load(
        (run_dir / "model_capacity_ledger.yml").read_text(encoding="utf-8")
    )
    assert capacity_ledger["pools"]["xai_subscription_shared"]["status"] == "closed"


def test_pipeline_execute_blocks_receipt_without_actual_generation_model(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(_oauth_contract(), sort_keys=False),
        encoding="utf-8",
    )

    def fake_execute(contract, root, out_dir, *, live, role_session):
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in {
            "role_session_receipt.yml": {
                "status": "complete",
                "role_session_id": role_session["role_session_id"],
                "execution_id": "media_exec_test",
            },
            "generation_ledger.yml": {"status": "completed"},
            "generation_receipt.yml": {
                "status": "complete",
                "producer": {
                    "role": "ArtifactProducer",
                    "id": role_session["role_session_id"],
                    "execution_id": "media_exec_test",
                },
                "model": None,
            },
            "generated_assets_manifest.yml": {
                "status": "complete",
                "assets": [{"candidate_id": "asset-1"}],
            },
        }.items():
            (out_dir / name).write_text(yaml.safe_dump(payload), encoding="utf-8")
        return {"status": "completed", "artifact_generation_verified": True}

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fake_execute,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media",
        pack_id="media_generation",
    )

    assert result["status"] == "blocked"
    assert "invalid:generation_receipt.backend_route_mismatch" in result["issues"]
    assert "invalid:generation_receipt.actual_model_missing" in result["issues"]
    assert not (run_dir / "media_delivery_receipt.yml").exists()


def test_pipeline_pending_capacity_probes_exact_xai_auth_shape_before_execution(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract = _oauth_contract()
    contract.update(
        {
            "selected_backend": None,
            "routing_status": "pending_capacity",
            "executable": False,
            "execution_blocker": {
                "status": "capacity_pending",
                "backend": "hermes_grok_oauth",
            },
        }
    )
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    probe_calls: list[tuple[str, ...]] = []

    def fake_probe(command: tuple[str, ...]):
        probe_calls.append(command)
        return {"returncode": 0, "stdout": "authenticated", "stderr": ""}

    def fake_execute(effective_contract, root, out_dir, *, live, role_session):
        assert effective_contract["selected_backend"] == "hermes_grok_oauth"
        assert effective_contract["routing_status"] == "selected"
        return _write_verified_pipeline_media_outputs(
            run_dir,
            out_dir,
            role_session,
        )

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fake_execute,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-pending",
        pack_id="media_generation",
        capacity_probe_runner=fake_probe,
    )

    assert result["status"] == "complete"
    assert probe_calls == [("hermes", "auth", "status", "xai-oauth")]
    selected_contract = yaml.safe_load(
        (run_dir / "media_generation_contract.yml").read_text(encoding="utf-8")
    )
    assert selected_contract["routing_status"] == "selected"
    assert selected_contract["selected_backend"] == "hermes_grok_oauth"
    assert selected_contract["execution_blocker"] is None
    receipt = yaml.safe_load(
        (run_dir / "media_capacity_route_receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["probe"]["command"] == [
        "hermes", "auth", "status", "xai-oauth"
    ]
    assert receipt["probe"]["status"] == "pass"
    assert "stdout" not in yaml.safe_dump(receipt)


def test_pipeline_pending_capacity_probe_failure_blocks_provider(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract = _oauth_contract()
    contract.update(
        {
            "selected_backend": None,
            "routing_status": "pending_capacity",
            "executable": False,
            "execution_blocker": {
                "status": "capacity_pending",
                "backend": "hermes_grok_oauth",
            },
        }
    )
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    provider_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider must remain blocked")

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fail_if_called,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-pending",
        pack_id="media_generation",
        capacity_probe_runner=lambda command: {
            "returncode": 1,
            "stdout": "",
            "stderr": "not authenticated",
        },
    )

    assert result["status"] == "blocked"
    assert provider_called is False
    assert "media_capacity_probe_failed:auth_missing" in result["issues"]
    receipt = yaml.safe_load(
        (run_dir / "media_capacity_route_receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "blocked"
    assert receipt["failure_class"] == "auth_missing"
    assert "not authenticated" not in yaml.safe_dump(receipt)


def test_pipeline_rejects_handwritten_backend_outside_capacity_route(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract = _oauth_contract()
    contract["selected_backend"] = "grok_direct"
    contract["routing_status"] = "selected"
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    provider_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider must remain blocked")

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fail_if_called,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-manual",
        pack_id="media_generation",
    )

    assert result["status"] == "blocked"
    assert provider_called is False
    assert "media_backend_capacity_route_mismatch:grok_direct:hermes_grok_oauth" in result["issues"]


def test_pipeline_media_capacity_route_blocks_unsupported_modality_before_provider(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    contract = _oauth_contract()
    contract["modality"] = "audio"
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    provider_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider must remain blocked")

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        fail_if_called,
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-audio",
        pack_id="media_generation",
    )

    assert result["status"] == "blocked"
    assert provider_called is False
    assert "media_capacity_route_not_selected:unsupported_modality" in result["issues"]
    receipt = yaml.safe_load(
        (run_dir / "media_capacity_route_receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["capacity_decision"]["missing_modalities"] == ["audio"]


def test_pipeline_capacity_failure_opens_shared_xai_pool(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "media_generation_contract.yml").write_text(
        yaml.safe_dump(_oauth_contract(), sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "agent_runtime.media_backend_adapter.execute_media_contract",
        lambda *args, **kwargs: {
            "status": "blocked",
            "reason": "quota exhausted; Resets in 1h",
            "artifact_generation_verified": False,
        },
    )

    result = _execute_media_backend_role_outputs(
        ROOT,
        run_dir,
        "Demo",
        "task-media-quota",
        pack_id="media_generation",
    )

    assert result["status"] == "blocked"
    ledger = yaml.safe_load(
        (run_dir / "model_capacity_ledger.yml").read_text(encoding="utf-8")
    )
    pool = ledger["pools"]["xai_subscription_shared"]
    assert pool["status"] == "open"
    assert pool["failure_class"] == "quota_exhausted"
    receipt = yaml.safe_load(
        (run_dir / "media_capacity_route_receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "blocked"
    assert receipt["failure_class"] == "quota_exhausted"


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
    contract.update(
        {
            "selected_backend": "hermes_grok_oauth",
            "routing_status": "selected",
            "executable": True,
            "execution_blocker": None,
            "fallback_chain": [
                "hermes_grok_oauth",
                "grok_direct",
                "bailian_cli",
            ],
        }
    )
    return contract


def _seedance_skill_contract() -> dict:
    return {
        "schema_version": 1,
        "contract_type": "media_generation_contract",
        "project_id": "Crown_of_Ash",
        "task_id": "task_crown_episode_001_seedance",
        "modality": "video",
        "prompt": "A cinematic dark-fantasy opening in Grey Valley.",
        "selected_backend": "hermes_ark_seedance_skill",
        "task_backend_override": "hermes_ark_seedance_skill",
        "user_authorized_live_generation": True,
        "artifact_producer_worker": "hermes_ark",
        "generation_parameters": {
            "resolution": "720p",
            "ratio": "16:9",
            "duration": 10,
            "generate_audio": True,
            "watermark": False,
            "service_tier": "default",
            "open_after_generation": False,
        },
    }


def _write_verified_pipeline_media_outputs(
    run_dir: Path,
    out_dir: Path,
    role_session: dict,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    asset = out_dir / "poster.png"
    asset.write_bytes(b"verified-media")
    asset_row = {
        "candidate_id": "asset-verified",
        "path": asset.relative_to(run_dir).as_posix(),
        "media_type": "image",
        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        "size_bytes": asset.stat().st_size,
    }
    for name, payload in {
        "role_session_receipt.yml": {
            "status": "complete",
            "role_session_id": role_session["role_session_id"],
            "execution_id": "media_exec_test",
        },
        "generation_ledger.yml": {
            "status": "completed",
            "generated_assets": [str(asset)],
        },
        "generation_receipt.yml": {
            "status": "complete",
            "producer": {
                "role": "ArtifactProducer",
                "id": role_session["role_session_id"],
                "execution_id": "media_exec_test",
            },
            "backend": "hermes_grok_oauth",
            "model": "grok-imagine-image-quality",
            "prompt_parameters": {"prompt_sha256": "a" * 64},
            "reference_assets": [],
        },
        "generated_assets_manifest.yml": {
            "status": "complete",
            "assets": [asset_row],
        },
    }.items():
        (out_dir / name).write_text(yaml.safe_dump(payload), encoding="utf-8")
    return {"status": "completed", "artifact_generation_verified": True}


def _artifact_role_session(contract: dict | None = None) -> dict:
    contract = contract or _contract()
    worker = str(contract.get("artifact_producer_worker") or "grok")
    return {
        "packet_type": "agentlab_role_session",
        "schema_version": 1,
        "role_session_id": f"{contract.get('task_id')}:ArtifactProducer:{worker}",
        "role": "ArtifactProducer",
        "worker": worker,
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
    report = preflight_media_contract(_oauth_contract(), ROOT, command_probe=lambda _backend: True)

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


def test_preflight_rejects_stale_audio_contract_before_provider_execution() -> None:
    contract = _oauth_contract()
    contract["modality"] = "audio"

    report = preflight_media_contract(
        contract,
        ROOT,
        command_probe=lambda _backend: True,
    )

    assert report["status"] == "blocked"
    assert report["executable"] is False
    assert report["block_reason"] == "unsupported_media_modality"
    modality_check = next(
        check for check in report["checks"]
        if check["id"] == "backend_modality_supported"
    )
    assert modality_check["status"] == "fail"
    assert "audio" not in modality_check["configured_modalities"]


def test_task_only_hermes_ark_preflight_requires_override_and_authorization() -> None:
    contract = _seedance_skill_contract()
    contract.pop("task_backend_override")

    report = preflight_media_contract(contract, ROOT, command_probe=lambda _backend: True)

    assert report["status"] == "blocked"
    assert report["block_reason"] == "task_backend_override_required"

    contract["task_backend_override"] = contract["selected_backend"]
    contract["user_authorized_live_generation"] = False
    report = preflight_media_contract(contract, ROOT, command_probe=lambda _backend: True)
    assert report["block_reason"] == "user_authorization_required"

    contract["user_authorized_live_generation"] = True
    report = preflight_media_contract(contract, ROOT, command_probe=lambda _backend: True)
    assert report["status"] == "ready"
    assert report["backend"]["selection_scope"] == "explicit_task_override_only"
    assert report["backend"]["worker_id"] == "hermes_ark"
    assert report["backend"]["skill_id"] == "arkcli-video-gen"
    assert report["backend"]["fallback_backend"] == "claude_seedance_agent_plan_skill"


def test_hermes_ark_execution_verifies_seedance_asset_and_receipts(tmp_path: Path) -> None:
    contract = _seedance_skill_contract()
    asset = tmp_path / "assets" / "task-video.mp4"

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        assert timeout == 600
        assert args[0] == "hermes"
        assert args[args.index("--provider") + 1] == "openai-codex"
        assert args[args.index("-m") + 1] == "gpt-5.6-sol"
        assert args.count("-s") == 2
        assert "arkcli-gen" in args
        assert "arkcli-video-gen" in args
        assert "--model" not in args
        prompt = args[args.index("-z") + 1]
        assert "arkcli-video-gen" in prompt
        assert "Do not copy a visual model ID from AgentLab" in prompt
        assert contract["prompt"] in prompt
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"fake-seedance-video")
        worker_result = {
            "status": "completed",
            "task_id": "task-seedance-001",
            "model": "doubao-seedance-2.0",
            "generated_assets": [str(asset)],
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(worker_result),
            stderr="",
        )

    result = execute_media_contract(
        contract,
        ROOT,
        tmp_path,
        live=True,
        timeout_seconds=600,
        command_runner=fake_runner,
        role_session=_artifact_role_session(contract),
    )

    assert result["status"] == "completed"
    assert result["producer_worker"] == "hermes_ark"
    assert result["provider_task_id"] == "task-seedance-001"
    assert result["generation_model"] == "doubao-seedance-2.0"
    assert result["provider_model"] == "skill_auto"
    assert result["provider_reported_model"] == "doubao-seedance-2.0"
    assert result["generated_assets"] == [str(asset.resolve())]
    assert result["artifact_generation_verified"] is True
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text())
    assert ledger["provider_status"] == "completed"
    assert ledger["provider_model"] == "skill_auto"
    assert ledger["producer_worker"] == "hermes_ark"
    assert ledger["generated_assets"] == ["assets/task-video.mp4"]
    assert ledger["generated_asset_receipts"][0]["sha256"] == hashlib.sha256(
        b"fake-seedance-video"
    ).hexdigest()
    assert ledger["generated_asset_receipts"][0]["path"] == "assets/task-video.mp4"
    receipt = yaml.safe_load((tmp_path / "generation_receipt.yml").read_text())
    assert receipt["status"] == "complete"
    assert receipt["model_source"] == "provider_response_normalized_alias"
    assert receipt["producer"]["worker"] == "hermes_ark"
    assert receipt["prompt_parameters"]["generation_parameters"]["duration"] == 10
    manifest = yaml.safe_load((tmp_path / "outbound_context_manifest_media.yml").read_text())
    assert manifest["status"] == "pass"
    assert manifest["authorization"]["approval_observed"] is True


def test_build_hermes_ark_payload_plan_registers_skill_instruction(
    tmp_path: Path,
) -> None:
    backend = preflight_media_contract(
        _seedance_skill_contract(), ROOT, command_probe=lambda _backend: True
    )["backend"]

    plan = build_hermes_ark_payload_plan(
        _seedance_skill_contract(), backend, out_dir=tmp_path
    )

    assert plan["skill_id"] == "arkcli-video-gen"
    assert plan["invocation_contract"] == "hermes_ark_artifact_producer"
    assert plan["model_selection"] == "worker_skill_auto"
    assert plan["provider_model"] == "skill_auto"
    assert plan["args"][0] == "hermes"
    assert "--model" not in plan["args"]
    prompt = plan["args"][plan["args"].index("-z") + 1]
    assert "Do not copy a visual model ID from AgentLab" in prompt
    assert str((tmp_path / "assets").resolve()) in prompt
    assert plan["auth_mode"] == "hermes_shell_arkcli_profile"
    assert plan["fallback_backend"] == "claude_seedance_agent_plan_skill"


def test_hermes_ark_worker_failure_exposes_registered_claude_fallback(
    tmp_path: Path,
) -> None:
    def failed_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="worker transport unavailable",
        )

    contract = _seedance_skill_contract()
    result = execute_media_contract(
        contract,
        ROOT,
        tmp_path,
        live=True,
        command_runner=failed_runner,
        role_session=_artifact_role_session(contract),
    )

    assert result["status"] == "local_cli_error"
    assert result["reason"] == "hermes_ark_worker_error"
    assert result["failure_scope"] == "hermes_ark_worker"
    assert result["provider_model"] == "skill_auto"
    assert result["fallback_backend"] == "claude_seedance_agent_plan_skill"
    ledger = yaml.safe_load((tmp_path / "generation_ledger.yml").read_text())
    assert ledger["block_reason"] == "hermes_ark_worker_error"
    assert ledger["provider_model"] == "skill_auto"


def test_claude_skill_is_available_as_task_scoped_fallback() -> None:
    contract = _seedance_skill_contract()
    contract["selected_backend"] = "claude_seedance_agent_plan_skill"
    contract["task_backend_override"] = "claude_seedance_agent_plan_skill"
    contract["artifact_producer_worker"] = "claude_ark"

    report = preflight_media_contract(contract, ROOT, command_probe=lambda _backend: True)

    assert report["status"] == "ready"
    assert report["backend"]["worker_id"] == "claude_ark"
    assert report["backend"]["fallback_only"] is True
    assert report["backend"]["skill_resolution"] == "worker_registry"
    plan = build_claude_skill_payload_plan(contract, report["backend"], out_dir=ROOT)
    assert plan["skill_id"] == "byted-ark-seedance-skill"
    assert plan["invocation_contract"] == "claude_seedance_artifact_fallback"
    assert "--model" not in plan["args"]


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
    assert ledger["text_artifacts"] == ["grok_cli_response.md"]
    assert ledger["generated_assets"] == []
    assert ledger["artifact_generation_verified"] is False
    assert yaml.safe_load((tmp_path / "generated_assets_manifest.yml").read_text())["status"] == "blocked"
    assert yaml.safe_load((tmp_path / "generation_receipt.yml").read_text())["status"] == "blocked"


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
            stdout=(
                "done\n"
                "AGENTLAB_GENERATION_MODEL: grok-imagine-image-quality\n"
                "AGENTLAB_GENERATED_ASSET: poster.png\n"
            ),
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
    assert ledger["generated_assets"] == ["poster.png"]
    assert ledger["generated_asset_receipts"] == [
        {
            "path": "poster.png",
            "sha256": hashlib.sha256(b"fake-png").hexdigest(),
            "size_bytes": len(b"fake-png"),
        }
    ]
    assert ledger["artifact_generation_verified"] is True
    assert ledger["producer_role_session_id"] == _artifact_role_session(_oauth_contract())["role_session_id"]
    receipt = yaml.safe_load((tmp_path / "generation_receipt.yml").read_text(encoding="utf-8"))
    assert receipt["status"] == "complete"
    assert receipt["model"] == "grok-imagine-image-quality"
    assert receipt["model_source"] == "worker_report_marker"
    assert receipt["model_registered_for_backend"] is True
    assert receipt["producer"]["id"] == _artifact_role_session(_oauth_contract())["role_session_id"]
    assert receipt["producer"]["execution_id"].startswith("media_exec_")
    role_receipt = yaml.safe_load((tmp_path / "role_session_receipt.yml").read_text(encoding="utf-8"))
    assert role_receipt["status"] == "complete"
    assert role_receipt["role_session_id"] == receipt["producer"]["id"]
    assert role_receipt["execution_id"] == receipt["producer"]["execution_id"]
    assert ledger["asset_return_contract"]["marker"] == "AGENTLAB_GENERATED_ASSET:"
    manifest = yaml.safe_load((tmp_path / "outbound_context_manifest_media.yml").read_text(encoding="utf-8"))
    assert manifest["status"] == "pass"
    assert manifest["payload"]["secret_pattern_hit_count"] == 0
    assert len(manifest["payload"]["sha256"]) == 64


def test_local_grok_cli_blocks_unregistered_reported_generation_model(tmp_path: Path) -> None:
    asset = tmp_path / "poster.png"

    def fake_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        asset.write_bytes(b"fake-png")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "AGENTLAB_GENERATION_MODEL: invented-image-model\n"
                "AGENTLAB_GENERATED_ASSET: poster.png\n"
            ),
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

    assert result["status"] == "blocked"
    assert result["reason"] == "generation_model_not_registered_for_backend"
    assert result["artifact_generation_verified"] is False
    receipt = yaml.safe_load((tmp_path / "generation_receipt.yml").read_text())
    assert receipt["status"] == "blocked"
    assert receipt["model_registered_for_backend"] is False
    assert "generation_model_not_registered_for_backend" in receipt["issues"]


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
    assert yaml.safe_load((tmp_path / "generated_assets_manifest.yml").read_text())["status"] == "blocked"
    assert yaml.safe_load((tmp_path / "generation_receipt.yml").read_text())["status"] == "blocked"
    assert yaml.safe_load((tmp_path / "role_session_receipt.yml").read_text())["status"] == "blocked"


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
            "grok",
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
    assert "grok-4.5" in plan["args"]
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
    modalities: [image]
    api_key: literal-test-key
    base_url: https://api.x.ai/v1
    endpoints:
      image_generation: /images/generations
    models:
      image: grok-imagine-image-quality
    registered_generation_models:
      image: [grok-imagine-image-quality]
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
    modalities: [image]
    api_key: env:XAI_API_KEY
    api_key_env: XAI_API_KEY
    base_url: https://api.x.ai/v1
    endpoints:
      image_generation: /images/generations
    models:
      image: grok-imagine-image-quality
    registered_generation_models:
      image: [grok-imagine-image-quality]
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
    assert ledger["generated_assets"] == ["generated_image_01.png"]
    role_receipt = yaml.safe_load((tmp_path / "role_session_receipt.yml").read_text(encoding="utf-8"))
    receipt = yaml.safe_load((tmp_path / "generation_receipt.yml").read_text(encoding="utf-8"))
    assert role_receipt["status"] == "complete"
    assert receipt["producer"]["id"] == role_receipt["role_session_id"]
    assert receipt["producer"]["execution_id"] == role_receipt["execution_id"]
