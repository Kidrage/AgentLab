"""Local Unix-socket Frontdesk service with durable idempotency."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socketserver
from typing import Any, Iterator, Mapping

import yaml

from atomic_io import atomic_write_yaml
from agent_runtime.frontdesk_intent import (
    compile_frontdesk_intent,
    load_frontdesk_intent_policy,
)

MAX_REQUEST_BYTES = 1024 * 1024


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class FrontdeskServiceState:
    """Small durable state used to resume sessions and suppress replays."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "schema_version": "frontdesk-service-state/v1",
            "processed_requests": {},
            "sessions": {},
            "processed_request_count": 0,
        }

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self.empty()
        try:
            value = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError("frontdesk service state is unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != "frontdesk-service-state/v1"
            or not isinstance(value.get("processed_requests"), dict)
            or not isinstance(value.get("sessions"), dict)
        ):
            raise ValueError("frontdesk service state schema is invalid")
        return value

    def save(self, value: Mapping[str, Any]) -> None:
        atomic_write_yaml(self.path, dict(value))

    def summary(self) -> dict[str, int]:
        with self.lock():
            value = self.load()
        return {
            "processed_request_count": int(
                value.get("processed_request_count") or 0
            ),
            "session_count": len(value.get("sessions") or {}),
        }


def _request_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in {"adapter"}
    }


def process_frontdesk_request(
    payload: Mapping[str, Any],
    *,
    state: FrontdeskServiceState | None,
    config_sha256: str,
    version: str,
    intent_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Route one request and persist it exactly once when state is configured."""

    if payload.get("operation") != "route":
        raise ValueError("frontdesk operation must be route")
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id or any(character in request_id for character in "\r\n\0"):
        raise ValueError("frontdesk request_id is required")
    request_text = str(payload.get("request") or "").strip()
    request_sha256 = _sha256(_request_identity(payload))

    def build_response() -> dict[str, Any]:
        intent = compile_frontdesk_intent(
            request_text,
            project=(
                str(payload["project"])
                if payload.get("project") is not None
                else None
            ),
            project_contract_exists=(
                payload.get("project_contract_exists") is True
            ),
            adapter=str(payload.get("adapter") or ""),
            policy=intent_policy,
        )
        return {
            "schema_version": "frontdesk-service-response/v1",
            "status": "routed",
            "request_id": request_id,
            "request_sha256": request_sha256,
            "intent": intent,
            "service_version": version,
            "config_sha256": config_sha256,
        }

    if state is None:
        return build_response()
    with state.lock():
        stored = state.load()
        prior = stored["processed_requests"].get(request_id)
        if isinstance(prior, Mapping):
            if prior.get("request_sha256") != request_sha256:
                raise ValueError(
                    "frontdesk request_id was reused with changed payload"
                )
            response = prior.get("response")
            if not isinstance(response, Mapping):
                raise ValueError("frontdesk cached response is invalid")
            return deepcopy(dict(response))
        response = build_response()
        stored["processed_requests"][request_id] = {
            "request_sha256": request_sha256,
            "response": deepcopy(response),
        }
        stored["processed_request_count"] = (
            int(stored.get("processed_request_count") or 0) + 1
        )
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            bindings = payload.get("capability_bindings") or []
            if not isinstance(bindings, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in bindings
            ):
                raise ValueError("capability_bindings must be strings")
            stored["sessions"][session_id] = {
                "last_request_id": request_id,
                "task_status": str(payload.get("task_status") or "routed"),
                "capability_bindings": list(bindings),
                "project": payload.get("project"),
            }
        state.save(stored)
        return response


def build_frontdesk_health(
    *,
    state: FrontdeskServiceState,
    config_sha256: str,
    version: str,
    adapter: str,
) -> dict[str, Any]:
    """Return a non-secret heartbeat and configuration receipt."""

    return {
        "schema_version": "frontdesk-health/v1",
        "status": "healthy",
        "version": version,
        "config_sha256": config_sha256,
        "adapter": adapter,
        "state": state.summary(),
    }


def frontdesk_config_sha256(agentlab_root: Path) -> str:
    """Hash only public routing authorities used by the service."""

    root = Path(agentlab_root).resolve()
    digest = hashlib.sha256()
    for relative in (
        "config/frontdesk_policy.yml",
        "config/routing_rules.yml",
        "config/agent_role_bindings.yml",
    ):
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve_frontdesk(
    *,
    socket_path: Path,
    state_path: Path,
    agentlab_root: Path,
    adapter: str,
    version: str,
) -> None:
    """Serve newline-delimited JSON on a private local Unix socket."""

    endpoint = Path(socket_path)
    if not endpoint.is_absolute():
        raise ValueError("frontdesk socket path must be absolute")
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    if endpoint.exists():
        if not endpoint.is_socket():
            raise ValueError("frontdesk socket path exists and is not a socket")
        endpoint.unlink()
    state = FrontdeskServiceState(state_path)
    config_sha256 = frontdesk_config_sha256(agentlab_root)
    intent_policy = load_frontdesk_intent_policy(agentlab_root)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(raw) > MAX_REQUEST_BYTES:
                response = {"status": "blocked", "error": "request_too_large"}
            else:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("request must be a mapping")
                    if payload.get("operation") == "health":
                        response = build_frontdesk_health(
                            state=state,
                            config_sha256=config_sha256,
                            version=version,
                            adapter=adapter,
                        )
                    else:
                        payload["adapter"] = adapter
                        response = process_frontdesk_request(
                            payload,
                            state=state,
                            config_sha256=config_sha256,
                            version=version,
                            intent_policy=intent_policy,
                        )
                except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    response = {
                        "schema_version": "frontdesk-service-response/v1",
                        "status": "blocked",
                        "error": type(exc).__name__,
                    }
            self.wfile.write(
                (_canonical_json(response) + "\n").encode("utf-8")
            )

    previous_umask = os.umask(0o077)
    try:
        with _ThreadingUnixServer(str(endpoint), Handler) as server:
            os.chmod(endpoint, 0o600)
            server.serve_forever()
    finally:
        os.umask(previous_umask)
        try:
            if endpoint.is_socket():
                endpoint.unlink()
        except OSError:
            pass
