from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from feedback_manager import create_decision_card
from skill_evolution import build_skill_adoption_request, write_skill_adoption_request
from webhook_dispatcher import dispatch_event, webhook_status


def _write_policy(root: Path, *, enabled: bool = True, max_attempts: int = 1) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "webhook_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": enabled,
            "endpoints": [{
                "name": "mock",
                "url_env": "AGENTLAB_TEST_WEBHOOK_URL",
                "secret_env": "AGENTLAB_TEST_WEBHOOK_SECRET",
                "events": [
                    "ACTION_REQUIRED",
                    "BLOCKED",
                    "STALE_RUNNING",
                    "FAILED_RECOVERABLE",
                    "COMPLETED",
                    "SKILL_REQUEST_PENDING",
                    "SKILL_CANDIDATE_READY",
                    "SKILL_PROMOTED",
                ],
            }],
            "retry": {"max_attempts": max_attempts, "backoff_seconds": 0},
            "security": {"sign_payload": True, "redact_secrets": True},
        }),
        encoding="utf-8",
    )


def _setup_run(root: Path) -> Path:
    run_dir = root / "projects" / "Demo" / "runs" / "task_0001"
    run_dir.mkdir(parents=True)
    return run_dir


def test_disabled_webhook_does_nothing_and_succeeds(tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=False)
    result = dispatch_event(
        tmp_path,
        event="ACTION_REQUIRED",
        project="Demo",
        task_id="task_0001",
        summary="Needs action.",
    )
    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["deliveries"] == []


def test_enabled_webhook_posts_payload(monkeypatch, tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=True)
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_URL", "http://example.test/hook")
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_SECRET", "secret")
    calls = []

    def fake_post(url, payload, headers, timeout=10):
        calls.append((url, payload, headers))
        return 204, ""

    monkeypatch.setattr("webhook_dispatcher.post_json", fake_post)
    result = dispatch_event(tmp_path, event="COMPLETED", project="Demo", task_id="task_0001", summary="Done.")

    assert result["ok"] is True
    assert calls[0][0] == "http://example.test/hook"
    assert calls[0][1]["event"] == "COMPLETED"
    assert calls[0][2]["X-AgentLab-Signature"].startswith("sha256=")


def test_payload_redacts_secrets(monkeypatch, tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=True)
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_URL", "http://example.test/hook")
    captured = {}

    def fake_post(url, payload, headers, timeout=10):
        captured.update(payload)
        return 200, "ok"

    monkeypatch.setattr("webhook_dispatcher.post_json", fake_post)
    dispatch_event(
        tmp_path,
        event="ACTION_REQUIRED",
        project="Demo",
        payload={
            "event": "ACTION_REQUIRED",
            "project": "Demo",
            "api_key": "do-not-send",
            "nested": {"secret_token": "do-not-send"},
        },
    )

    assert captured["api_key"] == "REDACTED"
    assert captured["nested"]["secret_token"] == "REDACTED"


def test_failed_delivery_records_retry_failure(monkeypatch, tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=True, max_attempts=2)
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_URL", "http://example.test/hook")

    def fake_post(url, payload, headers, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr("webhook_dispatcher.post_json", fake_post)
    result = dispatch_event(tmp_path, event="COMPLETED", project="Demo", task_id="task_0001", summary="Done.")
    status = webhook_status(tmp_path, "Demo", "task_0001")

    assert result["ok"] is False
    assert status["deliveries"][-1]["status"] == "failed"
    assert len(status["deliveries"][-1]["attempts"]) == 2


def test_decision_card_creation_triggers_dispatch(monkeypatch, tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=True)
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_URL", "http://example.test/hook")
    calls = []

    def fake_post(url, payload, headers, timeout=10):
        calls.append(payload)
        return 200, "ok"

    monkeypatch.setattr("webhook_dispatcher.post_json", fake_post)
    run_dir = _setup_run(tmp_path)
    create_decision_card(
        run_dir,
        task_id="task_0001",
        card_type="user_decision",
        title="Approval required",
        reason="Need approval.",
        options=[{"id": "approve_resume", "label": "Approve resume", "risk": "low"}],
    )

    assert calls[-1]["event"] == "ACTION_REQUIRED"
    assert calls[-1]["decision_card"]["options"][0]["id"] == "approve_resume"


def test_skill_request_triggers_dispatch(monkeypatch, tmp_path: Path) -> None:
    _write_policy(tmp_path, enabled=True)
    monkeypatch.setenv("AGENTLAB_TEST_WEBHOOK_URL", "http://example.test/hook")
    calls = []

    def fake_post(url, payload, headers, timeout=10):
        calls.append(payload)
        return 200, "ok"

    monkeypatch.setattr("webhook_dispatcher.post_json", fake_post)
    request = build_skill_adoption_request(
        tmp_path,
        project="Demo",
        skill_name="Demo skill",
        source="manual://demo",
        purpose="Test skill request webhook.",
    )
    write_skill_adoption_request(tmp_path, request)

    assert calls[-1]["event"] == "SKILL_REQUEST_PENDING"
    assert "Demo skill" in calls[-1]["summary"]
