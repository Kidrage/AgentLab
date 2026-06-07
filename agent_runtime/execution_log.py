"""Execution Log — minimal evidence trail for commands claimed in reports.

Provides helpers to append, load, and query structured command records
so that validation/audit reports can reference evidence of actual execution.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import yaml

_EXECUTION_LOG_FILENAME = "execution_log.yml"
_COMMAND_LOGS_DIR = "command_logs"


def _execution_log_path(run_dir: Path) -> Path:
    return run_dir / _EXECUTION_LOG_FILENAME


def _command_logs_dir(run_dir: Path) -> Path:
    return run_dir / _COMMAND_LOGS_DIR


def load_execution_log(run_dir: Path) -> dict:
    """Load execution_log.yml. Returns empty dict if not present."""
    path = _execution_log_path(run_dir)
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_execution_log(run_dir: Path, log: dict) -> None:
    """Save execution log to execution_log.yml."""
    _execution_log_path(run_dir).parent.mkdir(parents=True, exist_ok=True)
    from atomic_io import atomic_write_text
    atomic_write_text(
        _execution_log_path(run_dir),
        yaml.safe_dump(log, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def append_command_record(run_dir: Path, record: dict) -> str:
    """Append a command record to the execution log.

    Returns the command_id of the appended record.
    Automatically assigns a sequential command_id if not provided.
    """
    log = load_execution_log(run_dir)
    if not log:
        log = {"version": 1, "commands": []}

    commands = log.get("commands", [])
    record = dict(record)  # shallow copy

    # Auto-assign command_id
    if "command_id" not in record:
        next_id = len(commands) + 1
        record["command_id"] = f"cmd_{next_id:04d}"

    # Auto-timestamp
    if "started_at" not in record:
        record["started_at"] = datetime.now(timezone.utc).isoformat()
    if "completed_at" not in record:
        record["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Write stdout/stderr to files and record sha256
    stdout = record.get("stdout")
    stderr = record.get("stderr")
    logs_dir = _command_logs_dir(run_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    cmd_id = record["command_id"]

    if stdout is not None:
        stdout_path = logs_dir / f"{cmd_id}.stdout.txt"
        stdout_bytes = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
        stdout_path.write_bytes(stdout_bytes)
        record["stdout_path"] = str(stdout_path.relative_to(run_dir))
        record["stdout_sha256"] = hashlib.sha256(stdout_bytes).hexdigest()
        record.pop("stdout", None)

    if stderr is not None:
        stderr_path = logs_dir / f"{cmd_id}.stderr.txt"
        stderr_bytes = stderr.encode("utf-8") if isinstance(stderr, str) else stderr
        stderr_path.write_bytes(stderr_bytes)
        record["stderr_path"] = str(stderr_path.relative_to(run_dir))
        record["stderr_sha256"] = hashlib.sha256(stderr_bytes).hexdigest()
        record.pop("stderr", None)

    commands.append(record)
    log["commands"] = commands
    save_execution_log(run_dir, log)

    return cmd_id


def has_successful_command(run_dir: Path, command_id: str | None = None) -> bool:
    """Check if there's at least one command with exit_code=0.

    If command_id is provided, check that specific command.
    """
    log = load_execution_log(run_dir)
    commands = log.get("commands", [])
    if not commands:
        return False
    if command_id:
        for cmd in commands:
            if cmd.get("command_id") == command_id:
                return cmd.get("exit_code") == 0
        return False
    return any(cmd.get("exit_code") == 0 for cmd in commands)


def get_command_by_id(run_dir: Path, command_id: str) -> dict | None:
    """Retrieve a single command record by command_id."""
    log = load_execution_log(run_dir)
    for cmd in log.get("commands", []):
        if cmd.get("command_id") == command_id:
            return cmd
    return None