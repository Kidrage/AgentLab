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
