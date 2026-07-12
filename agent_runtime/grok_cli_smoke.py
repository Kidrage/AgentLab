"""Non-private Grok CLI session smoke for AgentLab acceptance evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shlex
import shutil
import subprocess
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
GROK_SMOKE_TEMPLATE_KEYS = ("session_smoke", "oauth_smoke", "hermes_session_smoke", "hermes_smoke_session")
SETTINGS_FAILURE_RETRYABLE = {
    "grok_cli_transport_or_proxy_failed",
    "grok_cli_settings_fetch_failed",
    "grok_cli_auth_session_unhealthy",
    "grok_cli_nonzero_exit",
    "grok_cli_timeout",
}
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
            rendered.append("<non_private_prompt>")
            skip_next = False
            continue
        rendered.append(arg)
        if arg in PROMPT_FLAGS:
            skip_next = True
    return " ".join(rendered)


def _parse_command_template(base_command: str, template: str) -> list[str]:
    if not template:
        return []
    try:
        args = shlex.split(template)
    except ValueError:
        return []
    rendered = [PROMPT if arg == "<prompt>" else arg for arg in args]
    return rendered if any(flag in rendered for flag in PROMPT_FLAGS) else []


def _coalesce_variants(variants: list[list[str]]) -> list[list[str]]:
    deduped: list[list[str]] = []
    for candidate in variants:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _command_variants(command: str, command_contract: dict[str, Any], fallback_prompt: str) -> list[list[str]]:
    templates: list[str] = []
    for key in GROK_SMOKE_TEMPLATE_KEYS:
        contract_template = str(command_contract.get(key) or "")
        if contract_template:
            templates.append(contract_template)

    # Existing contract may only provide oauth/session keys; preserve them as primary.
    if not templates and (command == "hermes" or "grok" in command):
        templates.append(f"{command} -p <prompt> --output-format plain --max-turns 3")

    # If hermes is the primary command, add a direct grok smoke fallback that often
    # bypasses hermes session transport restrictions.
    if command == "hermes":
        fallback = "grok -p <prompt> --output-format plain --max-turns 3"
        if fallback not in templates:
            templates.append(fallback)

    variants: list[list[str]] = []
    for template in templates:
        rendered = _parse_command_template(command, template)
        if rendered:
            variants.append(rendered)

    if not variants:
        variants.append([command, "-p", fallback_prompt, "--output-format", "plain", "--max-turns", "3"])
    return _coalesce_variants(variants)


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
    stdout_lower = stdout.lower()
    stderr_lower = stderr.lower()
    unauthenticated = "not authenticated" in stdout_lower or "not authenticated" in stderr_lower
    logged_in = "logged in" in stdout_lower and not unauthenticated
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
    if command == "hermes":
        inspect_args = [command, "status"]
        models_args = [command, "auth", "list"]
        command_labels = ("status", "auth_list")
    else:
        inspect_args = [command, "inspect"]
        models_args = [command, "models"]
        command_labels = ("inspect", "models")
    inspect_report = _diagnostic_command(
        inspect_args,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    models_report = _diagnostic_command(
        models_args,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    auth_status = (
        "not_authenticated"
        if models_report.get("not_authenticated_marker_present")
        else "authenticated_but_settings_fetch_failed"
        if models_report.get("logged_in_marker_present")
        and (models_report.get("settings_fetch_failed") or inspect_report.get("settings_fetch_failed"))
        else "authenticated"
        if models_report.get("logged_in_marker_present")
        else "unknown"
    )
    settings_fetch_failed = bool(
        inspect_report.get("settings_fetch_failed")
        or models_report.get("settings_fetch_failed")
    )
    transport_failure = bool(
        inspect_report.get("transport_failure_marker_present")
        or models_report.get("transport_failure_marker_present")
    )
    return {
        "scope": "non_private_local_cli_diagnostics",
        "loads_private_project_context": False,
        "commands": {
            command_labels[0]: inspect_report,
            command_labels[1]: models_report,
        },
        "auth_status": auth_status,
        "auth_session_healthy": auth_status == "authenticated" and not settings_fetch_failed and not transport_failure,
        "not_authenticated_marker_present": bool(models_report.get("not_authenticated_marker_present")),
        "model_catalog_visible": bool(
            inspect_report.get("model_catalog_visible")
            or models_report.get("model_catalog_visible")
        ),
        "login_or_model_catalog_visible": bool(
            inspect_report.get("logged_in_marker_present")
            or inspect_report.get("default_model_marker_present")
            or models_report.get("logged_in_marker_present")
            or models_report.get("default_model_marker_present")
        ),
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
    command = str(backend.get("command") or "grok")
    command_contract = backend.get("command_contract") if isinstance(backend.get("command_contract"), dict) else {}
    variants = _command_variants(
        command,
        command_contract if isinstance(command_contract, dict) else {},
        PROMPT,
    )
    fallback_prompt = f"{command} -p <prompt> --output-format plain --max-turns 3"
    if not variants:
        variants.append(_parse_command_template(command, fallback_prompt))
    command_path = shutil.which(variants[0][0]) if variants and variants[0] else None
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
        "command": variants[0][0] if variants and variants[0] else command,
        "command_available": bool(command_path),
        "cli_entrypoint_available": bool(command_path),
        "local_cli_entrypoint_available": bool(command_path),
        "command_path": command_path,
        "command_shape": _command_shape(variants[0]) if variants and variants[0] else _command_shape([]),
        "tested_invocation_mode": "non_interactive_prompt_contract",
        "execution_scope": "internal_local_cli_worker",
        "local_cli_entrypoint_is_internal_worker": (
            backend.get("adapter_kind") in {"local_grok_cli", "grok_cli_oauth"}
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
    if not variants or not variants[0]:
        report.update({"status": "blocked", "reason": "grok_cli_invalid_command_template"})
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
        command_path = shutil.which(args[0])
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

        timed_out, completed = _run_variant(args, timeout_seconds, runner)
        stdout = _safe_excerpt(completed.stdout)
        stderr = _safe_excerpt(completed.stderr)
        flags = _grok_cli_failure_flags(stdout, stderr)
        expected_token_present = EXPECTED in stdout

        attempt_report = {
            "attempt": attempt,
            "live": live,
            "command": args[0],
            "command_shape": _command_shape(args),
            "returncode": None if timed_out else completed.returncode,
            "stdout_excerpt": stdout,
            "stderr_excerpt": stderr,
            "settings_fetch_failed": flags["settings_fetch_failed"],
            "transport_failure_marker_present": flags["transport_failure_marker_present"],
            "auth_failure_marker_present": flags["auth_failure_marker_present"],
            "command_available": True,
            "command_path": command_path,
            "expected_token_present": expected_token_present,
        }

        if timed_out:
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

        if (
            attempt_report["status"] == "warn"
            or attempt_report["reason"] not in SETTINGS_FAILURE_RETRYABLE
            or attempt + 1 >= len(variants)
        ):
            break

        # Retry using fallback command variant (typically direct grok fallback for hermes session).
        continue

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
