from pathlib import Path
import pytest
import yaml

from agent_runtime.context_governance.context_pack import build_context_artifacts
from agent_runtime.knowledge_system import InsufficientEvidenceError


def test_context_pack_has_sections_omissions_externalized_and_evidence(tmp_path: Path):
    root = tmp_path
    run_dir = root / "projects" / "AgentLab" / "runs" / "task_x"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("csv table dataframe data stream", encoding="utf-8")
    artifacts = build_context_artifacts(root, "AgentLab", "task_x")
    assert set(artifacts) == {
        "context_profile",
        "context_budget",
        "context_pack",
        "compression_trace",
    }
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


def test_narrative_pack_uses_only_canonical_content_fact_sources(tmp_path: Path):
    root = tmp_path
    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "long_project_governance.yml").write_text(
        yaml.safe_dump(
            {
                "project_constitutions": {
                    "longform_text_project": {
                        "required_artifacts": [],
                        "must_read_patterns": [
                            "project_artifact_index.yml",
                            "project_brain/project_fact_snapshot.yml",
                            "production/bible/**/*.md",
                            "production/outlines/**/*.md",
                            "production/manuscript/第0*.md",
                        ],
                    }
                }
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    project_root = root / "projects" / "NovelGen"
    run_dir = project_root / "runs" / "task_story"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("write the next novel chapter with continuity", encoding="utf-8")
    for rel in [
        "project_artifact_index.yml",
        "project_brain/project_fact_snapshot.yml",
        "project_brain/artifact_version_policy.yml",
        "production/bible/world.md",
        "production/outlines/volume.md",
        "production/manuscript/第001章.md",
        "v2_rewrite/rewrite_blueprint_v2.md",
        "candidates/task_story/world.md",
        "archive/world/v1.md",
    ]:
        path = project_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel, encoding="utf-8")

    pack = build_context_artifacts(root, "NovelGen", "task_story")["context_pack"]
    dumped = yaml.safe_dump(pack, sort_keys=False, allow_unicode=True)

    assert "production/bible/world.md" in dumped
    assert "production/outlines/volume.md" in dumped
    assert "production/manuscript/第001章.md" in dumped
    assert "project_brain/project_fact_snapshot.yml" in dumped
    assert "v2_rewrite/rewrite_blueprint_v2.md" not in dumped
    assert "candidates/task_story/world.md" not in dumped
    assert "archive/world/v1.md" not in dumped
    assert any("v2_rewrite is not a formal narrative fact source" in warning for warning in pack["warnings"])


def _enable_knowledge(root: Path, mode: str) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "knowledge_system.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "mode": mode,
                "auto_memory": "propose_only",
                "retrieval": {"top_k": 4, "required_channels": ["keyword"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _knowledge_source(root: Path, phrase: str) -> None:
    path = root / "agent_runtime" / "knowledge_target.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"POLICY = {phrase!r}\n", encoding="utf-8")


def test_knowledge_shadow_traces_without_injecting_context(tmp_path: Path):
    root = tmp_path
    _enable_knowledge(root, "shadow")
    _knowledge_source(root, "SHADOW-COMET-EVIDENCE")

    artifacts = build_context_artifacts(
        root,
        "AgentLab",
        "task_shadow",
        request_text="find SHADOW-COMET-EVIDENCE in the code repo",
    )

    assert artifacts["knowledge_context"]["status"] == "READY"
    assert artifacts["knowledge_context"]["mode"] == "shadow"
    assert not any(
        section["section_id"].startswith("knowledge_evidence_")
        for section in artifacts["context_pack"]["packed_sections"]
    )
    assert not any(
        evidence.get("kind") == "knowledge_evidence"
        for evidence in artifacts["context_pack"]["evidence_refs"]
    )


def test_knowledge_assist_injects_governed_evidence(tmp_path: Path):
    root = tmp_path
    _enable_knowledge(root, "assist")
    _knowledge_source(root, "ASSIST-ORBIT-EVIDENCE")

    artifacts = build_context_artifacts(
        root,
        "AgentLab",
        "task_assist",
        request_text="find ASSIST-ORBIT-EVIDENCE in the code repo",
    )

    sections = artifacts["context_pack"]["packed_sections"]
    evidence_refs = artifacts["context_pack"]["evidence_refs"]
    assert any(section["section_id"].startswith("knowledge_evidence_") for section in sections)
    knowledge_ref = next(item for item in evidence_refs if item.get("kind") == "knowledge_evidence")
    assert knowledge_ref["locator"].startswith(knowledge_ref["path"] + "#L")
    assert len(knowledge_ref["content_hash"]) == 64
    assert knowledge_ref["authority"] == "canonical"
    assert knowledge_ref["lifecycle"] == "active"
    assert knowledge_ref["retrieval_trace_id"]


def test_knowledge_enforce_fails_closed_when_evidence_is_missing(tmp_path: Path):
    root = tmp_path
    _enable_knowledge(root, "enforce")

    with pytest.raises(InsufficientEvidenceError, match="INSUFFICIENT_EVIDENCE"):
        build_context_artifacts(
            root,
            "AgentLab",
            "task_enforce",
            request_text="find ABSENT-NARWHAL-EVIDENCE in the code repo",
        )
