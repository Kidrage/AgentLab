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
