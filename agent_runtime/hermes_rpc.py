"""Synchronous client for Hermes' local WebSocket JSON-RPC gateway.

Hermes is an optional execution accelerator.  AgentLab owns the task packet,
route choice, approvals, and receipts; this module only runs one fixed-model
session through the local Hermes control plane.  It never edits Hermes config
and it never approves tool requests on the operator's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlparse


class HermesRpcError(RuntimeError):
    """Hermes rejected a request or violated the JSON-RPC contract."""


class HermesRpcTimeout(HermesRpcError):
    """The fixed Hermes session did not finish before its deadline."""


class HermesApprovalRequired(HermesRpcError):
    """Hermes requested an approval that AgentLab must not grant implicitly."""


class WebSocketLike(Protocol):
    def send(self, payload: str) -> Any: ...

    def recv(self) -> str | bytes: ...

    def settimeout(self, value: float) -> Any: ...

    def close(self) -> Any: ...


SocketFactory = Callable[[str, float], WebSocketLike]


@dataclass(frozen=True, slots=True)
class HermesRunResult:
    text: str
    status: str
    usage: dict[str, Any]
    session_id: str
    stored_session_id: str | None
    provider: str | None
    model: str | None
    event_count: int
    reasoning_effort: str | None = None
    binding_observed: bool = False
    usage_source: str = "unavailable"
    exact_usage_available: bool = False


@dataclass(frozen=True, slots=True)
class HermesServerState:
    endpoint: str
    ready: bool
    started: bool
    pid: int | None


def _is_loopback(hostname: str | None) -> bool:
    return (hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"ws", "wss"}:
        raise HermesRpcError("Hermes endpoint must use ws:// or wss://")
    if not _is_loopback(parsed.hostname):
        raise HermesRpcError("Hermes RPC is restricted to a loopback endpoint")
    if parsed.path.rstrip("/") != "/api/ws":
        raise HermesRpcError("Hermes endpoint must target /api/ws")


def _canonical_binding(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _binding_matches(requested: str | None, observed: str | None) -> bool:
    if not requested:
        return True
    requested_key = _canonical_binding(requested)
    observed_key = _canonical_binding(observed)
    if not observed_key:
        return False
    observed_aliases = {
        _canonical_binding(part)
        for part in re.split(r"[\s/:]+", str(observed or ""))
        if part
    }
    return observed_key == requested_key or requested_key in observed_aliases


def _binding_info(value: Any) -> dict[str, str | None]:
    raw = value if isinstance(value, dict) else {}
    return {
        "provider": str(raw.get("provider") or "") or None,
        "model": str(raw.get("model") or "") or None,
        "reasoning_effort": str(raw.get("reasoning_effort") or "") or None,
    }


def _assert_observed_binding(
    observed: dict[str, str | None],
    *,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> None:
    for label, requested in (
        ("provider", provider),
        ("model", model),
        ("reasoning effort", reasoning_effort),
    ):
        key = "reasoning_effort" if label == "reasoning effort" else label
        actual = observed.get(key)
        if requested and not actual:
            raise HermesRpcError(f"Hermes {label} binding metadata is missing")
        if requested and not _binding_matches(requested, actual):
            raise HermesRpcError(
                f"Hermes {label} binding drift: requested {requested!r}, observed {actual!r}"
            )


def hermes_serve_command(binary: str, host: str, port: int) -> list[str]:
    """Build the only supported command for an AgentLab-owned local gateway."""
    if not _is_loopback(host):
        raise HermesRpcError("Hermes serve host must be loopback")
    if not binary or int(port) <= 0 or int(port) > 65535:
        raise HermesRpcError("Hermes serve binary and port must be valid")
    return [binary, "serve", "--host", host, "--port", str(int(port))]


def _default_socket_factory(endpoint: str, timeout: float) -> WebSocketLike:
    try:
        import websocket
    except ImportError as exc:  # pragma: no cover - installation boundary
        raise HermesRpcError(
            "websocket-client is required for the Hermes RPC adapter"
        ) from exc
    try:
        return websocket.create_connection(
            endpoint,
            timeout=timeout,
            http_proxy_host=None,
            http_proxy_port=None,
        )
    except Exception as exc:  # pragma: no cover - live transport boundary
        if "timeout" in type(exc).__name__.casefold():
            raise HermesRpcTimeout("timed out connecting to Hermes RPC") from exc
        raise HermesRpcError(f"could not connect to Hermes RPC: {exc}") from exc


def _probe_gateway(endpoint: str, timeout: float) -> bool:
    socket: WebSocketLike | None = None
    try:
        socket = _default_socket_factory(endpoint, timeout)
        socket.settimeout(timeout)
        raw = socket.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        frame = json.loads(raw)
        params = frame.get("params") if isinstance(frame, dict) else None
        return bool(
            isinstance(params, dict)
            and frame.get("method") == "event"
            and params.get("type") == "gateway.ready"
        )
    except Exception:
        return False
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass


def ensure_hermes_server(
    endpoint: str,
    *,
    binary: str = "hermes",
    log_path: Path,
    startup_timeout_seconds: float = 15,
    auto_start: bool = False,
    probe: Callable[[str, float], bool] | None = None,
    process_factory: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> HermesServerState:
    """Ensure one loopback Hermes gateway exists, starting it only if allowed.

    The start lock prevents concurrent AgentLab runs from launching duplicate
    machine-level gateways.  The spawned process is detached and reused by
    later roles; Hermes remains the owner of its own process lifecycle.
    """
    _validate_endpoint(endpoint)
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    readiness_probe = probe or _probe_gateway
    if readiness_probe(endpoint, 0.5):
        return HermesServerState(endpoint, True, False, None)
    if not auto_start:
        raise HermesRpcError("Hermes RPC gateway is not running and auto-start is disabled")

    resolved_log = Path(log_path).resolve()
    resolved_log.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolved_log.with_suffix(resolved_log.suffix + ".lock")
    process = None
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):  # pragma: no cover - non-POSIX fallback
            pass
        if readiness_probe(endpoint, 0.5):
            return HermesServerState(endpoint, True, False, None)
        command = hermes_serve_command(binary, host, port)
        factory = process_factory or subprocess.Popen
        with resolved_log.open("a", encoding="utf-8") as log_file:
            process = factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(resolved_log.parent),
                env=os.environ.copy(),
                shell=False,
                start_new_session=True,
                close_fds=True,
            )
        deadline = time.monotonic() + max(0.1, float(startup_timeout_seconds))
        while time.monotonic() < deadline:
            if readiness_probe(endpoint, 0.5):
                return HermesServerState(
                    endpoint,
                    True,
                    True,
                    int(process.pid) if getattr(process, "pid", None) else None,
                )
            if process.poll() is not None:
                raise HermesRpcError("Hermes RPC gateway exited during startup")
            sleeper(0.2)
    raise HermesRpcTimeout("Hermes RPC gateway did not become ready")


class HermesRpcClient:
    """Run one governed Hermes turn over the installed gateway protocol."""

    def __init__(
        self,
        endpoint: str = "ws://127.0.0.1:9119/api/ws",
        *,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        _validate_endpoint(endpoint)
        self.endpoint = endpoint
        self._socket_factory = socket_factory or _default_socket_factory
        self._socket: WebSocketLike | None = None
        self._next_id = 1
        self._events: list[dict[str, Any]] = []

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HermesRpcTimeout("Hermes RPC turn exceeded its deadline")
        return remaining

    def _recv(self, deadline: float) -> dict[str, Any]:
        if self._socket is None:
            raise HermesRpcError("Hermes RPC socket is not connected")
        self._socket.settimeout(max(0.05, self._remaining(deadline)))
        try:
            raw = self._socket.recv()
        except Exception as exc:
            name = type(exc).__name__.casefold()
            if isinstance(exc, TimeoutError) or "timeout" in name:
                raise HermesRpcTimeout("Hermes RPC turn exceeded its deadline") from exc
            raise HermesRpcError(f"Hermes RPC receive failed: {exc}") from exc
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            frame = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise HermesRpcError("Hermes RPC returned invalid JSON") from exc
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            raise HermesRpcError("Hermes RPC returned an invalid JSON-RPC frame")
        return frame

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        deadline: float,
    ) -> dict[str, Any]:
        if self._socket is None:
            raise HermesRpcError("Hermes RPC socket is not connected")
        request_id = self._next_id
        self._next_id += 1
        self._socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                ensure_ascii=False,
            )
        )
        while True:
            frame = self._recv(deadline)
            if frame.get("method") == "event":
                self._events.append(frame)
                continue
            if frame.get("id") != request_id:
                raise HermesRpcError(
                    f"Hermes RPC response id mismatch for {method}"
                )
            if isinstance(frame.get("error"), dict):
                error = frame["error"]
                raise HermesRpcError(
                    f"Hermes RPC {method} failed "
                    f"({error.get('code', 'unknown')}): {error.get('message', 'unknown error')}"
                )
            result = frame.get("result")
            if not isinstance(result, dict):
                raise HermesRpcError(f"Hermes RPC {method} returned no result object")
            return result

    def _next_turn_event(
        self,
        session_id: str,
        deadline: float,
    ) -> dict[str, Any]:
        while self._events:
            frame = self._events.pop(0)
            params = frame.get("params") or {}
            if params.get("session_id") in {"", session_id}:
                return frame
        while True:
            frame = self._recv(deadline)
            if frame.get("method") != "event":
                raise HermesRpcError("Hermes RPC emitted an unexpected response frame")
            params = frame.get("params") or {}
            if params.get("session_id") in {"", session_id}:
                return frame

    def _best_effort_close(self, session_id: str, deadline: float) -> None:
        if not session_id or self._socket is None:
            return
        try:
            self._request(
                "session.close",
                {"session_id": session_id},
                min(max(deadline, time.monotonic() + 0.05), time.monotonic() + 1.0),
            )
        except HermesRpcError:
            pass

    def run(
        self,
        prompt: str,
        *,
        cwd: Path,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: float = 600,
    ) -> HermesRunResult:
        if not prompt.strip():
            raise HermesRpcError("Hermes RPC prompt must not be empty")
        resolved_cwd = Path(cwd).resolve()
        if not resolved_cwd.is_dir():
            raise HermesRpcError("Hermes RPC cwd must be an existing directory")
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        session_id = ""
        stored_session_id: str | None = None
        final_payload: dict[str, Any] = {}
        deltas: list[str] = []
        observed_binding: dict[str, str | None] = {
            "provider": None,
            "model": None,
            "reasoning_effort": None,
        }
        turn_event_count = 0
        try:
            self._socket = self._socket_factory(
                self.endpoint,
                self._remaining(deadline),
            )
            create_params: dict[str, Any] = {
                "cwd": str(resolved_cwd),
                "source": "agentlab",
                "close_on_disconnect": True,
            }
            if profile:
                create_params["profile"] = profile
            if provider:
                create_params["provider"] = provider
            if model:
                create_params["model"] = model
            if reasoning_effort:
                create_params["reasoning_effort"] = reasoning_effort
            created = self._request("session.create", create_params, deadline)
            session_id = str(created.get("session_id") or "")
            if not session_id:
                raise HermesRpcError("Hermes RPC did not return a session id")
            stored_session_id = str(created.get("stored_session_id") or "") or None
            observed_binding.update(
                {
                    key: value
                    for key, value in _binding_info(created.get("info")).items()
                    if value
                }
            )
            self._request(
                "prompt.submit",
                {"session_id": session_id, "text": prompt},
                deadline,
            )
            while True:
                event = self._next_turn_event(session_id, deadline)
                params = event.get("params") or {}
                kind = str(params.get("type") or "")
                payload = params.get("payload") or {}
                turn_event_count += 1
                if kind == "message.delta" and isinstance(payload.get("text"), str):
                    deltas.append(payload["text"])
                elif kind == "session.info":
                    observed_binding.update(
                        {
                            key: value
                            for key, value in _binding_info(payload).items()
                            if value
                        }
                    )
                elif kind == "approval.request":
                    raise HermesApprovalRequired(
                        "Hermes requested tool approval; AgentLab left it unapproved"
                    )
                elif kind == "error":
                    raise HermesRpcError(
                        f"Hermes session failed: {payload.get('message', 'unknown error')}"
                    )
                elif kind == "message.complete":
                    final_payload = payload if isinstance(payload, dict) else {}
                    break

            _assert_observed_binding(
                observed_binding,
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            event_usage = final_payload.get("usage")
            usage = event_usage if isinstance(event_usage, dict) else {}
            usage_source = (
                "hermes_message_complete_usage" if usage else "unavailable"
            )
            exact_usage_available = False
            try:
                usage = self._request(
                    "session.usage",
                    {"session_id": session_id},
                    deadline,
                )
                usage_source = "hermes_session_usage"
                exact_usage_available = True
            except HermesRpcError:
                pass
            text = str(final_payload.get("text") or "") or "".join(deltas)
            return HermesRunResult(
                text=text,
                status=str(final_payload.get("status") or "complete"),
                usage=dict(usage),
                session_id=session_id,
                stored_session_id=stored_session_id,
                provider=observed_binding["provider"],
                model=observed_binding["model"],
                event_count=turn_event_count,
                reasoning_effort=observed_binding["reasoning_effort"],
                binding_observed=bool(
                    observed_binding["provider"] and observed_binding["model"]
                ),
                usage_source=usage_source,
                exact_usage_available=exact_usage_available,
            )
        finally:
            self._best_effort_close(session_id, deadline)
            if self._socket is not None:
                try:
                    self._socket.close()
                finally:
                    self._socket = None
