"""Non-private Grok CLI session smoke for AgentLab acceptance evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import shlex
import shutil
import subprocess
import tempfile
from typing import Any, Callable

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]

EXPECTED = "AGENTLAB_GROK_CLI_SMOKE_OK"
PROMPT = (
    "AgentLab non-private Grok CLI session smoke. "
    f"Reply exactly: {EXPECTED}"
)
DIAGNOSTIC_TIMEOUT_SECONDS = 15
PROMPT_FLAGS = {"-p", "--prompt", "-z", "--oneshot"}
SETTINGS_FETCH_MARKER = "Settings fetch failed"
GROK_SMOKE_TEMPLATE_KEY = "session_smoke"
TRANSPORT_FAILURE_MARKERS = (
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
AUTH_FAILURE_MARKERS = (
    "not authenticated",
    "not logged in",
    "logged out",
    "missing access token",
    "missing access_token",
    "oauth session expired",
    "oauth error",
    "sign in",
    "login required",
    "unauthorized",
)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _safe_excerpt(value: str | bytes | None, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value[:limit]


def _arg_value(args: list[str], option: str) -> str | None:
    try:
        idx = args.index(option)
    except ValueError:
        return None
    if idx + 1 >= len(args):
        return None
    return args[idx + 1]


def _command_shape(args: list[str]) -> str:
    rendered: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            rendered.append(
                "<usage_report>" if rendered[-1] == "--usage-file"
                else "<non_private_prompt>"
            )
            skip_next = False
            continue
        rendered.append(arg)
        if arg in PROMPT_FLAGS or arg == "--usage-file":
            skip_next = True
    return " ".join(rendered)


def _parse_command_template(template: str) -> list[str]:
    if not template:
        return []
    try:
        args = shlex.split(template)
    except ValueError:
        return []
    rendered = [PROMPT if arg == "<prompt>" else arg for arg in args]
    return rendered if any(flag in rendered for flag in PROMPT_FLAGS) else []


def _command_variants(command_contract: dict[str, Any]) -> list[list[str]]:
    """Return only the configured Hermes smoke contract, never a direct fallback."""
    template = str(command_contract.get(GROK_SMOKE_TEMPLATE_KEY) or "")
    rendered = _parse_command_template(template)
    return [rendered] if rendered else []


def _grok_cli_failure_flags(stdout: str = "", stderr: str = "") -> dict[str, Any]:
    combined = f"{stdout}\n{stderr}".lower()
    settings_fetch_failed = SETTINGS_FETCH_MARKER.lower() in combined
    transport_failure = any(marker in combined for marker in TRANSPORT_FAILURE_MARKERS)
    auth_failure = any(marker in combined for marker in AUTH_FAILURE_MARKERS)
    reason = None
    block_scope = "local_grok_session_health"
    if transport_failure:
        reason = "grok_cli_transport_or_proxy_failed"
        block_scope = "local_grok_network_or_proxy"
    elif settings_fetch_failed:
        reason = "grok_cli_settings_fetch_failed"
    elif auth_failure:
        reason = "grok_cli_auth_session_unhealthy"
    return {
        "settings_fetch_failed": settings_fetch_failed,
        "transport_failure_marker_present": transport_failure,
        "auth_failure_marker_present": auth_failure,
        "reason": reason,
        "block_scope": block_scope,
    }


def _run_command(args: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _resolve_command_path(command: str, command_runner: CommandRunner | None) -> str | None:
    path = shutil.which(command)
    if path:
        return path
    if command_runner is not None:
        return f"<injected-runner:{command}>"
    return None


def _diagnostic_command(
    args: list[str],
    *,
    timeout_seconds: int,
    runner: CommandRunner,
) -> dict[str, Any]:
    try:
        completed = runner(args, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stderr = _safe_excerpt(exc.stderr)
        flags = _grok_cli_failure_flags(_safe_excerpt(exc.stdout), stderr)
        return {
            "command_shape": " ".join(args),
            "status": "timeout",
            "returncode": None,
            "stdout_excerpt": _safe_excerpt(exc.stdout),
            "stderr_excerpt": stderr,
            "settings_fetch_failed": flags["settings_fetch_failed"],
            "transport_failure_marker_present": flags["transport_failure_marker_present"],
            "auth_failure_marker_present": flags["auth_failure_marker_present"],
        }
    stdout = _safe_excerpt(completed.stdout)
    stderr = _safe_excerpt(completed.stderr)
    flags = _grok_cli_failure_flags(stdout, stderr)
    combined_lower = f"{stdout}\n{stderr}".lower()
    unauthenticated = any(
        marker in combined_lower
        for marker in (
            "not authenticated",
            "not logged in",
            "logged out",
            "missing access token",
            "missing access_token",
        )
    )
    logged_in = "logged in" in combined_lower and not unauthenticated
    stdout_lower = stdout.lower()
    default_model_visible = "default model" in stdout_lower or "model:" in stdout_lower
    return {
        "command_shape": " ".join(args),
        "status": "pass" if completed.returncode == 0 else "nonzero",
        "returncode": completed.returncode,
        "stdout_excerpt": stdout,
        "stderr_excerpt": stderr,
        "settings_fetch_failed": flags["settings_fetch_failed"],
        "transport_failure_marker_present": flags["transport_failure_marker_present"],
        "auth_failure_marker_present": flags["auth_failure_marker_present"],
        "logged_in_marker_present": logged_in,
        "not_authenticated_marker_present": unauthenticated,
        "default_model_marker_present": default_model_visible,
        "model_catalog_visible": default_model_visible,
    }


def _diagnostics(
    command: str,
    *,
    runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any]:
    auth_report = _diagnostic_command(
        [command, "auth", "status", "xai-oauth"],
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    auth_status = (
        "not_authenticated"
        if auth_report.get("not_authenticated_marker_present")
        else "authenticated_but_settings_fetch_failed"
        if auth_report.get("logged_in_marker_present")
        and (
            auth_report.get("settings_fetch_failed")
            or auth_report.get("transport_failure_marker_present")
        )
        else "authenticated"
        if auth_report.get("logged_in_marker_present")
        else "unknown"
    )
    settings_fetch_failed = bool(auth_report.get("settings_fetch_failed"))
    transport_failure = bool(auth_report.get("transport_failure_marker_present"))
    return {
        "scope": "non_private_local_cli_diagnostics",
        "loads_private_project_context": False,
        "commands": {"xai_oauth_status": auth_report},
        "auth_status": auth_status,
        "auth_session_healthy": auth_status == "authenticated" and not settings_fetch_failed and not transport_failure,
        "not_authenticated_marker_present": bool(auth_report.get("not_authenticated_marker_present")),
        "model_catalog_visible": False,
        "login_or_model_catalog_visible": bool(auth_report.get("logged_in_marker_present")),
        "settings_fetch_failed": settings_fetch_failed,
        "transport_failure_marker_present": transport_failure,
    }


def _run_variant(
    args: list[str],
    timeout_seconds: int,
    runner: CommandRunner,
) -> tuple[bool, subprocess.CompletedProcess[str]]:
    try:
        return False, runner(args, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return True, subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=_safe_excerpt(exc.stdout),
            stderr=_safe_excerpt(exc.stderr),
        )


def build_grok_cli_smoke_report(
    root: Path,
    *,
    live: bool = False,
    timeout_seconds: int = 60,
    include_diagnostics: bool = True,
    diagnostics_timeout_seconds: int = DIAGNOSTIC_TIMEOUT_SECONDS,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Build a Grok CLI session report without sending private project context."""
    root = root.resolve()
    config = _read_yaml(root / "config" / "media_generation_backends.yml")
    backend = ((config.get("backends") or {}).get("hermes_grok_oauth") or {})
    command = str(backend.get("command") or "")
    command_contract = backend.get("command_contract") if isinstance(backend.get("command_contract"), dict) else {}
    variants = _command_variants(
        command_contract if isinstance(command_contract, dict) else {},
    )
    contract_command = variants[0][0] if variants and variants[0] else None
    executable_matches_contract = command == "hermes" and contract_command == command
    command_path = (
        _resolve_command_path(command, command_runner)
        if executable_matches_contract
        else None
    )
    max_turns = _arg_value(variants[0], "--max-turns") if variants and variants[0] else None
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "agentlab_grok_cli_session_smoke",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "live": live,
        "prompt_scope": "non_private_session_reachability_smoke",
        "private_project_context_loaded": False,
        "secret_values_rendered": False,
        "backend_id": "hermes_grok_oauth",
        "adapter_kind": backend.get("adapter_kind"),
        "adapter_kind_legacy_aliases": ["grok_cli_oauth"] if backend.get("adapter_kind") == "local_grok_cli" else [],
        "command_variants": [
            {"command": v[0], "command_shape": _command_shape(v)} for v in variants if v
        ],
        "command": command,
        "contract_command": contract_command,
        "configured_contract_key": GROK_SMOKE_TEMPLATE_KEY,
        "command_available": bool(command_path),
        "cli_entrypoint_available": bool(command_path),
        "local_cli_entrypoint_available": bool(command_path),
        "command_path": command_path,
        "command_shape": _command_shape(variants[0]) if variants and variants[0] else _command_shape([]),
        "tested_invocation_mode": "non_interactive_prompt_contract",
        "execution_scope": "internal_local_cli_worker",
        "local_cli_entrypoint_is_internal_worker": (
            executable_matches_contract
            and backend.get("adapter_kind") in {"local_grok_cli", "grok_cli_oauth"}
            and backend.get("internal_worker") is True
            and backend.get("worker_id") == "grok"
            and backend.get("role_owner") == "ArtifactProducer"
        ),
        "local_cli_auth_mode": "oauth_cli_session",
        "local_cli_requires_api_key": False,
        "interactive_cli_entrypoint": command,
        "interactive_cli_start_is_not_task_contract_proof": True,
        "non_interactive_prompt_contract_status": "not_tested",
        "expected_stdout_token": EXPECTED,
        "timeout_seconds": timeout_seconds,
        "max_turns": max_turns,
        "attempts": [],
    }
    report_command = report["command"]
    report_command_shape = report["command_shape"]

    if not backend:
        report.update({"status": "blocked", "reason": "backend_config_missing"})
        return report
    if command != "hermes":
        report.update(
            {
                "status": "blocked",
                "reason": "grok_cli_unsupported_executable",
            }
        )
        return report
    if not variants or not variants[0]:
        report.update({"status": "blocked", "reason": "grok_cli_invalid_command_template"})
        return report
    if contract_command != command:
        report.update(
            {
                "status": "blocked",
                "reason": "grok_cli_contract_executable_mismatch",
            }
        )
        return report
    if not command_path:
        report.update({"status": "blocked", "reason": "grok_cli_not_found"})
        return report
    if not live:
        report.update(
            {
                "status": "configured",
                "reason": "dry_run_only",
                "block_scope": "not_tested",
                "evidence_interpretation": (
                    "This confirms the local Grok CLI entrypoint can be discovered. "
                    "It does not prove the AgentLab non-interactive prompt contract "
                    "can fetch settings or return artifacts."
                ),
            }
        )
        return report

    runner = command_runner or _run_command
    final_status = "blocked"
    final_reason: str | None = None
    final_attempt = None
    for attempt, args in enumerate(variants):
        if not args:
            continue
        command_path = _resolve_command_path(args[0], command_runner)
        if not command_path:
            attempt_report: dict[str, Any] = {
                "attempt": attempt,
                "live": live,
                "status": "blocked",
                "reason": "grok_cli_not_found",
                "command": args[0],
                "command_shape": _command_shape(args),
                "returncode": None,
                "stdout_excerpt": "",
                "stderr_excerpt": "",
                "settings_fetch_failed": False,
                "transport_failure_marker_present": False,
                "auth_failure_marker_present": False,
                "command_available": False,
                "command_path": None,
            }
            report["attempts"].append(attempt_report)
            if attempt + 1 >= len(variants):
                report.update(attempt_report)
                break
            continue

        executed_args = list(args)
        usage: dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix="agentlab-grok-smoke-") as temp_dir:
            usage_path = Path(temp_dir) / "hermes_usage.json"
            prompt_indexes = [
                index
                for index, value in enumerate(executed_args)
                if value in {"-z", "--oneshot"}
            ]
            if prompt_indexes:
                executed_args[prompt_indexes[0]:prompt_indexes[0]] = [
                    "--usage-file",
                    str(usage_path),
                ]
            timed_out, completed = _run_variant(
                executed_args,
                timeout_seconds,
                runner,
            )
            if usage_path.is_file() and not usage_path.is_symlink():
                try:
                    loaded_usage = json.loads(
                        usage_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError):
                    loaded_usage = {}
                if isinstance(loaded_usage, dict):
                    usage = loaded_usage
        stdout = _safe_excerpt(completed.stdout)
        stderr = _safe_excerpt(completed.stderr)
        flags = _grok_cli_failure_flags(stdout, stderr)
        expected_token_present = EXPECTED in stdout
        requested_model = _arg_value(args, "-m") or _arg_value(args, "--model")
        requested_provider = _arg_value(args, "--provider")
        reported_model = str(usage.get("model") or "").strip()
        reported_provider = str(usage.get("provider") or "").strip()
        response_metadata_observed = bool(reported_model and reported_provider)
        provider_model_binding_verified = bool(
            response_metadata_observed
            and reported_model == requested_model
            and reported_provider == requested_provider
        )
        provider_model_mismatch = bool(
            response_metadata_observed and not provider_model_binding_verified
        )

        attempt_report = {
            "attempt": attempt,
            "live": live,
            "command": args[0],
            "command_shape": _command_shape(executed_args),
            "returncode": None if timed_out else completed.returncode,
            "stdout_excerpt": stdout,
            "stderr_excerpt": stderr,
            "settings_fetch_failed": flags["settings_fetch_failed"],
            "transport_failure_marker_present": flags["transport_failure_marker_present"],
            "auth_failure_marker_present": flags["auth_failure_marker_present"],
            "command_available": True,
            "command_path": command_path,
            "expected_token_present": expected_token_present,
            "requested_model_id": requested_model,
            "requested_provider": requested_provider,
            "provider_reported_model_id": reported_model or None,
            "provider_reported_provider": reported_provider or None,
            "provider_response_metadata_observed": response_metadata_observed,
            "provider_model_binding_verified": provider_model_binding_verified,
        }

        if provider_model_mismatch:
            attempt_report["status"] = "blocked"
            attempt_report["reason"] = "grok_cli_provider_model_binding_mismatch"
            attempt_report["block_scope"] = "provider_model_binding"
            attempt_report["non_interactive_prompt_contract_status"] = "blocked"
        elif timed_out:
            timed_out_reason = flags["reason"] or "grok_cli_timeout"
            attempt_report["status"] = "pass" if expected_token_present else "blocked"
            attempt_report["reason"] = (
                "grok_cli_expected_token_observed_before_process_timeout" if expected_token_present else timed_out_reason
            )
            attempt_report["block_scope"] = flags["block_scope"]
            attempt_report["non_interactive_prompt_contract_status"] = "pass" if expected_token_present else "blocked"
        elif completed.returncode != 0:
            attempt_report["status"] = "blocked"
            attempt_report["reason"] = flags["reason"] or "grok_cli_nonzero_exit"
            attempt_report["block_scope"] = flags["block_scope"]
            attempt_report["non_interactive_prompt_contract_status"] = "blocked"
        elif expected_token_present:
            attempt_report["status"] = "pass"
            attempt_report["non_interactive_prompt_contract_status"] = "pass"
        elif flags["reason"]:
            attempt_report["status"] = "blocked"
            attempt_report["reason"] = flags["reason"]
            attempt_report["block_scope"] = flags["block_scope"]
            attempt_report["non_interactive_prompt_contract_status"] = "blocked"
        else:
            attempt_report["status"] = "warn"
            attempt_report["reason"] = "grok_cli_returned_unexpected_content"
            attempt_report["block_scope"] = "unexpected_model_output"
            attempt_report["non_interactive_prompt_contract_status"] = "warn"

        report["attempts"].append(attempt_report)
        report_update: dict[str, Any] = {
            "command": report_command,
            "command_shape": report_command_shape,
            "status": attempt_report["status"],
            "command_available": attempt_report["command_available"],
            "cli_entrypoint_available": attempt_report["command_available"],
            "local_cli_entrypoint_available": attempt_report["command_available"],
            "command_path": attempt_report["command_path"],
            "stdout_excerpt": attempt_report["stdout_excerpt"],
            "stderr_excerpt": attempt_report["stderr_excerpt"],
            "settings_fetch_failed": attempt_report["settings_fetch_failed"],
            "transport_failure_marker_present": attempt_report["transport_failure_marker_present"],
            "auth_failure_marker_present": attempt_report["auth_failure_marker_present"],
            "non_interactive_prompt_contract_status": attempt_report["non_interactive_prompt_contract_status"],
            "expected_token_present": attempt_report["expected_token_present"],
            "requested_model_id": attempt_report["requested_model_id"],
            "requested_provider": attempt_report["requested_provider"],
            "provider_reported_model_id": attempt_report[
                "provider_reported_model_id"
            ],
            "provider_reported_provider": attempt_report[
                "provider_reported_provider"
            ],
            "provider_response_metadata_observed": attempt_report[
                "provider_response_metadata_observed"
            ],
            "provider_model_binding_verified": attempt_report[
                "provider_model_binding_verified"
            ],
        }
        if attempt_report["status"] != "pass" and attempt_report.get("block_scope") is not None:
            report_update["block_scope"] = attempt_report["block_scope"]
        if attempt_report.get("reason") is not None:
            report_update["reason"] = attempt_report["reason"]
        if attempt_report.get("returncode") is not None:
            report_update["returncode"] = attempt_report["returncode"]
        report.update(report_update)

        final_status = attempt_report["status"]
        final_reason = attempt_report.get("reason")
        final_attempt = attempt_report

        if attempt_report["status"] == "pass":
            report.update(
                {
                    "evidence_interpretation": (
                        "The local Grok CLI entrypoint and the AgentLab non-interactive "
                        "prompt contract both completed for a non-private smoke prompt."
                        if expected_token_present
                        else "The smoke reached an expected-token boundary before timeout."
                    ),
                }
            )
            return report

        break

    if final_status == "warn":
        report.update(
            {
                "status": "warn",
                "reason": final_reason or "grok_cli_returned_unexpected_content",
                "block_scope": final_attempt.get("block_scope") if final_attempt else "unexpected_model_output",
                "non_interactive_prompt_contract_status": final_attempt.get("non_interactive_prompt_contract_status", "warn"),
            }
        )
    elif final_status in {"blocked", "pass"} and final_reason == "grok_cli_not_found":
        report.update({"status": final_status, "reason": final_reason, "block_scope": final_attempt.get("block_scope")})
    elif final_status == "blocked":
        report.update(
            {
                "status": "blocked",
                "reason": final_reason or "grok_cli_nonzero_exit",
                "block_scope": final_attempt.get("block_scope", "local_grok_session_health"),
                "non_interactive_prompt_contract_status": "blocked",
            }
        )
        if include_diagnostics:
            report["diagnostics"] = _diagnostics(
                report_command,
                runner=runner,
                timeout_seconds=diagnostics_timeout_seconds,
            )
            report["evidence_interpretation"] = (
                "The Grok CLI entrypoint is present, but the non-interactive "
                "AgentLab prompt contract failed before producing accepted output."
            )
    else:
        report.update({"status": final_status, "reason": final_reason})

    if final_attempt:
        report["expected_token_present"] = bool(final_attempt.get("expected_token_present", False))
        report["settings_fetch_failed"] = bool(final_attempt.get("settings_fetch_failed", False))
        report["transport_failure_marker_present"] = bool(final_attempt.get("transport_failure_marker_present", False))
        report["auth_failure_marker_present"] = bool(final_attempt.get("auth_failure_marker_present", False))
        if report.get("status") == "pass":
            report.pop("reason", None)

    if report.get("status") == "blocked" and include_diagnostics:
        report["diagnostics"] = report.get("diagnostics") or _diagnostics(
            report_command,
            runner=runner,
            timeout_seconds=diagnostics_timeout_seconds,
        )
    return report


def write_grok_cli_smoke_report(
    root: Path,
    out: Path,
    *,
    live: bool = False,
    timeout_seconds: int = 60,
    include_diagnostics: bool = True,
) -> dict[str, Any]:
    report = build_grok_cli_smoke_report(
        root,
        live=live,
        timeout_seconds=timeout_seconds,
        include_diagnostics=include_diagnostics,
    )
    write_report_yaml(out, report, root)
    return report
