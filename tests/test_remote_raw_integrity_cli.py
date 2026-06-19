from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_remote_raw_module():
    spec = importlib.util.spec_from_file_location(
        "check_remote_raw_integrity",
        ROOT / "scripts" / "check_remote_raw_integrity.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_remote_raw_integrity"] = module
    spec.loader.exec_module(module)
    return module


def test_ref_is_branch_alias(monkeypatch) -> None:
    module = _load_remote_raw_module()
    calls = []

    def fake_fetch_raw(repo: str, branch: str, path: str, timeout: int = 20):
        calls.append((repo, branch, path, timeout))
        return module.RawResult(path=path, status="OK", lines=1, max_line=1, bytes=1)

    monkeypatch.setattr(module, "fetch_raw", fake_fetch_raw)

    code = module.main(["--repo", "Kidrage/AgentLab", "--ref", "main", "README.md"])

    assert code == 0
    assert calls == [("Kidrage/AgentLab", "main", "README.md", 20)]


def test_branch_argument_still_works(monkeypatch) -> None:
    module = _load_remote_raw_module()
    calls = []

    def fake_fetch_raw(repo: str, branch: str, path: str, timeout: int = 20):
        calls.append((repo, branch, path, timeout))
        return module.RawResult(path=path, status="OK", lines=1, max_line=1, bytes=1)

    monkeypatch.setattr(module, "fetch_raw", fake_fetch_raw)

    code = module.main(["--repo", "Kidrage/AgentLab", "--branch", "main", "README.md"])

    assert code == 0
    assert calls == [("Kidrage/AgentLab", "main", "README.md", 20)]


def test_default_critical_files_cover_ci_and_s6_recovery() -> None:
    module = _load_remote_raw_module()

    expected = {
        ".github/workflows/ci.yml",
        "scripts/audit_text_integrity.py",
        "tests/test_repository_text_integrity.py",
        "agent_runtime/recovery/failure_taxonomy.py",
        "agent_runtime/recovery/alternative_route_planner.py",
        "agent_runtime/recovery/capability_gap_resolver.py",
        "agent_runtime/recovery/escalation_policy.py",
        "agent_runtime/recovery/fake_evidence_detector.py",
        "config/recovery_strategy_policy.yml",
        "config/failure_taxonomy.yml",
        "config/evidence_integrity_policy.yml",
        "docs/S6_RECOVERY_BRAIN.md",
        "tests/test_s6_recovery_brain.py",
    }

    assert expected.issubset(set(module.CRITICAL_FILES))


def test_physical_lf_line_count_does_not_accept_unicode_separator() -> None:
    module = _load_remote_raw_module()

    assert module.physical_lf_line_count("one\u2028two\n".encode("utf-8")) == 1


def test_fetch_raw_flags_hidden_unicode_separator(monkeypatch) -> None:
    module = _load_remote_raw_module()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return "one\u2028two\n".encode("utf-8")

    def fake_urlopen(url: str, timeout: int = 20) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    result = module.fetch_raw("Kidrage/AgentLab", "main", "README.md")

    assert result.status == "SUSPICIOUS"
    assert result.lines == 1
    assert "U+2028 LINE SEPARATOR" in result.issue
