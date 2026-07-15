"""Safe CLI quota probes and normalized subscription capacity snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import pty
import re
import select
import subprocess
import time
from typing import Any, Mapping

from agent_runtime.runtime_registry import QuotaSnapshot, QuotaWindow, utc_timestamp


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
SAFE_SLASH_COMMANDS = {"/usage", "/quota", "/status", "/stats"}
SAFE_EXIT_COMMANDS = {"/exit", "/quit"}
SAFE_SHELLS = {"hermes", "agy", "claude", "codex", "grok", "qwen"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _duration_reset(text: str, observed_at: datetime) -> datetime | None:
    match = re.search(
        r"(?:reset|resets|refresh|refreshes)\s+(?:at\s+)?in\s+"
        r"(?:(\d+(?:\.\d+)?)\s*(?:days?|d))?\s*"
        r"(?:(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h))?\s*"
        r"(?:(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m))?\s*"
        r"(?:(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s))?",
        text,
        re.I,
    )
    if match and any(match.groups()):
        days, hours, minutes, seconds = (float(item or 0) for item in match.groups())
        return observed_at + timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
        )
    retry = re.search(
        r"(?:retry|available)\s+(?:after|in)\s+(\d+(?:\.\d+)?)\s*(d|h|m|s|days?|hours?|minutes?|seconds?)",
        text,
        re.I,
    )
    if retry:
        value = float(retry.group(1))
        unit = retry.group(2).lower()
        seconds = value * (
            86400
            if unit.startswith("d")
            else 3600
            if unit.startswith("h")
            else 60
            if unit.startswith("m")
            else 1
        )
        return observed_at + timedelta(seconds=seconds)
    return None


def _absolute_reset(text: str) -> datetime | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?(?:Z|[+-]\d{2}:?\d{2})?)", text)
    if not match:
        return None
    value = match.group(1).replace(" ", "T")
    if re.fullmatch(r".*T\d{2}:\d{2}", value):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _window_name(line: str, index: int) -> str:
    lowered = line.lower()
    for name, markers in (
        ("five_hour", ("5-hour", "5 hour", "5h")),
        ("weekly", ("weekly", "week")),
        ("daily", ("daily", "day")),
        ("monthly", ("monthly", "month")),
    ):
        if any(marker in lowered for marker in markers):
            return name
    prefix = re.split(r"[:|]", line, maxsplit=1)[0].strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", prefix).strip("_")
    return cleaned[:48] or f"window_{index}"


def parse_quota_output(
    credential_pool_id: str,
    output: str,
    *,
    observed_at: datetime | None = None,
    stale_after_seconds: int = 600,
    source_kind: str = "cli_usage",
) -> QuotaSnapshot:
    """Parse actual remaining percentages and reset times, never raw token data."""

    observed = _as_utc(observed_at or datetime.now(timezone.utc))
    clean = ANSI_RE.sub("", str(output or "")).replace("\r", "\n")
    lowered = clean.lower()
    stale_at = observed + timedelta(seconds=max(1, int(stale_after_seconds)))
    if any(marker in lowered for marker in ("not logged in", "login required", "unauthorized", "authentication failed")):
        return QuotaSnapshot(
            credential_pool_id=credential_pool_id,
            status="auth_missing",
            observed_at=utc_timestamp(observed),
            stale_at=utc_timestamp(stale_at),
            source_kind=source_kind,
            confidence="high",
            failure_class="auth_missing",
        )

    windows: list[QuotaWindow] = []
    pending_reset: datetime | None = None
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        reset = _duration_reset(line, observed) or _absolute_reset(line)
        percent_match = PERCENT_RE.search(line)
        if not percent_match:
            if reset is not None and windows and windows[-1].reset_at is None:
                previous = windows[-1]
                windows[-1] = QuotaWindow(
                    name=previous.name,
                    remaining_percent=previous.remaining_percent,
                    reset_at=utc_timestamp(reset),
                    confidence=previous.confidence,
                )
            elif reset is not None:
                pending_reset = reset
            continue
        value = max(0.0, min(100.0, float(percent_match.group("value"))))
        context = line.lower()
        if re.search(r"\b(used|consumed|spent)\b", context):
            remaining = 100.0 - value
        elif re.search(r"\b(remaining|left|available|remain)\b", context):
            remaining = value
        else:
            # A bare percentage is ambiguous and must not drive admission.
            continue
        window_reset = reset or pending_reset
        pending_reset = None
        windows.append(
            QuotaWindow(
                name=_window_name(line, index),
                remaining_percent=round(remaining, 4),
                reset_at=utc_timestamp(window_reset) if window_reset else None,
                confidence="high" if window_reset else "medium",
            )
        )

    known = [item for item in windows if item.remaining_percent is not None]
    if not known:
        return QuotaSnapshot(
            credential_pool_id=credential_pool_id,
            status="unknown",
            observed_at=utc_timestamp(observed),
            stale_at=utc_timestamp(stale_at),
            source_kind=source_kind,
            confidence="unknown",
            windows=tuple(windows),
            failure_class="telemetry_unparseable",
        )
    limiting = min(known, key=lambda item: float(item.remaining_percent or 0.0))
    remaining = float(limiting.remaining_percent or 0.0)
    status = "quota_reserve" if remaining <= 5.0 else "available"
    return QuotaSnapshot(
        credential_pool_id=credential_pool_id,
        status=status,
        observed_at=utc_timestamp(observed),
        stale_at=utc_timestamp(stale_at),
        remaining_percent=remaining,
        reset_at=limiting.reset_at,
        source_kind=source_kind,
        confidence="high" if limiting.reset_at else "medium",
        windows=tuple(windows),
        failure_class="quota_exhausted" if status == "quota_reserve" else None,
    )


@dataclass(frozen=True, slots=True)
class QuotaProbeSpec:
    shell_id: str
    argv: tuple[str, ...]
    slash_command: str
    exit_command: str = "/exit"
    timeout_seconds: int = 30
    startup_wait_seconds: float = 1.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QuotaProbeSpec":
        spec = cls(
            shell_id=str(value.get("shell_id") or ""),
            argv=tuple(str(item) for item in value.get("argv") or []),
            slash_command=str(value.get("slash_command") or ""),
            exit_command=str(value.get("exit_command") or "/exit"),
            timeout_seconds=int(value.get("timeout_seconds") or 30),
            startup_wait_seconds=float(value.get("startup_wait_seconds") or 1.0),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.shell_id not in SAFE_SHELLS:
            raise ValueError(f"unsupported quota probe shell: {self.shell_id}")
        if not self.argv or self.argv[0] != self.shell_id:
            raise ValueError("quota probe argv must start with its declared shell")
        if self.slash_command not in SAFE_SLASH_COMMANDS:
            raise ValueError(f"unsafe quota slash command: {self.slash_command}")
        if self.exit_command not in SAFE_EXIT_COMMANDS:
            raise ValueError(f"unsafe quota exit command: {self.exit_command}")
        try:
            from agent_runtime.shell_governance import validate_production_argv
        except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
            from shell_governance import validate_production_argv
        if validate_production_argv(self.argv):
            raise ValueError("dangerous shell bypass flag is forbidden in quota probes")


def run_interactive_probe(spec: QuotaProbeSpec) -> dict[str, Any]:
    """Run a bounded PTY probe; callers must persist only its parsed snapshot."""

    spec.validate()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        list(spec.argv),
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave_fd)
    chunks: list[bytes] = []
    deadline = time.monotonic() + spec.timeout_seconds
    try:
        time.sleep(max(0.0, spec.startup_wait_seconds))
        os.write(master_fd, f"{spec.slash_command}\n".encode())
        os.write(master_fd, f"{spec.exit_command}\n".encode())
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if ready:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            if process.poll() is not None and not ready:
                break
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        return {
            "returncode": int(process.returncode or 0),
            "output": b"".join(chunks).decode("utf-8", errors="replace"),
        }
    finally:
        os.close(master_fd)
