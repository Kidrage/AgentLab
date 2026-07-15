"""Media backend adapter seam for AgentLab media generation contracts.

The media generation router decides *which* backend should handle a request.
This module owns the execution-facing contract for that backend: preflight,
payload planning, and opt-in live invocation. Live calls are never made by
default.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml

try:
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.config_loader import load_yaml
    from agent_runtime.model_resolver import resolve_env_value
except ImportError:  # pragma: no cover - direct runtime import path
    from atomic_io import atomic_write_yaml
    from config_loader import load_yaml
    from model_resolver import resolve_env_value


HttpPost = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]
HttpGet = Callable[[str, dict[str, str], int], bytes | dict[str, Any]]
CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]
CommandProbe = Callable[[dict[str, Any]], bool]

LOCAL_GROK_CLI_ADAPTERS = {"local_grok_cli", "grok_cli_oauth"}
SUPPORTED_ADAPTERS = {"xai_imagine_rest", *LOCAL_GROK_CLI_ADAPTERS}
GROK_ASSET_MARKER = "AGENTLAB_GENERATED_ASSET:"
GROK_MODEL_MARKER = "AGENTLAB_GENERATION_MODEL:"
GROK_SMOKE_FALLBACK_KEYS = ("hermes_session_smoke", "hermes_smoke_session", "oauth_smoke")
PROMPT_FLAGS = {"-p", "--prompt", "-q", "-z", "--oneshot"}
GROK_SETTINGS_FETCH_MARKER = "Settings fetch failed"
GROK_TRANSPORT_FAILURE_MARKERS = (
    "request error",
    "error sending request",
    "api call failed",
    "connection error",
    "transport",
    "could not resolve host",
    "failed to connect",
    "connection refused",
    "network is unreachable",
    "no route to host",
    "timed out",
)
GROK_AUTH_FAILURE_MARKERS = (
    "not authenticated",
    "oauth session expired",
    "oauth error",
    "sign in",
    "login required",
    "unauthorized",
)


def load_media_generation_contract(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_media_backends(agentlab_root: Path) -> dict[str, dict[str, Any]]:
    config = load_yaml(Path(agentlab_root) / "config" / "media_generation_backends.yml")
    backends = config.get("backends", {}) if isinstance(config, dict) else {}
    return backends if isinstance(backends, dict) else {}


def preflight_media_contract(
    contract: dict[str, Any],
    agentlab_root: Path,
    *,
    command_probe: CommandProbe | None = None,
) -> dict[str, Any]:
    """Return a deterministic execution readiness report for a media contract."""
    backends = load_media_backends(agentlab_root)
    backend_id = str(contract.get("selected_backend") or "")
    backend = backends.get(backend_id, {})
    checks: list[dict[str, Any]] = []

    def check(ok: bool, check_id: str, message: str, **extra: Any) -> None:
        item = {
            "id": check_id,
            "status": "pass" if ok else "fail",
            "message": message,
        }
        item.update(extra)
        checks.append(item)

    check(bool(backend_id), "selected_backend_present", "media contract declares selected_backend")
    check(bool(backend), "backend_config_present", f"backend config exists for {backend_id or '<none>'}")
    if not backend:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "backend_config_missing")

    adapter_state = _adapter_state(backend)
    adapter_kind = str(backend.get("adapter_kind") or "")
    modality = str(contract.get("modality") or "").strip()
    configured_modalities = [
        str(item).strip()
        for item in (backend.get("modalities") or [])
        if str(item).strip()
    ]
    modality_supported = bool(modality) and modality in configured_modalities
    registered_models = _allowed_generation_models(backend, modality)
    api_key_env = str(backend.get("api_key_env") or "")
    accepted_env = _backend_api_key_env_names(backend)
    api_key_present = bool(_backend_api_key(backend))
    command_available = (command_probe or _backend_command_available)(backend)
    approval_required = bool(backend.get("approval_required", False))

    check(adapter_state in {"configured", "ready"}, "adapter_configured", f"adapter_state is {adapter_state}")
    check(adapter_kind in SUPPORTED_ADAPTERS, "adapter_kind_supported", f"adapter_kind is {adapter_kind or '<missing>'}")
    check(
        modality_supported,
        "backend_modality_supported",
        (
            f"backend explicitly supports modality {modality}"
            if modality_supported
            else f"backend does not explicitly support modality {modality or '<missing>'}"
        ),
        modality=modality or None,
        configured_modalities=configured_modalities,
    )
    check(
        bool(registered_models),
        "generation_model_registered",
        (
            f"registered generation model exists for {modality}"
            if registered_models
            else f"no registered generation model exists for {modality or '<missing>'}"
        ),
        registered_models=registered_models,
    )
    if adapter_kind in LOCAL_GROK_CLI_ADAPTERS:
        configured_command = str(backend.get("command") or "").strip()
        check(
            bool(configured_command) and command_available,
            "local_cli_available",
            f"Configured media shell command {configured_command} is available"
            if configured_command and command_available
            else "Media backend requires an explicit available shell command",
            command=configured_command or None,
            auth_probe=backend.get("auth_probe"),
        )
        command_available = bool(configured_command) and command_available
    if api_key_env:
        check(
            api_key_present,
            "auth_secret_present",
            (
                f"One of {', '.join(accepted_env)} is configured"
                if api_key_present
                else f"One of {', '.join(accepted_env)} is missing"
            ),
            env_var=api_key_env,
            aliases=backend.get("api_key_env_aliases") or [],
            accepted_env=accepted_env,
        )
    check(not approval_required, "approval_not_required", "backend does not require user approval before live execution")

    if adapter_state not in {"configured", "ready"}:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "adapter_unavailable")
    if adapter_kind not in SUPPORTED_ADAPTERS:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "unsupported_adapter")
    if not modality_supported:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "unsupported_media_modality")
    if not registered_models:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "generation_model_not_registered")
    if adapter_kind in LOCAL_GROK_CLI_ADAPTERS and not command_available:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "missing_media_shell_command")
    if api_key_env and not api_key_present:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "missing_auth")
    if approval_required:
        return _preflight_result(contract, backend_id, backend, checks, "blocked", "approval_required")

    return _preflight_result(contract, backend_id, backend, checks, "ready", None)


def execute_media_contract(
    contract: dict[str, Any],
    agentlab_root: Path,
    out_dir: Path,
    *,
    live: bool = False,
    timeout_seconds: int = 60,
    poll_interval_seconds: int = 5,
    max_polls: int = 24,
    http_post: HttpPost | None = None,
    http_get: HttpGet | None = None,
    command_runner: CommandRunner | None = None,
    role_session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute or dry-run a media contract and write auditable adapter artifacts.

    `live=False` writes an execution plan and ledger only. `live=True` may make
    network calls and requires preflight to pass.
    """
    out_dir = Path(out_dir).resolve(strict=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    preflight = preflight_media_contract(
        contract,
        agentlab_root,
        command_probe=(
            (lambda backend: bool(str(backend.get("command") or "").strip()))
            if command_runner is not None
            else None
        ),
    )
    runtime_backend = (
        load_media_backends(agentlab_root).get(str(preflight.get("backend_id") or ""), {})
        or preflight.get("backend")
        or {}
    )
    payload_plan = build_payload_plan(contract, runtime_backend, out_dir=out_dir)
    atomic_write_yaml(out_dir / "media_backend_preflight.yml", preflight)
    atomic_write_yaml(out_dir / "media_backend_payload_plan.yml", payload_plan)

    if not live:
        result = {
            "status": "dry_run",
            "live": False,
            "backend": preflight.get("backend_id"),
            "adapter_kind": preflight.get("adapter_kind"),
            "generated_assets": [],
            "ledger_path": str(out_dir / "generation_ledger.yml"),
            "note": "Dry run only; no media backend was called.",
        }
        _write_generation_ledger(out_dir, contract, preflight, result)
        return result

    live_guard = validate_media_live_role_session(contract, role_session)
    if live_guard.get("status") != "pass":
        result = {
            "status": "blocked",
            "live": True,
            "backend": preflight.get("backend_id"),
            "reason": live_guard.get("reason"),
            "generated_assets": [],
            "role_session_guard": live_guard,
        }
        _write_generation_ledger(out_dir, contract, preflight, result)
        return result

    execution_id = "media_exec_" + uuid.uuid4().hex

    if preflight.get("status") != "ready":
        result = {
            "status": "blocked",
            "live": True,
            "backend": preflight.get("backend_id"),
            "reason": preflight.get("block_reason"),
            "generated_assets": [],
            "execution_id": execution_id,
            "producer_role_session_id": live_guard.get("role_session_id"),
            "producer_worker": live_guard.get("worker"),
        }
        _write_generation_ledger(out_dir, contract, preflight, result)
        return result

    if preflight.get("adapter_kind") in LOCAL_GROK_CLI_ADAPTERS:
        if command_runner is not None:
            result = _execute_local_grok_cli(
                contract,
                preflight,
                out_dir,
                backend=runtime_backend,
                agentlab_root=Path(agentlab_root),
                timeout_seconds=timeout_seconds,
                command_runner=command_runner,
                execution_workspace_isolated=False,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="agentlab-media-role-") as workspace:
                result = _execute_local_grok_cli(
                    contract,
                    preflight,
                    out_dir,
                    backend=runtime_backend,
                    agentlab_root=Path(agentlab_root),
                    timeout_seconds=timeout_seconds,
                    command_runner=lambda args, timeout: _run_command(
                        args,
                        timeout,
                        cwd=Path(workspace),
                    ),
                    execution_workspace_isolated=True,
                )
        result["execution_id"] = execution_id
        result["producer_role_session_id"] = live_guard.get("role_session_id")
        result["producer_worker"] = live_guard.get("worker")
        _write_generation_ledger(out_dir, contract, preflight, result)
        return result

    if preflight.get("adapter_kind") != "xai_imagine_rest":
        result = {
            "status": "blocked",
            "live": True,
            "backend": preflight.get("backend_id"),
            "reason": "unsupported_adapter",
            "generated_assets": [],
            "execution_id": execution_id,
            "producer_role_session_id": live_guard.get("role_session_id"),
            "producer_worker": live_guard.get("worker"),
        }
        _write_generation_ledger(out_dir, contract, preflight, result)
        return result

    result = _execute_xai_imagine(
        contract,
        preflight,
        payload_plan,
        out_dir,
        backend=runtime_backend,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
        http_post=http_post or _http_post_json,
        http_get=http_get or _http_get,
    )
    result["execution_id"] = execution_id
    result["producer_role_session_id"] = live_guard.get("role_session_id")
    result["producer_worker"] = live_guard.get("worker")
    _write_generation_ledger(out_dir, contract, preflight, result)
    return result


def validate_media_live_role_session(
    contract: dict[str, Any],
    role_session: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate the role-session evidence required for live media execution."""
    if not role_session:
        return {
            "status": "blocked",
            "reason": "missing_role_session",
            "message": "live media execution requires an AgentLab ArtifactProducer role-session packet",
        }
    checks: list[dict[str, Any]] = []

    def check(ok: bool, check_id: str, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": message})

    packet_type = role_session.get("packet_type")
    role_session_id = str(role_session.get("role_session_id") or "").strip()
    role = role_session.get("role")
    worker = role_session.get("worker")
    binding = role_session.get("binding") if isinstance(role_session.get("binding"), dict) else {}
    session_project = role_session.get("project")
    session_task_id = role_session.get("task_id")
    contract_project = contract.get("project_id")
    contract_task_id = contract.get("task_id")

    check(packet_type == "agentlab_role_session", "packet_type", "packet is an AgentLab role-session")
    check(bool(role_session_id), "role_session_id", "role-session has a stable identity")
    check(role == "ArtifactProducer", "role_owner", "role-session belongs to ArtifactProducer")
    check(worker == "grok", "worker_owner", "role-session uses the registered grok worker")
    check(binding.get("allowed") is True, "binding_allowed", "role binding is allowed")
    if contract_project and session_project:
        check(session_project == contract_project, "project_match", "role-session project matches media contract")
    if contract_task_id and session_task_id:
        check(session_task_id == contract_task_id, "task_id_match", "role-session task_id matches media contract")

    failed = [item for item in checks if item["status"] != "pass"]
    if failed:
        return {
            "status": "blocked",
            "reason": "invalid_role_session",
            "checks": checks,
            "message": "live media execution must be owned by an allowed ArtifactProducer role-session",
        }
    return {
        "status": "pass",
        "reason": None,
        "checks": checks,
        "role_session_id": role_session_id,
        "role": role,
        "worker": worker,
        "project": session_project,
        "task_id": session_task_id,
    }


def build_payload_plan(
    contract: dict[str, Any],
    backend: dict[str, Any],
    *,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    if backend.get("adapter_kind") in LOCAL_GROK_CLI_ADAPTERS:
        return build_grok_cli_payload_plan(contract, backend, out_dir=out_dir)
    return build_xai_payload_plan(contract, backend)


def build_grok_cli_payload_plan(
    contract: dict[str, Any],
    backend: dict[str, Any],
    *,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    prompt = str(contract.get("prompt") or "")
    modality = str(contract.get("modality") or "image")
    command = str(backend.get("command") or "").strip()
    command_contract = backend.get("command_contract") if isinstance(backend.get("command_contract"), dict) else {}
    command_template = str(command_contract.get("session_smoke") or command_contract.get("oauth_smoke") or "")
    asset_return_contract = {
        "marker": GROK_ASSET_MARKER,
        "asset_root": str(out_dir) if out_dir else None,
        "requires_existing_local_files": True,
        "text_handoff_is_not_media_artifact": True,
    }
    asset_instruction = (
        f"If media files are generated, save/export them under this directory: {out_dir}. "
        f"Return one line per generated file as '{GROK_ASSET_MARKER} <path>'. "
        f"Return the actual image/video generation model as '{GROK_MODEL_MARKER} <model>'. "
        "Only report paths for local files that exist. "
        "If no media file is generated, return AGENTLAB_NO_MEDIA_ASSET."
        if out_dir
        else (
            f"If media files are generated, return one line per generated file as "
            f"'{GROK_ASSET_MARKER} <path>'. Text-only replies are handoff notes, not media artifacts."
        )
    )
    media_prompt = (
        "AgentLab media backend local Grok CLI task. Do not include secrets. "
        f"Intended media modality: {modality}. {asset_instruction} "
        f"Prompt summary: {prompt[:1200]}"
    )
    return {
        "prompt": media_prompt,
        "adapter_kind": backend.get("adapter_kind"),
        "modality": modality,
        "command": command,
        "args": _render_grok_cli_args(command, command_template, media_prompt),
        "artifact_generation_verified": False,
        "artifact_return_contract": asset_return_contract,
        "auth_mode": "local_authenticated_cli_session",
        "note": "The configured Hermes+xAI shell uses its authenticated session; media acceptance requires returned local asset paths under the trusted runner out_dir.",
    }


def _render_grok_cli_args(command: str, command_template: str, prompt: str) -> list[str]:
    if not command:
        return []
    if command_template:
        try:
            args = shlex.split(command_template)
        except ValueError:
            args = []
        if args:
            rendered = [prompt if arg == "<prompt>" else arg for arg in args]
            if any(flag in rendered for flag in PROMPT_FLAGS):
                return rendered
    return [command, "-p", prompt, "--output-format", "plain", "--max-turns", "3"]


def _grok_smoke_templates(backend: dict[str, Any]) -> list[str]:
    command_contract = backend.get("command_contract") if isinstance(backend.get("command_contract"), dict) else {}
    session_template = str(command_contract.get("session_smoke") or "").strip()
    templates = [session_template] if session_template else []
    for key in GROK_SMOKE_FALLBACK_KEYS:
        template = str(command_contract.get(key) or "").strip()
        if template and template not in templates:
            templates.append(template)
    return templates


def _run_local_grok_cli_command(
    args: list[str],
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> tuple[bool, subprocess.CompletedProcess[str], bool]:
    timed_out = False
    try:
        completed = command_runner(args, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        completed = subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=_coerce_process_text(exc.stdout),
            stderr=_coerce_process_text(exc.stderr),
        )
    stderr = _coerce_process_text(completed.stderr)
    settings_fetch_failed = GROK_SETTINGS_FETCH_MARKER in stderr
    return timed_out, completed, settings_fetch_failed


def _classify_local_grok_cli_failure(stdout: str, stderr: str, fallback_reason: str) -> dict[str, Any]:
    combined = f"{stdout}\n{stderr}".lower()
    settings_fetch_failed = GROK_SETTINGS_FETCH_MARKER.lower() in combined
    transport_failure = any(marker in combined for marker in GROK_TRANSPORT_FAILURE_MARKERS)
    auth_failure = any(marker in combined for marker in GROK_AUTH_FAILURE_MARKERS)
    if transport_failure:
        reason = "grok_cli_transport_or_proxy_failed"
        failure_scope = "local_grok_network_or_proxy"
    elif settings_fetch_failed:
        reason = "grok_cli_settings_fetch_failed"
        failure_scope = "local_grok_session_health"
    elif auth_failure:
        reason = "grok_cli_auth_session_unhealthy"
        failure_scope = "local_grok_session_health"
    else:
        reason = fallback_reason
        failure_scope = "local_grok_cli_execution"
    return {
        "reason": reason,
        "failure_scope": failure_scope,
        "settings_fetch_failed": settings_fetch_failed,
        "transport_failure_marker_present": transport_failure,
        "auth_failure_marker_present": auth_failure,
    }


def build_xai_payload_plan(contract: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
    modality = str(contract.get("modality") or "image")
    prompt = str(contract.get("prompt") or "")
    base_url = str(backend.get("base_url") or "https://api.x.ai/v1").rstrip("/")
    endpoints = backend.get("endpoints") or {}
    models = backend.get("models") or {}
    delivery_constraints = contract.get("delivery_constraints") or {}

    if modality == "video":
        endpoint = f"{base_url}{endpoints.get('video_generation', '/videos/generations')}"
        payload = {
            "model": models.get("video", "grok-imagine-video-1.5"),
            "prompt": prompt,
            "duration": int(backend.get("default_video_duration_seconds", 8)),
        }
        if delivery_constraints.get("aspect_ratio"):
            payload["aspect_ratio"] = delivery_constraints["aspect_ratio"]
    else:
        endpoint = f"{base_url}{endpoints.get('image_generation', '/images/generations')}"
        payload = {
            "model": models.get("image", "grok-imagine-image-quality"),
            "prompt": prompt,
            "n": int(backend.get("default_image_count", 1)),
            "response_format": backend.get("default_response_format", "b64_json"),
        }
        if delivery_constraints.get("aspect_ratio"):
            payload["aspect_ratio"] = delivery_constraints["aspect_ratio"]

    return {
        "adapter_kind": backend.get("adapter_kind"),
        "modality": modality,
        "endpoint": endpoint,
        "payload": payload,
        "poll_endpoint_template": f"{base_url}{endpoints.get('video_poll', '/videos/{request_id}')}",
    }


def _execute_local_grok_cli(
    contract: dict[str, Any],
    preflight: dict[str, Any],
    out_dir: Path,
    *,
    backend: dict[str, Any],
    agentlab_root: Path,
    timeout_seconds: int,
    command_runner: CommandRunner,
    execution_workspace_isolated: bool = False,
) -> dict[str, Any]:
    plan = build_grok_cli_payload_plan(contract, backend, out_dir=out_dir)
    modality = str(contract.get("modality") or "image")
    response_path = out_dir / "grok_cli_response.md"
    templates = _grok_smoke_templates(backend)
    command = str(plan.get("command") or "").strip()
    prompt = str(plan.get("prompt") or "")
    try:
        from agent_runtime.outbound_context import write_outbound_context_manifest
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from outbound_context import write_outbound_context_manifest

    manifest_path = out_dir / "outbound_context_manifest_media.yml"
    approval_required = (
        os.getenv("AGENTLAB_TRUSTED_LIVE_RUNNER") == "1"
        or out_dir.name.startswith("media_backend_live_internal_")
    )
    manifest = write_outbound_context_manifest(
        Path(agentlab_root),
        manifest_path,
        item_id=str(contract.get("task_id") or out_dir.name),
        role="ArtifactProducer",
        provider_surface=f"local_cli:{command}",
        payload_kind="media_prompt_summary",
        payload_text=prompt,
        source_paths=[],
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=execution_workspace_isolated,
        approval_required=approval_required,
    )
    if not manifest.get("execution_allowed"):
        return {
            "status": "blocked",
            "live": True,
            "backend": preflight.get("backend_id"),
            "adapter_kind": preflight.get("adapter_kind"),
            "reason": "media_outbound_context_gate_blocked",
            "outbound_context_status": manifest.get("status"),
            "outbound_context_manifest": str(manifest_path),
            "generated_assets": [],
            "text_artifacts": [str(manifest_path)],
            "artifact_generation_verified": False,
        }
    if not templates:
        # Keep backwards-compatible behavior: render default command when contract
        # does not provide any explicit smoke template.
        templates = [""]
    failure_result: dict[str, Any] | None = None

    for attempt_index, template in enumerate(templates):
        args = _render_grok_cli_args(command, template, prompt)
        execution_scope = "internal_local_cli_worker" if attempt_index == 0 else "hermes_fallback_session"
        timed_out, completed, settings_fetch_failed = _run_local_grok_cli_command(
            args,
            timeout_seconds,
            command_runner,
        )
        stdout = _coerce_process_text(completed.stdout).strip()
        stderr = _coerce_process_text(completed.stderr).strip()
        failure = _classify_local_grok_cli_failure(
            stdout,
            stderr,
            "grok_cli_timeout" if timed_out else "grok_cli_nonzero_exit",
        )
        response_path.write_text(stdout + ("\n" if stdout else ""), encoding="utf-8")

        if timed_out:
            failure_result = {
                "status": "local_cli_timeout",
                "live": True,
                "backend": preflight.get("backend_id"),
                "adapter_kind": preflight.get("adapter_kind"),
                "command": args[0] if args else plan.get("command"),
                "execution_scope": execution_scope,
                "reason": failure["reason"],
                "failure_scope": failure["failure_scope"],
                "timeout_seconds": timeout_seconds,
                "stdout_excerpt": stdout[:500],
                "stderr_excerpt": stderr[:500],
                "settings_fetch_failed": failure["settings_fetch_failed"],
                "transport_failure_marker_present": failure["transport_failure_marker_present"],
                "auth_failure_marker_present": failure["auth_failure_marker_present"],
                "generated_assets": [],
                "text_artifacts": [str(response_path)] if response_path.exists() else [],
                "artifact_generation_verified": False,
            }
            if not failure["settings_fetch_failed"] or attempt_index == len(templates) - 1:
                return failure_result
            continue

        if completed.returncode != 0:
            failure_result = {
                "status": "local_cli_error",
                "live": True,
                "backend": preflight.get("backend_id"),
                "adapter_kind": preflight.get("adapter_kind"),
                "command": args[0] if args else plan.get("command"),
                "execution_scope": execution_scope,
                "reason": failure["reason"],
                "failure_scope": failure["failure_scope"],
                "returncode": completed.returncode,
                "stderr_excerpt": stderr[:500],
                "settings_fetch_failed": failure["settings_fetch_failed"],
                "transport_failure_marker_present": failure["transport_failure_marker_present"],
                "auth_failure_marker_present": failure["auth_failure_marker_present"],
                "generated_assets": [],
                "text_artifacts": [str(response_path)] if response_path.exists() else [],
                "artifact_generation_verified": False,
            }
            if not failure["settings_fetch_failed"] or attempt_index == len(templates) - 1:
                return failure_result
            continue

        if (
            failure["transport_failure_marker_present"]
            or failure["settings_fetch_failed"]
            or failure["auth_failure_marker_present"]
        ):
            return {
                "status": "local_cli_error",
                "live": True,
                "backend": preflight.get("backend_id"),
                "adapter_kind": preflight.get("adapter_kind"),
                "command": args[0] if args else plan.get("command"),
                "execution_scope": execution_scope,
                "reason": failure["reason"],
                "failure_scope": failure["failure_scope"],
                "returncode": completed.returncode,
                "stdout_excerpt": stdout[:500],
                "stderr_excerpt": stderr[:500],
                "settings_fetch_failed": failure["settings_fetch_failed"],
                "transport_failure_marker_present": failure["transport_failure_marker_present"],
                "auth_failure_marker_present": failure["auth_failure_marker_present"],
                "generated_assets": [],
                "text_artifacts": [str(response_path)] if response_path.exists() else [],
                "artifact_generation_verified": False,
            }

        collected = _collect_local_grok_assets(stdout, out_dir)
        generated_assets = collected["generated_assets"]
        if generated_assets:
            generation_model = _parse_grok_generation_model(stdout)
            allowed_models = _allowed_generation_models(backend, modality)
            model_issue = (
                "actual_generation_model_missing"
                if not generation_model
                else "generation_model_not_registered_for_backend"
                if generation_model not in allowed_models
                else None
            )
            return {
                "status": "completed" if model_issue is None else "blocked",
                "live": True,
                "backend": preflight.get("backend_id"),
                "adapter_kind": preflight.get("adapter_kind"),
                "command": args[0] if args else plan.get("command"),
                "execution_scope": execution_scope,
                "generated_assets": generated_assets,
                "text_artifacts": [str(response_path)],
                "artifact_generation_verified": model_issue is None,
                "reason": model_issue,
                "asset_claims": collected["asset_claims"],
                "asset_claims_rejected": collected["asset_claims_rejected"],
                "asset_return_contract": plan.get("artifact_return_contract"),
                "generation_model": generation_model,
                "note": (
                    "Local Grok CLI call succeeded and returned verified local media artifacts."
                    if attempt_index == 0
                    else "Fallback media CLI call succeeded and returned verified local media artifacts."
                ),
            }
        return {
            "status": "completed_text_handoff",
            "live": True,
            "backend": preflight.get("backend_id"),
            "adapter_kind": preflight.get("adapter_kind"),
            "command": args[0] if args else plan.get("command"),
            "execution_scope": execution_scope,
            "generated_assets": [],
            "text_artifacts": [str(response_path)],
            "artifact_generation_verified": False,
            "asset_claims": collected["asset_claims"],
            "asset_claims_rejected": collected["asset_claims_rejected"],
            "asset_return_contract": plan.get("asset_return_contract"),
            "note": (
                "Local Grok CLI call succeeded; no media file artifact was returned by this adapter."
                if attempt_index == 0
                else "Fallback media CLI call succeeded; no media file artifact was returned by this adapter."
            ),
        }

    return failure_result or {
        "status": "local_cli_error",
        "live": True,
        "backend": preflight.get("backend_id"),
        "adapter_kind": preflight.get("adapter_kind"),
        "command": command,
        "execution_scope": "hermes_fallback_session",
        "reason": "grok_cli_settings_fetch_failed",
        "timeout_seconds": timeout_seconds,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "settings_fetch_failed": True,
        "transport_failure_marker_present": False,
        "auth_failure_marker_present": False,
        "generated_assets": [],
        "text_artifacts": [str(response_path)] if response_path.exists() else [],
        "artifact_generation_verified": False,
    }


def _parse_grok_asset_claims(stdout: str) -> list[str]:
    claims: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if not stripped.startswith(GROK_ASSET_MARKER):
            continue
        raw = stripped[len(GROK_ASSET_MARKER) :].strip().strip("`'\"")
        if raw:
            claims.append(raw)
    return claims


def _parse_grok_generation_model(stdout: str) -> str | None:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        if stripped.startswith(GROK_MODEL_MARKER):
            model = stripped[len(GROK_MODEL_MARKER) :].strip().strip("`'\"")
            return model or None
    return None


def _allowed_generation_models(backend: dict[str, Any], modality: str) -> list[str]:
    registered = (
        backend.get("registered_generation_models")
        if isinstance(backend.get("registered_generation_models"), dict)
        else {}
    )
    raw = registered.get(modality) or []
    if isinstance(raw, str):
        raw = [raw]
    allowed = [str(item) for item in raw if str(item).strip()]
    models = backend.get("models") if isinstance(backend.get("models"), dict) else {}
    configured = str(models.get(modality) or "").strip()
    if configured and configured not in allowed:
        allowed.append(configured)
    return allowed


def _collect_local_grok_assets(stdout: str, out_dir: Path) -> dict[str, Any]:
    out_root = out_dir.resolve()
    assets: list[str] = []
    rejected: list[dict[str, str]] = []
    for claim in _parse_grok_asset_claims(stdout):
        candidate = Path(claim)
        if not candidate.is_absolute():
            candidate = out_dir / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(out_root)
        except ValueError:
            rejected.append({"path": claim, "reason": "outside_out_dir"})
            continue
        if not resolved.exists() or not resolved.is_file():
            rejected.append({"path": claim, "reason": "missing_or_not_file"})
            continue
        if resolved.stat().st_size <= 0:
            rejected.append({"path": claim, "reason": "empty_file"})
            continue
        assets.append(str(resolved))
    return {
        "asset_claims": _parse_grok_asset_claims(stdout),
        "generated_assets": assets,
        "asset_claims_rejected": rejected,
    }


def _coerce_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _execute_xai_imagine(
    contract: dict[str, Any],
    preflight: dict[str, Any],
    payload_plan: dict[str, Any],
    out_dir: Path,
    *,
    backend: dict[str, Any],
    timeout_seconds: int,
    poll_interval_seconds: int,
    max_polls: int,
    http_post: HttpPost,
    http_get: HttpGet,
) -> dict[str, Any]:
    api_key = _backend_api_key(backend)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = http_post(payload_plan["endpoint"], headers, payload_plan["payload"], timeout_seconds)
    modality = str(contract.get("modality") or "image")

    if modality == "video":
        return _handle_xai_video_response(
            response,
            payload_plan,
            out_dir,
            headers,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            max_polls=max_polls,
            http_get=http_get,
        )
    return _handle_xai_image_response(response, out_dir, http_get, headers, timeout_seconds)


def _handle_xai_image_response(
    response: dict[str, Any],
    out_dir: Path,
    http_get: HttpGet,
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    generated: list[str] = []
    for index, item in enumerate(response.get("data") or [], start=1):
        if item.get("b64_json"):
            path = out_dir / f"generated_image_{index:02d}.png"
            path.write_bytes(base64.b64decode(str(item["b64_json"])))
            generated.append(str(path))
        elif item.get("url"):
            path = out_dir / f"generated_image_{index:02d}.png"
            content = http_get(str(item["url"]), headers, timeout_seconds)
            if isinstance(content, bytes):
                path.write_bytes(content)
                generated.append(str(path))
    return {
        "status": "completed" if generated else "no_artifact_returned",
        "live": True,
        "generated_assets": generated,
        "raw_response_keys": sorted(response.keys()),
    }


def _handle_xai_video_response(
    response: dict[str, Any],
    payload_plan: dict[str, Any],
    out_dir: Path,
    headers: dict[str, str],
    *,
    timeout_seconds: int,
    poll_interval_seconds: int,
    max_polls: int,
    http_get: HttpGet,
) -> dict[str, Any]:
    request_id = response.get("request_id") or response.get("id")
    if not request_id:
        return {
            "status": "provider_error",
            "live": True,
            "reason": "missing_request_id",
            "generated_assets": [],
            "raw_response_keys": sorted(response.keys()),
        }
    poll_url = str(payload_plan["poll_endpoint_template"]).format(request_id=request_id)
    last_result: dict[str, Any] = {}
    for _ in range(max_polls):
        raw = http_get(poll_url, headers, timeout_seconds)
        if isinstance(raw, bytes):
            last_result = json.loads(raw.decode("utf-8"))
        else:
            last_result = raw
        status = str(last_result.get("status") or "").lower()
        if status in {"done", "completed", "succeeded"}:
            video = last_result.get("video") or {}
            url = video.get("url") or last_result.get("url")
            if not url:
                return {
                    "status": "no_artifact_returned",
                    "live": True,
                    "request_id": request_id,
                    "generated_assets": [],
                }
            asset_path = out_dir / "generated_video_01.mp4"
            content = http_get(str(url), headers, timeout_seconds)
            if isinstance(content, bytes):
                asset_path.write_bytes(content)
                return {
                    "status": "completed",
                    "live": True,
                    "request_id": request_id,
                    "generated_assets": [str(asset_path)],
                }
        if status in {"failed", "expired", "canceled", "cancelled"}:
            return {
                "status": "provider_error",
                "live": True,
                "request_id": request_id,
                "reason": status,
                "generated_assets": [],
                "provider_response": last_result,
            }
        time.sleep(poll_interval_seconds)
    return {
        "status": "timeout",
        "live": True,
        "request_id": request_id,
        "generated_assets": [],
        "provider_response": last_result,
    }


def _preflight_result(
    contract: dict[str, Any],
    backend_id: str,
    backend: dict[str, Any],
    checks: list[dict[str, Any]],
    status: str,
    block_reason: str | None,
) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "status": status,
        "executable": status == "ready",
        "backend_id": backend_id or None,
        "adapter_state": _adapter_state(backend) if backend else None,
        "adapter_kind": backend.get("adapter_kind") if backend else None,
        "api_key_configured": bool(_backend_api_key(backend)) if backend else False,
        "modality": contract.get("modality"),
        "backend": _public_backend(backend),
        "checks": checks,
    }
    if block_reason:
        result["block_reason"] = block_reason
    api_key_env = backend.get("api_key_env") if backend else None
    if api_key_env:
        result["api_key_env"] = api_key_env
    return result


def _public_backend(backend: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "display_name",
        "adapter_kind",
        "adapter_state",
        "api_key_env",
        "api_key_env_aliases",
        "auth_probe",
        "base_url",
        "command",
        "command_contract",
        "endpoints",
        "execution_kernel",
        "execution_mode",
        "fallback_only",
        "orchestration_scope",
        "registered_generation_models",
        "models",
        "approval_required",
        "final_artifact_allowed",
        "workflow_shell_registry",
        "workflow_shell_capability_families",
        "agentlab_boundary",
        "required_receipts",
    ]
    public = {key: backend[key] for key in keys if key in backend}
    api_key_ref = backend.get("api_key")
    if isinstance(api_key_ref, str) and api_key_ref.startswith("env:"):
        public["api_key"] = api_key_ref
    return public


def _backend_api_key(backend: dict[str, Any]) -> str:
    explicit = resolve_env_value(backend.get("api_key"), "")
    if explicit:
        return explicit
    for name in _backend_api_key_env_names(backend):
        value = os.getenv(name, "")
        if value:
            return value
    return ""


def _backend_api_key_env_names(backend: dict[str, Any]) -> list[str]:
    env_names: list[str] = []
    primary = str(backend.get("api_key_env") or "").strip()
    if primary:
        env_names.append(primary)
    aliases = backend.get("api_key_env_aliases") or []
    if isinstance(aliases, list):
        env_names.extend(str(item).strip() for item in aliases if str(item).strip())
    return list(dict.fromkeys(env_names))


def _backend_command_available(backend: dict[str, Any]) -> bool:
    command = str(backend.get("command") or "").strip()
    if not command:
        return False
    return shutil.which(command) is not None


def _adapter_state(backend: dict[str, Any]) -> str:
    configured = str(backend.get("adapter_state") or "").strip()
    if configured:
        return configured
    if backend.get("command_contract") or backend.get("adapter_kind"):
        return "configured"
    if str(backend.get("execution_mode") or "") == "harness_route":
        return "configured"
    return "missing"


def _run_command(
    args: list[str],
    timeout_seconds: int,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        cwd=cwd,
    )


def _write_generation_ledger(
    out_dir: Path,
    contract: dict[str, Any],
    preflight: dict[str, Any],
    result: dict[str, Any],
) -> None:
    generated_asset_receipts = _generated_asset_receipts(
        out_dir,
        result.get("generated_assets") or [],
    )
    result["generated_asset_receipts"] = generated_asset_receipts
    ledger = {
        "schema_version": 1,
        "contract_type": "generation_ledger",
        "backend": preflight.get("backend_id"),
        "adapter_kind": preflight.get("adapter_kind"),
        "modality": contract.get("modality"),
        "prompt_recorded": bool(contract.get("prompt")),
        "live": result.get("live", False),
        "status": result.get("status"),
        "generated_assets": result.get("generated_assets", []),
        "generated_asset_receipts": generated_asset_receipts,
        "text_artifacts": result.get("text_artifacts", []),
        "artifact_generation_verified": result.get("artifact_generation_verified"),
        "block_reason": result.get("reason") or preflight.get("block_reason"),
    }
    for key in [
        "returncode",
        "timeout_seconds",
        "stdout_excerpt",
        "stderr_excerpt",
        "settings_fetch_failed",
        "transport_failure_marker_present",
        "auth_failure_marker_present",
        "failure_scope",
        "asset_claims",
        "asset_claims_rejected",
        "asset_return_contract",
        "execution_id",
        "producer_role_session_id",
        "producer_worker",
    ]:
        if result.get(key) is not None:
            ledger[key] = result.get(key)
    atomic_write_yaml(out_dir / "generation_ledger.yml", ledger)
    _write_generated_assets_manifest(
        out_dir,
        contract,
        result,
        generated_asset_receipts,
    )
    _write_generation_receipt(
        out_dir,
        contract,
        preflight,
        result,
        generated_asset_receipts,
    )
    _write_role_session_receipt(out_dir, contract, result)


def _write_generated_assets_manifest(
    out_dir: Path,
    contract: dict[str, Any],
    result: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    media_type = _acceptance_media_type(str(contract.get("modality") or ""))
    assets = [
        {
            "candidate_id": f"asset-{str(receipt.get('sha256') or '')[:12]}",
            "path": receipt.get("path"),
            "media_type": media_type,
            "sha256": receipt.get("sha256"),
            "size_bytes": receipt.get("size_bytes"),
        }
        for receipt in receipts
    ]
    atomic_write_yaml(
        out_dir / "generated_assets_manifest.yml",
        {
            "schema_version": "generated-assets-manifest/v1",
            "status": (
                "complete"
                if assets
                else "not_required"
                if result.get("live") is False
                and result.get("status") in {"dry_run", "not_required"}
                else "blocked"
            ),
            "candidate_only": True,
            "production_modified": False,
            "assets": assets,
            "source_ledger": "generation_ledger.yml",
            "artifact_generation_verified": result.get("artifact_generation_verified"),
        },
    )


def _write_generation_receipt(
    out_dir: Path,
    contract: dict[str, Any],
    preflight: dict[str, Any],
    result: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    backend = preflight.get("backend") if isinstance(preflight.get("backend"), dict) else {}
    models = backend.get("models") if isinstance(backend.get("models"), dict) else {}
    modality = str(contract.get("modality") or "")
    model = result.get("generation_model") or models.get(modality)
    allowed_models = _allowed_generation_models(backend, modality)
    model_registered = bool(model) and model in allowed_models
    producer_id = result.get("producer_role_session_id") if result.get("live") and receipts else None
    issues: list[str] = []
    if receipts and not model:
        issues.append("actual_generation_model_missing")
    elif receipts and not model_registered:
        issues.append("generation_model_not_registered_for_backend")
    if receipts and not producer_id:
        issues.append("artifact_producer_role_session_identity_missing")
    if result.get("live") and not receipts:
        issues.append("verified_media_asset_missing")
    status = (
        "complete"
        if receipts and model and model_registered and producer_id
        else "not_required"
        if not receipts
        and result.get("live") is False
        and result.get("status") in {"dry_run", "not_required"}
        else "blocked"
    )
    prompt = str(contract.get("prompt") or "")
    atomic_write_yaml(
        out_dir / "generation_receipt.yml",
        {
            "schema_version": "generation-receipt/v1",
            "status": status,
            "producer": {
                "role": "ArtifactProducer",
                "id": producer_id,
                "execution_id": result.get("execution_id"),
                "worker": result.get("producer_worker"),
            },
            "backend": preflight.get("backend_id"),
            "model": model,
            "model_source": (
                "worker_report_marker"
                if result.get("generation_model")
                else "configured_provider_request"
                if model
                else "unknown"
            ),
            "model_registered_for_backend": model_registered if receipts else None,
            "prompt_parameters": {
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "delivery_constraints": contract.get("delivery_constraints") or {},
            },
            "reference_assets": contract.get("reference_assets") or [],
            "generated_asset_receipts": receipts,
            "candidate_only": True,
            "production_modified": False,
            "issues": issues,
        },
    )


def _write_role_session_receipt(
    out_dir: Path,
    contract: dict[str, Any],
    result: dict[str, Any],
) -> None:
    live = result.get("live") is True
    role_session_id = result.get("producer_role_session_id")
    guard = result.get("role_session_guard") if isinstance(result.get("role_session_guard"), dict) else {}
    if not live:
        status = "not_required"
        issues: list[str] = []
    elif role_session_id:
        status = "complete"
        issues = []
    else:
        status = "blocked"
        issues = [str(guard.get("reason") or "role_session_identity_missing")]
    atomic_write_yaml(
        out_dir / "role_session_receipt.yml",
        {
            "schema_version": "role-session-receipt/v1",
            "status": status,
            "role": "ArtifactProducer",
            "role_session_id": role_session_id,
            "worker": result.get("producer_worker"),
            "project": contract.get("project_id"),
            "task_id": contract.get("task_id"),
            "execution_id": result.get("execution_id"),
            "live": live,
            "issues": issues,
        },
    )


def _acceptance_media_type(modality: str) -> str:
    lowered = modality.lower()
    if "video" in lowered:
        return "video"
    if "audio" in lowered:
        return "audio"
    if lowered == "pdf":
        return "pdf"
    return "image"


def _generated_asset_receipts(
    out_dir: Path,
    generated_assets: list[Any],
) -> list[dict[str, Any]]:
    """Hash only real files inside the trusted media output directory."""

    out_root = out_dir.resolve()
    receipts: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw_path in generated_assets:
        candidate = Path(str(raw_path))
        if not candidate.is_absolute():
            candidate = out_root / candidate
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        try:
            resolved.relative_to(out_root)
        except ValueError:
            continue
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        seen.add(resolved)
        receipts.append(
            {
                "path": str(resolved),
                "sha256": digest.hexdigest(),
                "size_bytes": resolved.stat().st_size,
            }
        )
    return receipts


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI media backend HTTP {exc.code}: {body[:500]}") from exc


def _http_get(url: str, headers: dict[str, str], timeout_seconds: int) -> bytes | dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
            if "application/json" in content_type:
                return json.loads(data.decode("utf-8"))
            return data
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"xAI media backend HTTP {exc.code}: {body[:500]}") from exc
