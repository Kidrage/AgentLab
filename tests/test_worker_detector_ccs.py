import pytest
from agent_runtime.workers.detector import scan_workers, DEFAULT_CANDIDATES

@pytest.fixture(autouse=True)
def mock_all_probes(monkeypatch):
    def fake_probe_command(cmd):
        return False

    def fake_probe_version(cmd):
        return f"{cmd}-mock-version"

    def fake_probe_auth(worker_id):
        return "yes"

    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", fake_probe_command)
    monkeypatch.setattr("agent_runtime.workers.detector.probe_version", fake_probe_version)
    monkeypatch.setattr("agent_runtime.workers.detector.probe_auth", fake_probe_auth)

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

def test_worker_detector_ccs_tests_do_not_call_real_subprocess(monkeypatch):
    import subprocess

    def fail_subprocess_run(*args, **kwargs):
        raise AssertionError("CCS detector tests must not call real subprocess.run")

    monkeypatch.setattr(subprocess, "run", fail_subprocess_run)
    monkeypatch.setattr("agent_runtime.workers.detector.probe_command", lambda cmd: cmd == "ccs")
    monkeypatch.setattr("agent_runtime.workers.detector.probe_version", lambda cmd: f"{cmd}-mock-version")
    monkeypatch.setattr("agent_runtime.workers.detector.probe_auth", lambda worker_id: "yes")

    from agent_runtime.workers.detector import scan_workers
    workers = scan_workers()
    claude = next(w for w in workers if w.worker_id == "claude_code")
    assert claude.command == "ccs"
