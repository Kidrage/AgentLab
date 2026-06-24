import os
import json
import yaml
import pytest
from agent_runtime.observability.api import emit_event
from agent_runtime.observability.query import query_timeline

def test_m2_7_observability_e2e(tmp_path):
    project_dir = tmp_path / "AgentLab"
    
    # Simulate full lifecycle
    emit_event("p1", project_dir, "route_decision_created", {"route_profile": "local_fast"}, worker_id="w1", role_id="r1")
    emit_event("p1", project_dir, "role_assigned", {"decision_path": "cache"}, worker_id="w1", role_id="r1")
    emit_event("p1", project_dir, "cost_estimated", {"model": "gpt-4"}, cost_usd=0.1)
    emit_event("p1", project_dir, "approval_requested", {"decision_card_id": "dc1"})
    emit_event("p1", project_dir, "approval_accepted", {"decision_card_id": "dc1"})
    emit_event("p1", project_dir, "task_packet_created", {"file": "task.yml"}, task_id="t1")
    emit_event("p1", project_dir, "executor_started", {"mode": "execute"}, task_id="t1")
    emit_event("p1", project_dir, "executor_finished", {"status": "success"}, task_id="t1")
    emit_event("p1", project_dir, "evidence_collected", {"artifact": "diff.patch"}, task_id="t1")
    emit_event("p1", project_dir, "phase_accepted", {"phase": "build"}, task_id="t1")

    # Verify timeline
    events = query_timeline(str(project_dir))
    assert len(events) == 10
    assert all(e.schema_version == "m2.7.1" for e in events)
    assert events[0].event_type == "route_decision_created"
    assert events[-1].event_type == "phase_accepted"
    
    # Verify yaml logs
    obs_dir = project_dir / "observability"
    assert (obs_dir / "timeline.jsonl").exists()
    assert (obs_dir / "event_log.jsonl").exists()
    assert (obs_dir / "route_events.yml").exists()
    assert (obs_dir / "worker_events.yml").exists()
    assert (obs_dir / "cost_events.yml").exists()
    assert (obs_dir / "decision_events.yml").exists()
    assert (obs_dir / "executor_runs.yml").exists()

def test_m2_7_observability_api_invalid_type(tmp_path):
    project_dir = tmp_path / "AgentLab"
    # invalid type should not crash but return None (if fail_open)
    evt = emit_event("p1", project_dir, "invalid_fake_event_type", {"data": 123})
    assert evt is None

def test_m2_7_observability_api_redacts_secrets(tmp_path):
    project_dir = tmp_path / "AgentLab"
    evt = emit_event("p1", project_dir, "worker_detected", {"data": "API_KEY=sk-12345"})
    assert evt is not None
    content = (project_dir / "observability" / "timeline.jsonl").read_text()
    assert "sk-12345" not in content
    assert "REDACTED" in content

def test_m2_7_observability_api_negative_cost(tmp_path):
    project_dir = tmp_path / "AgentLab"
    # If cost is negative, it should fail validation and not crash (if fail_open), returning None
    evt = emit_event("p1", project_dir, "cost_estimated", {"data": 123}, cost_usd=-1.0)
    assert evt is None
    
def test_m2_7_observability_api_crash_handling(tmp_path, monkeypatch):
    project_dir = tmp_path / "AgentLab"
    # force a crash in log_event
    def fake_log(*args, **kwargs):
        raise RuntimeError("Fake crash")
    monkeypatch.setattr("agent_runtime.observability.event_log.EventLogger.log_event", fake_log)
    
    # Should not crash the caller
    evt = emit_event("p1", project_dir, "cost_estimated", {"data": 123}, cost_usd=1.0)
    assert evt is None
