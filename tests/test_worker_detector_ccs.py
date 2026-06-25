import pytest
from agent_runtime.workers.detector import scan_workers, DEFAULT_CANDIDATES

@pytest.fixture(autouse=True)
def mock_all_probes(monkeypatch):
    monkeypatch.setattr("agent_runtime.workers.detector.probe_version", lambda cmd: f"{cmd}-mock-version")
    monkeypatch.setattr("agent_runtime.workers.detector.probe_auth", lambda worker_id: "yes")

def test_claude_code_prefers_ccs_when_available(monkeypatch):
    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", lambda cmd: cmd == "ccs")
    workers = scan_workers()
    claude = next(w for w in workers if w.worker_id == "claude_code")
    assert claude.command == "ccs"
    assert claude.installed is True

def test_claude_code_falls_back_to_claude_when_ccs_missing(monkeypatch):
    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", lambda cmd: cmd == "claude")
    workers = scan_workers()
    claude = next(w for w in workers if w.worker_id == "claude_code")
    assert claude.command == "claude"
    assert claude.installed is True

def test_claude_code_not_installed_when_neither_binary_exists(monkeypatch):
    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", lambda cmd: False)
    workers = scan_workers()
    claude = next(w for w in workers if w.worker_id == "claude_code")
    assert claude.installed is False

def test_high_risk_claude_code_not_default_enabled():
    claude = next(c for c in DEFAULT_CANDIDATES if c["worker_id"] == "claude_code")
    assert claude.get("default_enabled") is False
    assert claude.get("risk_level") == "high"

def test_high_risk_workers_always_require_approval(monkeypatch):
    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", lambda cmd: True)
    workers = scan_workers()
    for w in workers:
        if w.risk_level == "high":
            assert w.approval_required is True
