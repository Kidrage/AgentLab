from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_runtime.hermes_rpc import (
    HermesServerState,
    HermesApprovalRequired,
    HermesRpcClient,
    HermesRpcError,
    HermesRpcTimeout,
    HermesRunResult,
    _binding_matches,
    ensure_hermes_server,
    hermes_serve_command,
)


def test_binding_match_accepts_delimited_qualified_names_but_not_suffix_spoofing():
    assert _binding_matches("gpt-5.5", "openai-codex/gpt-5.5") is True
    assert _binding_matches("openai-codex", "provider:openai-codex") is True
    assert _binding_matches("gpt-5.5", "unexpected-gpt-5.5") is False


class FakeSocket:
    def __init__(self, frames: list[dict]) -> None:
        self.frames = [json.dumps(frame) for frame in frames]
        self.sent: list[dict] = []
        self.closed = False
        self.timeout: float | None = None

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if not self.frames:
            raise TimeoutError("scripted websocket exhausted")
        return self.frames.pop(0)

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def close(self) -> None:
        self.closed = True


def _response(request_id: int, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32000, "message": message},
    }


def _event(kind: str, session_id: str = "session-1", payload: dict | None = None) -> dict:
    params = {"type": kind, "session_id": session_id}
    if payload is not None:
        params["payload"] = payload
    return {"jsonrpc": "2.0", "method": "event", "params": params}


def test_run_uses_real_hermes_session_protocol_and_collects_usage(tmp_path: Path) -> None:
    socket = FakeSocket(
        [
            _event("gateway.ready", session_id="", payload={"skin": {}}),
            _response(
                1,
                {
                    "session_id": "session-1",
                    "stored_session_id": "stored-1",
                    "messages": [],
                    "info": {
                        "provider": "openai-codex",
                        "model": "gpt-5.5",
                        "reasoning_effort": "high",
                    },
                },
            ),
            _response(2, {"status": "streaming"}),
            _event("message.delta", payload={"text": "hel"}),
            _event(
                "message.complete",
                payload={
                    "text": "hello",
                    "status": "complete",
                    "usage": {"input": 12, "output": 3, "total": 15},
                },
            ),
            _response(3, {"calls": 1, "input": 12, "output": 3, "total": 15}),
            _response(4, {"closed": True}),
        ]
    )
    client = HermesRpcClient(
        "ws://127.0.0.1:9119/api/ws",
        socket_factory=lambda _url, _timeout: socket,
    )

    result = client.run(
        "write the report",
        cwd=tmp_path,
        profile="agentlabsupervisor",
        provider="openai-codex",
        model="gpt-5.5",
        reasoning_effort="high",
        timeout_seconds=30,
    )

    assert result.text == "hello"
    assert result.status == "complete"
    assert result.session_id == "session-1"
    assert result.stored_session_id == "stored-1"
    assert result.usage == {"calls": 1, "input": 12, "output": 3, "total": 15}
    assert result.usage_source == "hermes_session_usage"
    assert result.exact_usage_available is True
    assert result.provider == "openai-codex"
    assert result.model == "gpt-5.5"
    assert result.reasoning_effort == "high"
    assert result.binding_observed is True
    assert socket.closed is True
    assert [item["method"] for item in socket.sent] == [
        "session.create",
        "prompt.submit",
        "session.usage",
        "session.close",
    ]
    create = socket.sent[0]["params"]
    assert create["cwd"] == str(tmp_path.resolve())
    assert create["profile"] == "agentlabsupervisor"
    assert create["provider"] == "openai-codex"
    assert create["model"] == "gpt-5.5"
    assert create["reasoning_effort"] == "high"
    assert create["close_on_disconnect"] is True


def test_run_fails_closed_on_observed_provider_or_model_drift(tmp_path: Path) -> None:
    socket = FakeSocket(
        [
            _response(
                1,
                {
                    "session_id": "session-1",
                    "info": {
                        "provider": "openai-codex",
                        "model": "gpt-5.4",
                        "reasoning_effort": "high",
                    },
                },
            ),
            _response(2, {"status": "streaming"}),
            _event("message.complete", payload={"text": "wrong binding", "status": "complete"}),
            _response(3, {"closed": True}),
        ]
    )
    client = HermesRpcClient(
        "ws://127.0.0.1:9119/api/ws",
        socket_factory=lambda _url, _timeout: socket,
    )

    with pytest.raises(HermesRpcError, match="model binding drift"):
        client.run(
            "do work",
            cwd=tmp_path,
            provider="openai-codex",
            model="gpt-5.5",
            reasoning_effort="high",
            timeout_seconds=30,
        )


def test_run_marks_message_usage_inexact_when_session_usage_fails(tmp_path: Path) -> None:
    socket = FakeSocket(
        [
            _response(
                1,
                {
                    "session_id": "session-1",
                    "info": {
                        "provider": "openai-codex",
                        "model": "gpt-5.5",
                        "reasoning_effort": "high",
                    },
                },
            ),
            _response(2, {"status": "streaming"}),
            _event(
                "message.complete",
                payload={
                    "text": "done",
                    "status": "complete",
                    "usage": {"input": 9, "output": 2, "total": 11},
                },
            ),
            _error_response(3, "usage unavailable"),
            _response(4, {"closed": True}),
        ]
    )
    client = HermesRpcClient(
        "ws://127.0.0.1:9119/api/ws",
        socket_factory=lambda _url, _timeout: socket,
    )

    result = client.run(
        "do work",
        cwd=tmp_path,
        provider="openai-codex",
        model="gpt-5.5",
        reasoning_effort="high",
        timeout_seconds=30,
    )

    assert result.usage == {"input": 9, "output": 2, "total": 11}
    assert result.usage_source == "hermes_message_complete_usage"
    assert result.exact_usage_available is False


def test_run_fails_closed_when_hermes_requests_approval(tmp_path: Path) -> None:
    socket = FakeSocket(
        [
            _response(1, {"session_id": "session-1", "stored_session_id": "stored-1"}),
            _response(2, {"status": "streaming"}),
            _event("approval.request", payload={"approval_id": "approval-1"}),
            _response(3, {"closed": True}),
        ]
    )
    client = HermesRpcClient(
        "ws://127.0.0.1:9119/api/ws",
        socket_factory=lambda _url, _timeout: socket,
    )

    with pytest.raises(HermesApprovalRequired, match="approval"):
        client.run("do work", cwd=tmp_path, timeout_seconds=30)

    assert socket.closed is True
    assert socket.sent[-1]["method"] == "session.close"


def test_run_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(HermesRpcError, match="loopback"):
        HermesRpcClient("ws://example.com:9119/api/ws")


def test_run_converts_transport_timeout_to_typed_error(tmp_path: Path) -> None:
    socket = FakeSocket([])
    client = HermesRpcClient(
        "ws://127.0.0.1:9119/api/ws",
        socket_factory=lambda _url, _timeout: socket,
    )

    with pytest.raises(HermesRpcTimeout):
        client.run("do work", cwd=tmp_path, timeout_seconds=1)


def test_hermes_serve_command_is_loopback_and_noninteractive() -> None:
    assert hermes_serve_command("hermes", "127.0.0.1", 9119) == [
        "hermes",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "9119",
    ]

    with pytest.raises(HermesRpcError, match="loopback"):
        hermes_serve_command("hermes", "0.0.0.0", 9119)


def test_ensure_server_starts_once_without_a_shell(tmp_path: Path) -> None:
    probes = iter([False, False, True])
    calls: list[tuple[list[str], dict]] = []

    class Process:
        pid = 321

        @staticmethod
        def poll() -> None:
            return None

    def popen(argv: list[str], **kwargs):
        calls.append((argv, kwargs))
        return Process()

    state = ensure_hermes_server(
        "ws://127.0.0.1:9119/api/ws",
        binary="hermes",
        log_path=tmp_path / "hermes.log",
        startup_timeout_seconds=2,
        auto_start=True,
        probe=lambda _endpoint, _timeout: next(probes),
        process_factory=popen,
        sleeper=lambda _seconds: None,
    )

    assert state == HermesServerState(
        endpoint="ws://127.0.0.1:9119/api/ws",
        ready=True,
        started=True,
        pid=321,
    )
    assert calls[0][0] == [
        "hermes",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "9119",
    ]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["start_new_session"] is True


def test_ensure_server_does_not_start_when_auto_start_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(HermesRpcError, match="not running"):
        ensure_hermes_server(
            "ws://127.0.0.1:9119/api/ws",
            log_path=tmp_path / "hermes.log",
            auto_start=False,
            probe=lambda _endpoint, _timeout: False,
        )


def test_cli_channel_binds_fixed_profile_provider_model_and_exact_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_runtime.cli_executor import _run_hermes_rpc_channel

    captured: dict = {}

    class Client:
        def __init__(self, endpoint: str) -> None:
            captured["endpoint"] = endpoint

        def run(self, prompt: str, **kwargs) -> HermesRunResult:
            captured["prompt"] = prompt
            captured["run"] = kwargs
            return HermesRunResult(
                text="governed output",
                status="complete",
                usage={"calls": 1, "input": 100, "output": 25, "total": 125},
                session_id="live-1",
                stored_session_id="stored-1",
                provider=kwargs["provider"],
                model=kwargs["model"],
                event_count=4,
                reasoning_effort=kwargs["reasoning_effort"],
                binding_observed=True,
                usage_source="hermes_session_usage",
                exact_usage_available=True,
            )

    monkeypatch.setattr("agent_runtime.hermes_rpc.HermesRpcClient", Client)
    monkeypatch.setattr(
        "agent_runtime.hermes_rpc.ensure_hermes_server",
        lambda *_args, **_kwargs: HermesServerState(
            endpoint="ws://127.0.0.1:9119/api/ws",
            ready=True,
            started=False,
            pid=None,
        ),
    )
    packet = tmp_path / "task_packet_supervisor.json"
    packet.write_text("{}", encoding="utf-8")

    process, usage, metadata = _run_hermes_rpc_channel(
        role_profile={
            "profile_ref": "agentlabsupervisor",
            "runtime_channel_config": {
                "endpoint": "ws://127.0.0.1:9119/api/ws",
                "auto_start": True,
            },
        },
        contract={"resolved_reasoning_effort": "high"},
        model_values={
            "provider": "openai-codex",
            "model_id": "gpt-5.5",
            "model_key": "codex_gpt_5_5_high_hermes_oauth",
            "catalog_model_id": "gpt-5.5",
            "catalog_provider": "hermes_codex_oauth",
        },
        execution_cwd=tmp_path,
        execution_packet_path=packet,
        agentlab_root=tmp_path,
        agent_name="Supervisor",
        timeout_seconds=60,
    )

    assert process.returncode == 0
    assert process.stdout == "governed output"
    assert captured["run"]["profile"] == "agentlabsupervisor"
    assert captured["run"]["provider"] == "openai-codex"
    assert captured["run"]["model"] == "gpt-5.5"
    assert captured["run"]["reasoning_effort"] == "high"
    assert str(packet) in captured["prompt"]
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 25
    assert usage["total_tokens"] == 125
    assert usage["usage_source"] == "hermes_session_usage"
    assert usage["exact_usage_available"] is True
    assert metadata["execution_channel"] == "hermes_json_rpc_ws"
    assert metadata["observed_provider"] == "openai-codex"
    assert metadata["observed_model"] == "gpt-5.5"
    assert metadata["observed_reasoning_effort"] == "high"
    assert metadata["binding_observed"] is True


def test_hermes_receipt_separates_requested_and_observed_binding(tmp_path: Path) -> None:
    from agent_runtime.cli_executor import _write_hermes_supervisor_model_receipt

    path = _write_hermes_supervisor_model_receipt(
        tmp_path,
        {
            "applicable": True,
            "status": "pass",
            "issues": [],
            "required_shell_state": {
                "model.provider": "openai-codex",
                "model.default": "gpt-5.5",
            },
            "resolved_reasoning_effort": "high",
            "command_binding_verified": True,
            "attempt_id": "attempt-1",
        },
        status="pass",
        provider_process_started=True,
        execution_metadata={
            "binding_observed": True,
            "observed_provider": "openai-codex",
            "observed_model": "gpt-5.5",
            "observed_reasoning_effort": "high",
        },
    )

    receipt = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert receipt["requested_provider"] == "openai-codex"
    assert receipt["requested_model"] == "gpt-5.5"
    assert receipt["provider"] == "openai-codex"
    assert receipt["model"] == "gpt-5.5"
    assert receipt["provider_response_metadata_observed"] is True
    assert receipt["evidence_source"] == "hermes_session_info"
