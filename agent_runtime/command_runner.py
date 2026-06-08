"""Safe command runner for validation evidence.

Only explicit validation commands are executed, and only when the command
matches the allowlist policy. This module never invokes a shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import os
import shlex
import subprocess

import yaml

from atomic_io import atomic_write_text
from execution_log import append_command_record


DEFAULT_COMMAND_POLICY: dict[str, Any] = {
    "version": 1,
    "default_timeout_sec": 120,
    "allowed_executables": ["python", "python3", "pytest", "git"],
    "allowed_python_modules": ["pytest", "py_compile"],
    "blocked_executables": [
        "sudo", "rm", "mv", "cp", "curl", "wget", "bash", "sh", "zsh",
        "powershell", "pip", "npm", "pnpm", "yarn", "brew", "apt", "apt-get",
    ],
    "blocked_substrings": [
        "rm -rf", "curl |", "wget |", "sudo ", " > /", " /etc/",
        " ~/.ssh", " id_rsa",
    ],
}


def load_command_policy(agentlab_root: Path) -> dict:
    """Load config/command_policy.yml or return strict defaults."""
    path = agentlab_root / "config" / "command_policy.yml"
    if not path.exists():
        return dict(DEFAULT_COMMAND_POLICY)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return dict(DEFAULT_COMMAND_POLICY)
    policy = dict(DEFAULT_COMMAND_POLICY)
    policy.update(loaded)
    return policy


def normalize_command(command: str | list[str]) -> list[str]:
    """Normalize command text/list into argv without invoking a shell."""
    if isinstance(command, str):
        argv = shlex.split(command)
    elif isinstance(command, list):
        if not all(isinstance(item, str) for item in command):
            raise TypeError("command list must contain only strings")
        argv = list(command)
    else:
        raise TypeError("command must be a string or list[str]")
    if not argv:
        raise ValueError("empty command")
    return argv


def is_command_allowed(command: str | list[str], policy: dict) -> tuple[bool, str]:
    """Return whether command is allowed by the validation command policy."""
    try:
        argv = normalize_command(command)
    except Exception as exc:
        return False, str(exc)

    original = command if isinstance(command, str) else shlex.join(argv)
    executable = Path(argv[0]).name
    blocked_executables = set(policy.get("blocked_executables") or [])
    allowed_executables = set(policy.get("allowed_executables") or [])
    blocked_substrings = list(policy.get("blocked_substrings") or [])

    if executable in blocked_executables:
        return False, f"blocked executable: {executable}"
    for substring in blocked_substrings:
        if substring and substring in original:
            return False, f"blocked substring: {substring}"
    if executable not in allowed_executables:
        return False, f"executable is not allowlisted: {executable}"

    if executable in {"python", "python3"}:
        if len(argv) >= 3 and argv[1] == "-m":
            module = argv[2]
            allowed_modules = set(policy.get("allowed_python_modules") or [])
            if module not in allowed_modules:
                return False, f"python module is not allowlisted: {module}"
            return True, "allowed"
        if len(argv) >= 2 and argv[1] == "-c":
            return False, "python -c is not allowed"
        return False, "direct python script execution is not allowed"

    if executable == "git":
        if len(argv) < 2:
            return False, "git subcommand is required"
        if argv[1] not in {"status", "diff", "log"}:
            return False, f"git subcommand is not allowlisted: {argv[1]}"
        return True, "allowed"

    if executable == "pytest":
        return True, "allowed"

    return True, "allowed"


def safe_resolve_cwd(cwd: str | Path | None, workspace_root: Path) -> Path:
    """Resolve cwd and ensure it stays under workspace_root."""
    root = workspace_root.resolve()
    candidate = root if cwd is None else Path(cwd)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"cwd escapes workspace_root: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(f"cwd does not exist: {resolved}")
    return resolved


def _sha256_text(text: str | bytes | None) -> str:
    if text is None:
        raw = b""
    elif isinstance(text, bytes):
        raw = text
    else:
        raw = text.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_logged_command(
    *,
    agentlab_root: Path,
    run_dir: Path,
    command: str | list[str],
    cwd: str | Path | None = None,
    workspace_root: Path | None = None,
    node: str = "VALIDATION",
    agent: str = "TesterAuditor",
    timeout_sec: int = 120,
    env: dict[str, str] | None = None,
    allow_nonzero: bool = False,
) -> dict[str, Any]:
    """Run one allowlisted command and append a structured execution record."""
    policy = load_command_policy(agentlab_root)
    try:
        argv = normalize_command(command)
    except Exception as exc:
        return {
            "command_id": None,
            "exit_code": None,
            "blocked_by_policy": True,
            "blocked_reason": str(exc),
        }

    allowed, reason = is_command_allowed(command, policy)
    if not allowed:
        return {
            "command_id": None,
            "exit_code": None,
            "blocked_by_policy": True,
            "blocked_reason": reason,
        }

    root = workspace_root or agentlab_root
    resolved_cwd = safe_resolve_cwd(cwd, root)
    run_dir.mkdir(parents=True, exist_ok=True)

    safe_env = os.environ.copy()
    if env:
        safe_env.update({str(k): str(v) for k, v in env.items()})

    command_text = shlex.join(argv)
    timed_out = False
    exit_code: int | None
    stdout = ""
    stderr = ""
    status = "success"

    try:
        completed = subprocess.run(
            argv,
            cwd=str(resolved_cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
            env=safe_env,
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if exit_code != 0:
            status = "failed" if not allow_nonzero else "nonzero_allowed"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        status = "timeout"
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)

    record = {
        "node": node,
        "agent": agent,
        "command": command_text,
        "argv": argv,
        "cwd": str(resolved_cwd),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_sec": timeout_sec,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
    }
    command_id = append_command_record(run_dir, record)
    stdout_path = f"command_logs/{command_id}.stdout.txt"
    stderr_path = f"command_logs/{command_id}.stderr.txt"

    return {
        "command_id": command_id,
        "command": command_text,
        "argv": argv,
        "cwd": str(resolved_cwd),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "blocked_by_policy": False,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
    }


def load_validation_commands(run_dir: Path) -> dict | None:
    """Load optional validation_commands.yml from a task run directory."""
    path = run_dir / "validation_commands.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("validation_commands.yml must be a mapping")
    return data


def _format_command_summary(results: list[dict[str, Any]], all_required_passed: bool) -> str:
    lines = ["", "## Command Execution Evidence", ""]
    for item in results:
        result = item["result"]
        lines.extend([
            f"- command_id: {result.get('command_id')}",
            f"  - name: {item.get('name')}",
            f"  - command: `{result.get('command') or item.get('command')}`",
            f"  - exit_code: {result.get('exit_code')}",
            f"  - timed_out: {str(result.get('timed_out', False)).lower()}",
            f"  - stdout: `{result.get('stdout_path')}`",
            f"  - stderr: `{result.get('stderr_path')}`",
        ])
        if result.get("blocked_by_policy"):
            lines.append(f"  - blocked_reason: {result.get('blocked_reason')}")
    lines.append("")
    if all_required_passed:
        lines.append("Result: all required validation commands passed.")
    else:
        lines.append("Result: required validation commands failed.")
    lines.append("")
    return "\n".join(lines)


def run_validation_commands_if_present(
    *,
    agentlab_root: Path,
    run_dir: Path,
    workspace_root: Path,
    node: str = "VALIDATION",
    agent: str = "TesterAuditor",
) -> dict:
    """Run explicit validation_commands.yml commands, if configured."""
    config = load_validation_commands(run_dir)
    if config is None:
        return {
            "ran": False,
            "results": [],
            "all_required_passed": True,
            "failed_required": [],
            "summary_markdown": "",
        }

    configured_root = config.get("workspace_root", ".")
    effective_workspace = safe_resolve_cwd(configured_root, workspace_root)
    results: list[dict[str, Any]] = []
    failed_required: list[dict[str, Any]] = []

    commands = config.get("commands") or []
    if not isinstance(commands, list):
        raise ValueError("validation_commands.yml commands must be a list")

    policy = load_command_policy(agentlab_root)
    default_timeout = int(policy.get("default_timeout_sec", 120))

    for index, item in enumerate(commands):
        if not isinstance(item, dict):
            raise ValueError("validation command entries must be mappings")
        name = str(item.get("name") or f"command_{index + 1}")
        command = item.get("command")
        required = bool(item.get("required", False))
        timeout_sec = int(item.get("timeout_sec") or default_timeout)
        result = run_logged_command(
            agentlab_root=agentlab_root,
            run_dir=run_dir,
            command=command,
            cwd=item.get("cwd", "."),
            workspace_root=effective_workspace,
            node=node,
            agent=agent,
            timeout_sec=timeout_sec,
        )
        entry = {
            "name": name,
            "command": command,
            "required": required,
            "result": result,
        }
        results.append(entry)
        passed = (
            not result.get("blocked_by_policy")
            and result.get("exit_code") == 0
            and not result.get("timed_out")
        )
        if required and not passed:
            failed_required.append(entry)

    summary_markdown = _format_command_summary(results, not failed_required)
    atomic_write_text(run_dir / "validation_command_summary.md", summary_markdown)
    return {
        "ran": True,
        "results": results,
        "all_required_passed": not failed_required,
        "failed_required": failed_required,
        "summary_markdown": summary_markdown,
    }
