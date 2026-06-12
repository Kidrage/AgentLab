from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion import github_reader
from ingestion.github_reader import RawFileResult, RepoTree, parse_github_url
from ingestion.resource_ledger import ResourceLedger, write_resource_ledger


def test_parse_github_url_owner_repo_ref() -> None:
    ref = parse_github_url("https://github.com/Kidrage/AO-SpatialAuthoring-Modular/tree/dev")

    assert ref.owner == "Kidrage"
    assert ref.repo == "AO-SpatialAuthoring-Modular"
    assert ref.ref == "dev"


def test_build_repo_manifest_api_only_targeted_fetch(monkeypatch) -> None:
    def fake_tree(repo_ref, recursive=True):
        return RepoTree(entries=[
            {"path": "README.md", "type": "blob", "size": 20},
            {"path": "package.json", "type": "blob", "size": 40},
            {"path": "dist/app.js", "type": "blob", "size": 10},
            {"path": "large.md", "type": "blob", "size": 300 * 1024},
        ])

    def fake_raw(repo_ref, path):
        return RawFileResult(path=path, content=f"content for {path}", bytes_downloaded=10)

    monkeypatch.setattr(github_reader, "fetch_repo_tree", fake_tree)
    monkeypatch.setattr(github_reader, "fetch_raw_file", fake_raw)

    manifest = github_reader.build_repo_manifest(
        "https://github.com/Kidrage/AgentLab",
        policy={
            "limits": {
                "max_api_tree_entries": 100000,
                "max_single_file_kb": 256,
                "max_files_read": 100,
                "max_total_text_mb": 5,
            },
            "default_excludes": ["dist/**"],
        },
    )

    assert manifest.clone_performed is False
    assert [item["path"] for item in manifest.files_read] == ["README.md", "package.json"]
    assert manifest.bytes_downloaded == 20
    assert any(item["path"] == "dist/app.js" for item in manifest.files_skipped_by_policy)


def test_resource_ledger_from_manifest(tmp_path: Path, monkeypatch) -> None:
    def fake_tree(repo_ref, recursive=True):
        return RepoTree(entries=[{"path": "README.md", "type": "blob", "size": 20}])

    def fake_raw(repo_ref, path):
        return RawFileResult(path=path, content="hello", bytes_downloaded=5)

    monkeypatch.setattr(github_reader, "fetch_repo_tree", fake_tree)
    monkeypatch.setattr(github_reader, "fetch_raw_file", fake_raw)
    manifest = github_reader.build_repo_manifest("https://github.com/Kidrage/AgentLab")

    ledger = ResourceLedger.from_manifest("task_repo", manifest)
    path = write_resource_ledger(tmp_path, ledger)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["repo_access"]["clone_performed"] is False
    assert data["repo_access"]["files_read"] == 1
    assert data["repo_access"]["bytes_downloaded"] == 5
