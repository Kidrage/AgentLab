"""Non-private Agy Observer session smoke for AgentLab acceptance evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shlex
import shutil
import subprocess
from typing import Any, Callable

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

EXPECTED = "AGENTLAB_AGY_CLI_SMOKE_OK"
_DIRECT_GEMINI_API_KEY_ENV_VARS = {
    "GEMINI_API_KEY",
    "GENAI_API_KEY",
    "GOOGLE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_GENAI_API_KEY",
}
_PROXY_ENV_VARS = (
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


def _is_direct_gemini_api_key_environment(name: str) -> bool:
    normalized = str(name).strip().upper()
    if normalized in _DIRECT_GEMINI_API_KEY_ENV_VARS:
        return True
    return "API_KEY" in normalized and any(
        marker in normalized
        for marker in ("GEMINI", "GENAI", "GENERATIVE_AI", "GOOGLE")
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


def _command_shape(args: list[str]) -> str:
    rendered: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            rendered.append("<non_private_prompt>")
            skip_next = False
            continue
        rendered.append(arg)
        if arg == "-p":
            skip_next = True
    return " ".join(rendered)


def _classify_failure(stderr: str, log_excerpt: str) -> str:
    combined = f"{stderr}\n{log_excerpt}"
    if "listen tcp 127.0.0.1:0" in combined and "operation not permitted" in combined:
        return "agy_localhost_bind_denied"
    if "oauth_session_or_region_blocked" in combined:
        return "agy_oauth_session_or_region_blocked"
    if "Settings fetch failed" in combined:
        return "agy_settings_fetch_failed"
    return "agy_cli_nonzero_exit"


def _write_task_packet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "packet_type": "agentlab_non_private_cli_smoke",
                "project": "AgentLab",
                "task_id": "agy_cli_session_smoke",
                "role": "Observer",
                "prompt_scope": "non_private_observer_session_reachability_smoke",
                "private_project_context_loaded": False,
                "instructions": (
                    f"Reply exactly: {EXPECTED}. Do not read project files, do not edit files, "
                    "and do not execute additional commands."
                ),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _run_command(args: list[str], timeout_seconds: int, log_path: Path) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    for name in list(process_env):
        if _is_direct_gemini_api_key_environment(name):
            process_env.pop(name, None)
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=process_env,
    )


def _resolve_command_path(command: str, command_runner: CommandRunner | None) -> str | None:
    path = shutil.which(command)
    if path:
        return path
    if command_runner is not None:
        return f"<injected-runner:{command}>"
    return None


def _contract_template(root: Path) -> str:
    data = _read_yaml(root / "config" / "worker_invocation_contracts.yml")
    contract = ((data.get("contracts") or {}).get("agy_observer") or {})
    return str(contract.get("template") or "")


def _default_model_id(root: Path) -> str:
    data = _read_yaml(root / "config" / "model_catalog.yml")
    provider = ((data.get("providers") or {}).get("agy_gemini_oauth") or {})
    return str(
        provider.get("cli_model_id")
        or provider.get("default_model")
        or ""
    )


def _append_log_file(args: list[str], log_path: Path) -> list[str]:
    return [*args, "--log-file", str(log_path)]


def _command_variants(root: Path, task_packet: Path, log_path: Path) -> list[list[str]]:
    template = _contract_template(root)
    model_id = _default_model_id(root)
    if not template or not model_id:
        return []
    try:
        rendered = template.format(
            task_packet_path=str(task_packet),
            model_id=model_id,
        )
        parsed = shlex.split(rendered)
    except (KeyError, ValueError):
        return []
    if not parsed or parsed[0] != "agy" or "--sandbox" not in parsed:
        return []
    return [_append_log_file(parsed, log_path)]


def _run_single_variant(
    args: list[str],
    runner: CommandRunner,
    timeout_seconds: int,
    log_path: Path,
) -> tuple[bool, subprocess.CompletedProcess[str]]:
    try:
        completed = runner(args, timeout_seconds, log_path)
        return False, completed
    except subprocess.TimeoutExpired as exc:
        return True, subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=_safe_excerpt(exc.stdout),
            stderr=_safe_excerpt(exc.stderr),
        )


def _build_attempt_report(
    attempt: int,
    args: list[str],
    timed_out: bool,
    completed: subprocess.CompletedProcess[str],
    log_path: Path,
    live: bool,
) -> dict[str, Any]:
    stdout = _safe_excerpt(completed.stdout)
    stderr = _safe_excerpt(completed.stderr)
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    log_excerpt = _safe_excerpt(log_text)
    model_resolution_failed = (
        "failed to resolve model flag" in log_text.lower()
        or "is not recognized as a known model" in log_text.lower()
    )
    expected = EXPECTED in stdout
    status = "warn"
    reason = None
    process_exit_status = "completed"
    if model_resolution_failed:
        process_exit_status = "model_resolution_failed"
        status = "blocked"
        reason = "agy_model_flag_unresolved"
    elif timed_out:
        process_exit_status = "timeout_after_expected_token" if expected else "timeout"
        status = "pass" if expected else "blocked"
        reason = "agy_cli_expected_token_observed_before_process_timeout" if expected else "agy_cli_timeout"
    elif completed.returncode != 0:
        reason = _classify_failure(stderr, log_excerpt)
        status = "blocked"
    elif expected:
        status = "pass"
    else:
        reason = "agy_cli_returned_unexpected_content"
        status = "warn"

    return {
        "attempt": attempt,
        "live": live,
        "command": args[0] if args else "agy",
        "command_shape": _command_shape(args),
        "status": status,
        "reason": reason,
        "returncode": None if timed_out else completed.returncode,
        "stdout_excerpt": stdout,
        "stderr_excerpt": stderr,
        "log_excerpt": log_excerpt,
        "expected_token_present": expected,
        "model_resolution_failed": model_resolution_failed,
        "process_exit_status": process_exit_status,
    }


def build_agy_cli_smoke_report(
    root: Path,
    *,
    live: bool = False,
    timeout_seconds: int = 60,
    command_runner: CommandRunner | None = None,
    smoke_dir: Path | None = None,
) -> dict[str, Any]:
    """Build an Agy CLI session report without sending private project context."""
    root = root.resolve()
    smoke_dir = (
        smoke_dir.resolve()
        if smoke_dir is not None
        else root / "acceptance_runs" / "agentlab_capability_acceptance" / "agy_cli_session_smoke"
    )
    task_packet = smoke_dir / "task_packet.yml"
    log_path = smoke_dir / "agy_cli_smoke.log"
    _write_task_packet(task_packet)
    proxy_environment_names = sorted(
        name for name in _PROXY_ENV_VARS if str(os.environ.get(name) or "").strip()
    )
    proxy_binding_verified = bool(proxy_environment_names)
    command_variants = _command_variants(root, task_packet, log_path)
    if not command_variants or not command_variants[0]:
        return {
            "schema_version": 1,
            "report_type": "agentlab_agy_cli_session_smoke",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "live": live,
            "status": "blocked",
            "reason": "agy_cli_invalid_command_template",
            "prompt_scope": "non_private_observer_session_reachability_smoke",
            "private_project_context_loaded": False,
            "secret_values_rendered": False,
            "proxy_binding_verified": proxy_binding_verified,
            "proxy_environment_names": proxy_environment_names,
            "worker": "agy",
            "invocation_contract": "agy_observer",
            "expected_stdout_token": EXPECTED,
            "task_packet_path": str(task_packet),
            "log_path": str(log_path),
            "timeout_seconds": timeout_seconds,
            "command_variants": [],
            "attempts": [],
        }

    first_args = command_variants[0]
    first_path = _resolve_command_path(first_args[0], command_runner) if first_args else None
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "agentlab_agy_cli_session_smoke",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "live": live,
        "status": "blocked",
        "prompt_scope": "non_private_observer_session_reachability_smoke",
        "private_project_context_loaded": False,
        "secret_values_rendered": False,
        "proxy_binding_verified": proxy_binding_verified,
        "proxy_environment_names": proxy_environment_names,
        "worker": "agy",
        "invocation_contract": "agy_observer",
        "command": first_args[0],
        "command_available": bool(first_path),
        "command_path": first_path,
        "command_shape": _command_shape(first_args),
        "expected_stdout_token": EXPECTED,
        "task_packet_path": str(task_packet),
        "log_path": str(log_path),
        "timeout_seconds": timeout_seconds,
        "command_variants": [
            {"command": args[0], "command_shape": _command_shape(args), "with_log_file": True}
            for args in command_variants
        ],
        "attempts": [],
    }
    if not first_path:
        report.update({"status": "blocked", "reason": "agy_cli_not_found"})
        return report

    if not proxy_binding_verified:
        report.update(
            {
                "status": "blocked",
                "reason": "agy_oauth_proxy_environment_missing",
            }
        )
        return report

    if not live:
        report.update({"status": "configured", "reason": "dry_run_only"})
        return report

    runner = command_runner or _run_command
    for attempt, args in enumerate(command_variants):
        if not args:
            continue
        command_path = _resolve_command_path(args[0], command_runner)
        if not command_path:
            attempt_report = {
                "attempt": attempt,
                "live": live,
                "command": args[0],
                "command_shape": _command_shape(args),
                "status": "blocked",
                "reason": "agy_cli_not_found",
                "returncode": None,
                "stdout_excerpt": "",
                "stderr_excerpt": "",
                "log_excerpt": "",
                "expected_token_present": False,
                "process_exit_status": "command_missing",
            }
            report["attempts"].append(attempt_report)
            if attempt + 1 >= len(command_variants):
                report.update(
                    {
                        "status": "blocked",
                        "reason": "agy_cli_not_found",
                        "command": args[0],
                        "command_shape": _command_shape(args),
                        "command_available": False,
                    }
                )
                return report
            continue

        log_path.unlink(missing_ok=True)
        timed_out, completed = _run_single_variant(args, runner, timeout_seconds, log_path)
        attempt_report = _build_attempt_report(
            attempt=attempt,
            args=args,
            timed_out=timed_out,
            completed=completed,
            log_path=log_path,
            live=live,
        )
        attempt_report["command_path"] = command_path
        attempt_report["command_available"] = True

        report["attempts"].append(attempt_report)
        report_update: dict[str, Any] = {
            "command": attempt_report["command"],
            "command_shape": attempt_report["command_shape"],
            "command_path": command_path,
            "command_available": True,
            "status": attempt_report["status"],
            "stdout_excerpt": attempt_report["stdout_excerpt"],
            "stderr_excerpt": attempt_report["stderr_excerpt"],
            "log_excerpt": attempt_report["log_excerpt"],
            "expected_token_present": attempt_report["expected_token_present"],
            "process_exit_status": attempt_report["process_exit_status"],
        }
        if attempt_report.get("reason") is not None:
            report_update["reason"] = attempt_report["reason"]
        if attempt_report.get("returncode") is not None:
            report_update["returncode"] = attempt_report["returncode"]
        report.update(report_update)

        if attempt_report["status"] == "pass":
            return report

        break

    return report


def write_agy_cli_smoke_report(
    root: Path,
    out: Path,
    *,
    live: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    report = build_agy_cli_smoke_report(
        root,
        live=live,
        timeout_seconds=timeout_seconds,
        smoke_dir=out.parent / out.stem,
    )
    write_report_yaml(out, report, root)
    return report
