from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion import github_reader
from ingestion.github_reader import RawFileResult, RepoTree


def test_manifest_records_resolved_commit_from_mock_ref(monkeypatch) -> None:
    monkeypatch.setattr(github_reader, "fetch_resolved_commit", lambda ref: "abc123")
    monkeypatch.setattr(github_reader, "fetch_repo_tree", lambda ref, recursive=True: RepoTree(entries=[]))
    manifest = github_reader.build_repo_manifest("https://github.com/Kidrage/AgentLab", policy={"limits": {}, "default_excludes": []})
    assert manifest.resolved_commit == "abc123"


def test_manifest_warns_when_commit_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(github_reader, "fetch_resolved_commit", lambda ref: None)
    monkeypatch.setattr(github_reader, "fetch_repo_tree", lambda ref, recursive=True: RepoTree(entries=[]))
    manifest = github_reader.build_repo_manifest("https://github.com/Kidrage/AgentLab", policy={"limits": {}, "default_excludes": []})
    assert manifest.resolved_commit is None
    assert "resolved_commit_unavailable" in manifest.warnings