from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.frontdesk_service import (
    FrontdeskServiceState,
    build_frontdesk_health,
    process_frontdesk_request,
)


def test_different_adapters_produce_identical_route() -> None:
    openclaw = process_frontdesk_request(
        {
            "operation": "route",
            "request_id": "request-001",
            "request": "Audit and verify this bounded change",
            "project": "AgentLab",
            "adapter": "openclaw",
        },
        state=None,
        config_sha256="a" * 64,
        version="1.0.0",
    )
    hermes = process_frontdesk_request(
        {
            "operation": "route",
            "request_id": "request-002",
            "request": "Audit and verify this bounded change",
            "project": "AgentLab",
            "adapter": "hermes",
        },
        state=None,
        config_sha256="a" * 64,
        version="1.0.0",
    )

    assert openclaw["intent"] == hermes["intent"]
    assert openclaw["intent"]["route_tier"] == "F3"


def test_state_restores_session_and_deduplicates_same_request(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "frontdesk_state.yml"
    first_store = FrontdeskServiceState(state_path)
    request = {
        "operation": "route",
        "request_id": "request-stable",
        "request": "Implement one bounded file change",
        "project": "AgentLab",
        "adapter": "openclaw",
        "session_id": "session-42",
        "task_status": "planned",
        "capability_bindings": ["file_edit", "test_execution"],
    }
    first = process_frontdesk_request(
        request,
        state=first_store,
        config_sha256="b" * 64,
        version="2.0.0",
    )

    restarted_store = FrontdeskServiceState(state_path)
    repeated = process_frontdesk_request(
        request,
        state=restarted_store,
        config_sha256="b" * 64,
        version="2.0.0",
    )

    assert repeated == first
    persisted = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    assert persisted["sessions"]["session-42"]["task_status"] == "planned"
    assert persisted["sessions"]["session-42"]["capability_bindings"] == [
        "file_edit",
        "test_execution",
    ]
    assert persisted["processed_request_count"] == 1


def test_reused_request_id_with_changed_payload_is_rejected(
    tmp_path: Path,
) -> None:
    store = FrontdeskServiceState(tmp_path / "state.yml")
    original = {
        "operation": "route",
        "request_id": "same-id",
        "request": "Check status",
    }
    process_frontdesk_request(
        original,
        state=store,
        config_sha256="c" * 64,
        version="1",
    )
    changed = {**original, "request": "Delete production"}

    try:
        process_frontdesk_request(
            changed,
            state=store,
            config_sha256="c" * 64,
            version="1",
        )
    except ValueError as exc:
        assert "request_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("changed request was replayed")


def test_health_receipt_reports_version_config_and_state_without_secrets(
    tmp_path: Path,
) -> None:
    state = FrontdeskServiceState(tmp_path / "state.yml")
    health = build_frontdesk_health(
        state=state,
        config_sha256="d" * 64,
        version="3.1.4",
        adapter="openclaw",
    )

    assert health["status"] == "healthy"
    assert health["version"] == "3.1.4"
    assert health["config_sha256"] == "d" * 64
    assert health["adapter"] == "openclaw"
    assert health["state"]["processed_request_count"] == 0
    assert "path" not in str(health).lower()


def test_systemd_template_is_non_root_local_socket_and_auto_restarts() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (
        root / "deploy" / "systemd" / "agentlab-frontdesk.service"
    ).read_text(encoding="utf-8")

    assert "User=root" not in text
    assert "frontdesk serve --adapter openclaw" in text
    assert "--socket %t/agentlab/frontdesk.sock" in text
    assert "Restart=on-failure" in text
    assert "RuntimeDirectory=agentlab" in text
