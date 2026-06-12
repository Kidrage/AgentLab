from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.repo_manifest import RepoManifest
import pipeline_runner


def test_pipeline_repo_analysis_generates_manifest_without_clone(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_repo"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Repo analysis https://github.com/Kidrage/AgentLab", encoding="utf-8")
    monkeypatch.setattr(pipeline_runner, "build_repo_manifest", lambda url, **kwargs: RepoManifest(repo_url=url, owner="Kidrage", repo="AgentLab", files_read=[{"path": "README.md"}]))

    paths = pipeline_runner.ensure_repo_manifest_for_run(tmp_path, "Demo", "task_repo")

    assert paths
    assert (run_dir / "repo_manifest.json").exists()
    ledger = yaml.safe_load((run_dir / "resource_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["repo_access"]["clone_performed"] is False


def test_pipeline_multiple_github_urls_generate_manifests(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_multi"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Repo analysis https://github.com/a/one and https://github.com/b/two", encoding="utf-8")

    def fake_build(url, **kwargs):
        owner, repo = url.rstrip("/").split("/")[-2:]
        return RepoManifest(repo_url=url, owner=owner, repo=repo)

    monkeypatch.setattr(pipeline_runner, "build_repo_manifest", fake_build)
    paths = pipeline_runner.ensure_repo_manifest_for_run(tmp_path, "Demo", "task_multi")
    assert len(paths) == 2
    assert (run_dir / "repo_manifests" / "a__one.json").exists()
    assert (run_dir / "repo_manifests" / "b__two.json").exists()


def test_pipeline_manifest_failure_records_warning_not_crash(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_fail"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Repo analysis https://github.com/Kidrage/AgentLab", encoding="utf-8")
    monkeypatch.setattr(pipeline_runner, "build_repo_manifest", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("api down")))
    paths = pipeline_runner.ensure_repo_manifest_for_run(tmp_path, "Demo", "task_fail")
    assert paths
    data = (run_dir / "repo_manifest.json").read_text(encoding="utf-8")
    assert "repo_manifest_build_failed" in data