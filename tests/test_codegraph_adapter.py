from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter


def test_rejects_remote_github_url() -> None:
    decision = CodeGraphAdapter({"enabled": True}).can_index(Path("https://github.com/openai/codex"), mode="repo_patch")
    assert decision.action == "deny"


def test_rejects_missing_local_path(tmp_path: Path) -> None:
    decision = CodeGraphAdapter({"enabled": True}).can_index(tmp_path / "missing", mode="repo_patch")
    assert decision.action == "deny"


def test_repo_profile_denies_indexing(tmp_path: Path) -> None:
    decision = CodeGraphAdapter({"enabled": True}).can_index(tmp_path, mode="repo_profile")
    assert decision.action == "deny"


def test_disabled_returns_setup_required_not_execution(tmp_path: Path) -> None:
    result = CodeGraphAdapter({"enabled": False}).index_repo(tmp_path, dry_run=True)
    assert result.performed is False
    assert result.decision.action == "setup_required"


def test_missing_cli_setup_required(tmp_path: Path) -> None:
    adapter = CodeGraphAdapter({"enabled": True, "codegraph": {"command": "definitely-missing-codegraph"}}, which=lambda _: None)
    assert adapter.status(tmp_path).status == "setup_required"


def test_dry_run_does_not_execute_subprocess(tmp_path: Path) -> None:
    def runner(*args, **kwargs):  # pragma: no cover
        raise AssertionError("runner should not execute")

    adapter = CodeGraphAdapter({"enabled": True}, runner=runner, which=lambda _: "/bin/true")
    result = adapter.index_repo(tmp_path, dry_run=True, approve_indexing=True)
    assert result.performed is False

