"""Failure event capture: standardized failure record structure."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_runtime.recovery.redaction import redact_context_text


@dataclass
class FailureEvent:
    """Standardized failure event structure for recovery analysis."""

    task_id: str
    project: str
    stage: str
    command: str | None
    exit_code: int | None
    error_type: str | None
    stdout_tail: str | None
    stderr_tail: str | None
    artifact_paths: list[str]
    context_pack_path: str | None
    cost_ledger_path: str | None
    resource_ledger_path: str | None
    created_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "project": self.project,
            "stage": self.stage,
            "command": self.command,
            "exit_code": self.exit_code,
            "error_type": self.error_type,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "artifact_paths": self.artifact_paths,
            "context_pack_path": self.context_pack_path,
            "cost_ledger_path": self.cost_ledger_path,
            "resource_ledger_path": self.resource_ledger_path,
            "created_at": self.created_at,
        }

    def to_json_path(self, run_dir: Path) -> Path:
        """Return path for failure_event.json within run directory."""
        recovery_dir = run_dir / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        return recovery_dir / "failure_event.json"


def create_failure_event(
    task_id: str,
    project: str,
    stage: str,
    command: str | None,
    exit_code: int | None,
    stdout: str | None = None,
    stderr: str | None = None,
    stdout_tail_chars: int = 8000,
    stderr_tail_chars: int = 8000,
    artifact_paths: list[str] | None = None,
    context_pack_path: str | None = None,
    cost_ledger_path: str | None = None,
    resource_ledger_path: str | None = None,
    error_type: str | None = None,
) -> FailureEvent:
    """Create a FailureEvent from command execution results.

    Args:
        task_id: Task identifier
        project: Project name
        stage: Pipeline stage name
        command: Command that failed
        exit_code: Exit code from command
        stdout: Full stdout output (truncated before storage)
        stderr: Full stderr output (truncated before storage)
        stdout_tail_chars: Maximum chars for stdout tail
        stderr_tail_chars: Maximum chars for stderr tail
        artifact_paths: List of artifact paths involved
        context_pack_path: Path to context pack if exists
        cost_ledger_path: Path to cost ledger if exists
        resource_ledger_path: Path to resource ledger if exists
        error_type: Optional error type string

    Returns:
        FailureEvent with redacted and truncated content
    """
    if artifact_paths is None:
        artifact_paths = []

    # Truncate and redact stdout/stderr
    stdout_tail = _truncate_and_redact(stdout, stdout_tail_chars)
    stderr_tail = _truncate_and_redact(stderr, stderr_tail_chars)

    # Convert absolute paths to relative where possible
    relative_artifacts = _relative_paths(artifact_paths)
    relative_context = _relative_path_or_none(context_pack_path)
    relative_cost = _relative_path_or_none(cost_ledger_path)
    relative_resource = _relative_path_or_none(resource_ledger_path)

    return FailureEvent(
        task_id=task_id,
        project=project,
        stage=stage,
        command=command,
        exit_code=exit_code,
        error_type=error_type,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        artifact_paths=relative_artifacts,
        context_pack_path=relative_context,
        cost_ledger_path=relative_cost,
        resource_ledger_path=relative_resource,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _truncate_and_redact(text: str | None, max_chars: int) -> str | None:
    """Truncate text to max_chars and redact secrets.

    Args:
        text: Input text or None
        max_chars: Maximum characters in output

    Returns:
        Redacted and truncated text, or None if input is None
    """
    if text is None:
        return None

    # First redact secrets
    redacted, _ = redact_context_text(text)

    # Then truncate to max chars from the end
    if len(redacted) > max_chars:
        return redacted[-max_chars:]

    return redacted


def _relative_paths(paths: list[str]) -> list[str]:
    """Convert absolute paths to relative paths where possible.

    For security, redact absolute paths that are not under common roots.
    This prevents exposing user's local file system structure.

    Args:
        paths: List of absolute or relative paths

    Returns:
        List of paths (relative or redacted for security)
    """
    result = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_absolute():
            # Redact absolute paths to avoid exposing user's file system
            result.append("[REDACTED_PATH]")
        else:
            result.append(path_str)
    return result


def _relative_path_or_none(path: str | None) -> str | None:
    """Convert single path to relative or return None.

    Args:
        path: Absolute or relative path or None

    Returns:
        Relative path string or None
    """
    if path is None:
        return None
    return _relative_paths([path])[0]


def extract_error_type_from_stderr(stderr: str | None) -> str | None:
    """Extract a high-level error type from stderr content.

    Args:
        stderr: Stderr content from failed command

    Returns:
        High-level error type string, or None if cannot determine
    """
    if not stderr:
        return None

    # Try common Python exception types
    exception_patterns = [
        ("SyntaxError", "syntax_error"),
        ("IndentationError", "syntax_error"),
        ("ModuleNotFoundError", "import_error"),
        ("ImportError", "import_error"),
        ("TypeError", "type_error"),
        ("ValueError", "value_error"),
        ("FileNotFoundError", "missing_artifact"),
        ("PermissionError", "permission_error"),
        ("TimeoutError", "timeout"),
        ("yaml.parser.ParserError", "yaml_parse_failure"),
        ("yaml.scanner.ScannerError", "yaml_parse_failure"),
    ]

    for exc_name, error_type in exception_patterns:
        if exc_name in stderr:
            return error_type

    # Try common failure patterns - order matters, more specific first
    failure_patterns = [
        (r"text integrity.*fail", "text_integrity_failure"),
        (r"remote.*raw.*fail", "remote_raw_failure"),
        (r"secret.*leak|secret.*detector", "secret_leak_risk"),
        (r"context missing", "context_missing"),
        (r"context budget", "context_budget_exceeded"),
        (r"resource.*limit|out of memory", "resource_limit"),
        (r"network.*unavailable|connection.*refused", "network_disabled_or_unavailable"),
        (r"FAILED", "test_failure"),
        (r"pytest.*FAILED", "test_failure"),
    ]

    for pattern, error_type in failure_patterns:
        if re.search(pattern, stderr, re.IGNORECASE):
            return error_type

    return None
