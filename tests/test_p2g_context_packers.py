from pathlib import Path
import yaml

from agent_runtime.context_governance.context_pack import build_context_artifacts


def test_context_pack_has_sections_omissions_externalized_and_evidence(tmp_path: Path):
    root = tmp_path
    run_dir = root / "projects" / "AgentLab" / "runs" / "task_x"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("csv table dataframe data stream", encoding="utf-8")
    artifacts = build_context_artifacts(root, "AgentLab", "task_x")
    pack = artifacts["context_pack"]
    assert pack["packed_sections"]
    assert pack["omitted_sections"]
    assert pack["externalized_artifacts"]
    assert pack["evidence_refs"]
    dumped = yaml.safe_dump(pack, sort_keys=False)
    yaml.safe_load(dumped)
    assert len(dumped) < 70000


def test_repo_pack_no_full_repo_and_tool_externalizes(tmp_path: Path):
    root = tmp_path
    run_dir = root / "projects" / "AgentLab" / "runs" / "task_repo"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("github repository refactor src/ tests/", encoding="utf-8")
    repo = build_context_artifacts(root, "AgentLab", "task_repo")["context_pack"]
    assert any("full repo" in o["reason"].lower() for o in repo["omitted_sections"])
    assert repo["profile"]["compression_safety"] == "no_lossy_compression"

    run_dir2 = root / "projects" / "AgentLab" / "runs" / "task_tool"
    run_dir2.mkdir(parents=True)
    (run_dir2 / "user_request.md").write_text("huge tool output stdout stderr exit code", encoding="utf-8")
    tool = build_context_artifacts(root, "AgentLab", "task_tool")["context_pack"]
    assert tool["externalized_artifacts"]
