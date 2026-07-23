from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from feedback_manager import create_decision_card, load_pending_decision_cards
from task_events import append_task_event, load_task_events
from watchdog import scan_project
import web_ui.server as web_server


class FakeSSEHandler:
    def __init__(self) -> None:
        self.status = 0
        self.headers: dict[str, str] = {}
        self.wfile = self
        self.body = b""

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers[key.lower()] = value

    def end_headers(self) -> None:
        pass

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

    def _json_response(self, data, status=200) -> None:
        self.status = status
        self.headers["content-type"] = "application/json"
        self.body += json.dumps(data).encode("utf-8")

    def _json_default(self, obj):
        return str(obj)

    def write(self, chunk: bytes) -> None:
        self.body += chunk

    def flush(self) -> None:
        pass


def _setup_run(root: Path, task_id: str = "task_0001") -> Path:
    run_dir = root / "projects" / "Demo" / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump({"project": "Demo", "task_id": task_id, "status": "paused"}),
        encoding="utf-8",
    )
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({"project": "Demo", "task_id": task_id, "status": "paused"}),
        encoding="utf-8",
    )
    return run_dir


def _patch_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(web_server, "AGENTLAB_ROOT", root)
    monkeypatch.setenv("AGENTLAB_WEB_UI_TOKEN", "test-token")


def test_events_endpoint_returns_task_events(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    append_task_event(run_dir, "TASK_CREATED", status="QUEUED", severity="INFO", message="Created.")
    _patch_root(monkeypatch, tmp_path)
    payload = web_server.handle_get_task_events("Demo", "task_0001")
    assert payload["success"] is True
    assert payload["events"][0]["event"] == "TASK_CREATED"


def test_status_uses_resolved_workflow_model_profiles(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "agent_registry.yml").write_text(
        yaml.safe_dump(
            {
                "agents": {
                    "Supervisor": {"role": "route owner", "execution_owner": "agentlab"},
                    "Coder": {"role": "implementation", "execution_owner": "worker"},
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "task_snapshot.yml").write_text(
        yaml.safe_dump({"route": ["Supervisor", "Coder"], "status": "planned"}),
        encoding="utf-8",
    )
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "execution_backend": "agentlab_orchestrated_cli",
                "route": {"agents": ["Supervisor", "Coder"]},
                "model_profiles": {
                    "Supervisor": {"cli_agent": "hermes", "model": "model-supervisor"},
                    "Coder": {"cli_agent": "claude_code", "model": "model-coder"},
                },
            }
        ),
        encoding="utf-8",
    )
    _patch_root(monkeypatch, tmp_path)

    payload = web_server.handle_get_status("Demo", "task_0001")

    assert payload["workflowDriver"] == "agentlab_orchestrated_cli"
    assert [(agent["provider"], agent["model"]) for agent in payload["agents"]] == [
        ("hermes", "model-supervisor"),
        ("claude_code", "model-coder"),
    ]
    assert "coderProvider" not in payload
    assert "brainProvider" not in payload


def test_project_overview_uses_canonical_default_workflow_driver(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "execution_modes.yml").write_text(
        yaml.safe_dump({"default_mode": "agentlab_orchestrated_cli"}),
        encoding="utf-8",
    )
    _patch_root(monkeypatch, tmp_path)

    payload = web_server.handle_get_status("Demo", "")

    assert payload["taskStatus"] == "no_task"
    assert payload["workflowDriver"] == "agentlab_orchestrated_cli"


def test_web_project_creation_uses_current_config_and_artifact_layout(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_root(monkeypatch, tmp_path)

    payload = web_server.handle_create_project({"projectName": "NewProject"})

    assert payload["success"] is True
    project_root = tmp_path / "projects" / "NewProject"
    assert (project_root / "production").is_dir()
    assert (project_root / "archive").is_dir()
    config = yaml.safe_load(
        (project_root / "project_config.yml").read_text(encoding="utf-8")
    )
    assert config["paths"]["production"] == "production"
    assert config["paths"]["archive"] == "archive"
    assert config["global_config"]["agent_model_profiles"].endswith(
        "config/agent_model_profiles.yml"
    )
    assert "model_profiles" not in config["global_config"]


def test_decisions_endpoint_returns_pending_cards(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    create_decision_card(
        run_dir,
        task_id="task_0001",
        card_type="user_decision",
        title="Approve",
        reason="Need approval.",
        options=[{"id": "approve_resume", "label": "Approve resume", "risk": "low"}],
    )
    _patch_root(monkeypatch, tmp_path)
    payload = web_server.handle_get_task_decisions("Demo", "task_0001")
    assert payload["success"] is True
    assert payload["pending_count"] == 1
    assert payload["decisions"][0]["type"] == "user_decision"


def test_approve_endpoint_updates_decision_card(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    card, _path = create_decision_card(
        run_dir,
        task_id="task_0001",
        card_type="user_decision",
        title="Approve",
        reason="Need approval.",
        options=[{"id": "approve_resume", "label": "Approve resume", "risk": "low"}],
    )
    _patch_root(monkeypatch, tmp_path)
    payload = web_server.handle_resolve_task_decision(
        "Demo",
        "task_0001",
        card["id"],
        "approved",
        {"project": "Demo", "option": "approve_resume"},
    )
    assert payload["success"] is True
    assert load_pending_decision_cards(run_dir) == []


def test_resume_endpoint_clears_waiting_state_where_appropriate(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    _patch_root(monkeypatch, tmp_path)
    payload = web_server.handle_task_control("Demo", "task_0001", "resume", {"project": "Demo"})
    assert payload["success"] is True
    state = yaml.safe_load((run_dir / "state.yml").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert load_task_events(run_dir)[-1]["event"] == "TASK_RESUMED"


def test_watchdog_marks_stale_task_as_stale_running(tmp_path: Path) -> None:
    run_dir = _setup_run(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({"status": "running", "last_event_at": old.isoformat()}),
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "watchdog_policy.yml").write_text(
        yaml.safe_dump({
            "enabled": True,
            "thresholds": {
                "running_without_heartbeat_seconds": 1,
                "running_without_event_seconds": 1,
                "waiting_for_approval_seconds": 1,
                "stale_lock_seconds": 1,
            },
            "stale_actions": {"append_event": True, "write_feedback_status": True, "create_decision_card": True},
        }),
        encoding="utf-8",
    )
    summary = scan_project(tmp_path, "Demo")
    assert summary["stale_count"] == 1
    assert load_task_events(run_dir)[-2]["event"] == "STALE_RUNNING"


def test_watchdog_creates_decision_card_for_stale_task(tmp_path: Path) -> None:
    run_dir = _setup_run(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({"status": "running", "last_event_at": old.isoformat()}),
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "watchdog_policy.yml").write_text(
        yaml.safe_dump({
            "enabled": True,
            "thresholds": {
                "running_without_heartbeat_seconds": 1,
                "running_without_event_seconds": 1,
                "waiting_for_approval_seconds": 1,
                "stale_lock_seconds": 1,
            },
            "stale_actions": {"append_event": True, "write_feedback_status": True, "create_decision_card": True},
        }),
        encoding="utf-8",
    )
    scan_project(tmp_path, "Demo")
    cards = load_pending_decision_cards(run_dir)
    assert len(cards) == 1
    assert cards[0]["type"] == "stale_running"


def test_sse_endpoint_returns_event_stream_headers(tmp_path: Path, monkeypatch) -> None:
    run_dir = _setup_run(tmp_path)
    append_task_event(run_dir, "TASK_CREATED", status="QUEUED", severity="INFO", message="Created.")
    _patch_root(monkeypatch, tmp_path)
    handler = FakeSSEHandler()
    web_server.AgentLabAPIHandler._sse_task_events(handler, "Demo", "task_0001")
    assert handler.status == 200
    assert handler.headers["content-type"].startswith("text/event-stream")
    assert b"event: TASK_CREATED" in handler.body
