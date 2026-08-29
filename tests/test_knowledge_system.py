from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3

import pytest
import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.knowledge_system import (
    AuthorityLevel,
    KnowledgeRecord,
    KnowledgeTaskRequest,
    Modality,
    SourceRef,
    activate_knowledge_mode,
    build_knowledge_base,
    evaluate_outcome,
    import_legacy_jsonl,
    knowledge_status,
    prepare_task,
    sync_committed,
    validate_knowledge_stage,
)
from agent_runtime.local_search.document import Document, SourceCategory
from agent_runtime.local_search.storage import save_index
from agent_runtime.knowledge_system.storage import KnowledgeStore
from agent_runtime.knowledge_system.sources import SourceCollector


def _write_config(
    root: Path,
    *,
    mode: str = "assist",
    required_channels: list[str] | None = None,
    keyword_backend: str = "auto",
    refresh_on_prepare: bool | None = None,
    bootstrap_missing_spaces: bool | None = None,
    project_allowlist: list[str] | None = None,
) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "knowledge_system.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "mode": mode,
                "auto_memory": "propose_only",
                "storage": {"keyword_backend": keyword_backend},
                "indexing": {
                    "project_allowlist": (
                        project_allowlist if project_allowlist is not None else ["*"]
                    ),
                    **(
                        {"refresh_on_prepare": refresh_on_prepare}
                        if refresh_on_prepare is not None
                        else {}
                    ),
                    **(
                        {"bootstrap_missing_spaces": bootstrap_missing_spaces}
                        if bootstrap_missing_spaces is not None
                        else {}
                    ),
                },
                "retrieval": {
                    "top_k": 6,
                    "required_channels": required_channels or ["keyword"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_current_artifacts(root: Path, project: str, *production_paths: str) -> None:
    artifact_index = root / "projects" / project / "project_artifact_index.yml"
    artifact_index.parent.mkdir(parents=True, exist_ok=True)
    artifact_index.write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "project": project,
                "artifacts": [
                    {
                        "artifact_id": f"current_{index}",
                        "status": "current",
                        "production_path": production_path,
                        "production_sha256": artifact_sha256(
                            root / "projects" / project / production_path
                        ),
                        "evidence_only": False,
                    }
                    for index, production_path in enumerate(production_paths, start=1)
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_global_build_reconciles_indexes_to_configured_project_allowlist(tmp_path: Path) -> None:
    root = tmp_path
    projects = {
        "AgentLab": "AGENTLAB-ALLOWLIST-EVIDENCE",
        "Crown_of_Ash": "CROWN-ALLOWLIST-EVIDENCE",
        "NovelGen": "NOVELGEN-ALLOWLIST-EVIDENCE",
        "DemoProject": "DEMO-MEMORY-POLLUTION",
        "demo_video_generation": "DEMO-VIDEO-MEMORY-POLLUTION",
    }
    for project, marker in projects.items():
        source = root / "projects" / project / "project_brain" / "facts.yml"
        source.parent.mkdir(parents=True)
        source.write_text(f"fact: {marker}\n", encoding="utf-8")

    _write_config(root)
    first = build_knowledge_base(root, include_all_projects=True)
    assert "project.DemoProject" in first["namespaces"]

    _write_config(
        root,
        project_allowlist=["AgentLab", "Crown_of_Ash", "NovelGen"],
    )
    receipt = build_knowledge_base(root, include_all_projects=True)
    status = knowledge_status(root)

    assert receipt["projects"] == ["AgentLab", "Crown_of_Ash", "NovelGen"]
    assert status["project_allowlist"] == ["AgentLab", "Crown_of_Ash", "NovelGen"]
    assert set(receipt["retired_namespaces"]) == {
        "project.DemoProject",
        "project.demo_video_generation",
        "domain.media_production",
    }
    assert receipt["purged_record_counts"]["domain.code_engineering"] > 0
    assert receipt["purged_record_counts"]["domain.media_production"] > 0
    assert {item["namespace"] for item in status["spaces"]} == {
        "system.agentlab",
        "project.AgentLab",
        "project.Crown_of_Ash",
        "project.NovelGen",
        "domain.code_engineering",
        "domain.longform_narrative",
    }
    assert (root / "projects" / "DemoProject" / "project_brain" / "facts.yml").is_file()
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    assert store.search(
        ("domain.code_engineering", "domain.longform_narrative"),
        "DEMO-MEMORY-POLLUTION",
        max_results=10,
    ) == []


def test_retire_spaces_rejects_catalog_paths_outside_managed_shard_directory(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path, ".agentlab_runtime/knowledge", "auto")
    store.ensure_space("project.DemoProject")
    protected = store.root / "protected.txt"
    protected.write_text("must survive\n", encoding="utf-8")
    with sqlite3.connect(store.catalog_path) as catalog:
        catalog.execute(
            "UPDATE spaces SET db_name = ? WHERE namespace = ?",
            ("../protected.txt", "project.DemoProject"),
        )

    with pytest.raises(ValueError, match="invalid knowledge shard filename"):
        store.retire_spaces(("project.DemoProject",))

    assert protected.read_text(encoding="utf-8") == "must survive\n"
    assert store.space_exists("project.DemoProject") is True


def test_explicit_build_rejects_project_outside_allowlist(tmp_path: Path) -> None:
    root = tmp_path
    demo_source = root / "projects" / "DemoProject" / "project_brain" / "facts.yml"
    demo_source.parent.mkdir(parents=True)
    demo_source.write_text("fact: MUST-NOT-BE-INDEXED\n", encoding="utf-8")

    with pytest.raises(ValueError, match="project_allowlist: DemoProject"):
        build_knowledge_base(root, projects=["DemoProject"])

    assert {item["namespace"] for item in knowledge_status(root)["spaces"]} == {
        "system.agentlab"
    }


def test_build_knowledge_base_discovers_system_project_and_domain_spaces(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, mode="off")
    system_source = root / "agent_runtime" / "engine.py"
    system_source.parent.mkdir(parents=True)
    system_source.write_text("AGENTLAB-SCAFFOLD-EVIDENCE\n", encoding="utf-8")
    protocol = root / "_shared" / "AGENT_PROTOCOL.md"
    protocol.parent.mkdir(parents=True)
    protocol.write_text("GOVERNED-PROTOCOL-EVIDENCE\n", encoding="utf-8")

    project = root / "projects" / "Crown_of_Ash"
    project_sources = {
        "project_brain/world.yml": "canon: ASH-WORLD-CANON\n",
        "production/chapter_001.md": "ASH-CHAPTER-ACCEPTED\n",
        "candidates/chapter_002.md": "ASH-DRAFT-CANDIDATE\n",
        "runs/task_001/audit.md": "ASH-RUN-AUDIT\n",
        "参考资料/source.md": "ASH-EXTERNAL-REFERENCE\n",
    }
    for relative, content in project_sources.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _write_current_artifacts(root, "Crown_of_Ash", "production/chapter_001.md")

    receipt = build_knowledge_base(root, include_all_projects=True)
    status = knowledge_status(root)

    assert receipt["status"] == "BUILT"
    assert receipt["projects"] == ["Crown_of_Ash"]
    assert receipt["project_domains"] == {"Crown_of_Ash": "longform_narrative"}
    assert set(receipt["namespaces"]) == {
        "system.agentlab",
        "domain.longform_narrative",
        "project.Crown_of_Ash",
    }
    assert status["mode"] == "off"
    assert status["storage_inside_agentlab"] is True
    spaces = {item["namespace"]: item for item in status["spaces"]}
    assert spaces["system.agentlab"]["record_count"] >= 2
    assert spaces["project.Crown_of_Ash"]["authority_counts"] == {
        "accepted": 1,
        "audit": 1,
        "candidate": 1,
        "canonical": 2,
        "external": 1,
    }
    assert spaces["domain.longform_narrative"]["record_count"] == 6


def test_project_retrieval_uses_only_manifest_selected_production(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    project = root / "projects" / "Novel"
    selected = project / "production" / "selected.md"
    selected.parent.mkdir(parents=True)
    selected.write_text("SELECTED-PRODUCTION-GOLD-EVIDENCE\n", encoding="utf-8")
    for relative in (
        "production/orphan.md",
        "artifacts/draft.md",
        "agent_docs/handoff.md",
        "docs/notes.md",
        "prompt_templates/writer.md",
        "skills/story/SKILL.md",
        "tasks/task.yml",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("UNGOVERNED-PROJECT-SCARLET-EVIDENCE\n", encoding="utf-8")
    _write_current_artifacts(
        root,
        "Novel",
        "production/selected.md",
        "artifacts/draft.md",
    )

    selected_result = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_selected_production",
            "SELECTED-PRODUCTION-GOLD-EVIDENCE",
            "longform_narrative",
        )
    )
    ungoverned_result = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_unselected_sources",
            "UNGOVERNED-PROJECT-SCARLET-EVIDENCE",
            "longform_narrative",
        )
    )

    assert selected_result.status == "READY"
    assert {item.source.path for item in selected_result.evidence_bundle.items} == {
        "projects/Novel/production/selected.md"
    }
    assert ungoverned_result.status == "INSUFFICIENT_EVIDENCE"
    assert ungoverned_result.evidence_bundle.items == ()


def test_manifest_selected_production_is_rejected_after_hash_tamper(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    selected = root / "projects" / "Novel" / "production" / "selected.md"
    selected.parent.mkdir(parents=True)
    selected.write_text("ORIGINALONLYZEBRA123\n", encoding="utf-8")
    _write_current_artifacts(root, "Novel", "production/selected.md")
    request = KnowledgeTaskRequest(
        root,
        "Novel",
        "task_manifest_hash",
        "ORIGINALONLYZEBRA123",
        "longform_narrative",
    )
    assert prepare_task(request).status == "READY"

    selected.write_text("TAMPEREDONLYRUBY456\n", encoding="utf-8")
    prepared = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_manifest_hash_tampered",
            "TAMPEREDONLYRUBY456",
            "longform_narrative",
        )
    )

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.items == ()


def test_manifest_selected_directory_is_rejected_after_member_tamper(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    chapter = root / "projects" / "Novel" / "production" / "manuscript" / "chapter.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("DIRECTORY-MANIFEST-ORIGINAL-FACT\n", encoding="utf-8")
    _write_current_artifacts(root, "Novel", "production/manuscript")
    assert prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_directory_manifest",
            "DIRECTORY-MANIFEST-ORIGINAL-FACT",
            "longform_narrative",
        )
    ).status == "READY"

    chapter.write_text("DIRECTORY-MANIFEST-TAMPERED-FACT\n", encoding="utf-8")
    prepared = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_directory_manifest_tampered",
            "DIRECTORY-MANIFEST-TAMPERED-FACT",
            "longform_narrative",
        )
    )

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.items == ()


def test_generic_artifact_cannot_bypass_narrative_release_lineage(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    edition = root / "projects" / "Novel" / "release_objects" / "editions" / "bypass"
    edition.mkdir(parents=True)
    (edition / "chapter_001.md").write_text("DECLARED-EDITION-EVIDENCE\n", encoding="utf-8")
    (edition / "chapter_999.md").write_text("BYPASS-EDITION-EVIDENCE\n", encoding="utf-8")
    index = edition.parents[2] / "project_artifact_index.yml"
    index.write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "forged_release_directory",
                        "status": "current",
                        "production_path": "release_objects/editions/bypass",
                        "production_sha256": artifact_sha256(edition),
                        "evidence_only": False,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    build_knowledge_base(root, projects=("Novel",))
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")

    assert store.search(
        ("project.Novel",),
        "BYPASS-EDITION-EVIDENCE",
        max_results=10,
        project_id="Novel",
    ) == []


def test_manifest_selected_production_rejects_symlinked_candidate_content(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(root)
    project = root / "projects" / "Novel"
    candidate = project / "candidates" / "manuscript"
    candidate.mkdir(parents=True)
    (candidate / "chapter.md").write_text("SYMLINK-CANDIDATE-EVIDENCE\n", encoding="utf-8")
    production = project / "production"
    production.mkdir()
    (production / "manuscript").symlink_to(candidate, target_is_directory=True)
    index = project / "project_artifact_index.yml"
    index.write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "forged_production_link",
                        "status": "current",
                        "production_path": "production/manuscript",
                        "production_sha256": artifact_sha256(candidate),
                        "evidence_only": False,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    build_knowledge_base(root, projects=("Novel",))
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")

    assert store.search(
        ("project.Novel",),
        "SYMLINK-CANDIDATE-EVIDENCE",
        max_results=10,
        project_id="Novel",
    ) == []


def test_project_brain_rejects_symlink_to_another_project(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    beta_brain = root / "projects" / "Beta" / "project_brain"
    beta_brain.mkdir(parents=True)
    (beta_brain / "facts.yml").write_text(
        "fact: SYMLINK-CROSS-PROJECT-EVIDENCE\n",
        encoding="utf-8",
    )
    alpha = root / "projects" / "Alpha"
    alpha.mkdir(parents=True)
    (alpha / "project_brain").symlink_to(beta_brain, target_is_directory=True)

    build_knowledge_base(root, projects=("Alpha",))
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")

    assert store.search(
        ("project.Alpha",),
        "SYMLINK-CROSS-PROJECT-EVIDENCE",
        max_results=10,
        project_id="Alpha",
    ) == []


def test_system_source_root_rejects_symlink_to_candidate_content(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    candidates = root / "projects" / "Victim" / "candidates"
    candidates.mkdir(parents=True)
    (candidates / "draft.md").write_text(
        "SYMLINK-SYSTEM-CANDIDATE-EVIDENCE\n",
        encoding="utf-8",
    )
    (root / "docs").symlink_to(candidates, target_is_directory=True)

    build_knowledge_base(root, projects=("Alpha",))
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")

    assert store.search(
        ("system.agentlab",),
        "SYMLINK-SYSTEM-CANDIDATE-EVIDENCE",
        max_results=10,
        project_id="Alpha",
    ) == []


def test_project_collection_rejects_symlinked_projects_root(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    forged = root / "candidate_projects" / "Alpha" / "project_brain"
    forged.mkdir(parents=True)
    (forged / "facts.md").write_text(
        "SYMLINK-PROJECTS-ROOT-EVIDENCE\n",
        encoding="utf-8",
    )
    (root / "projects").symlink_to(root / "candidate_projects", target_is_directory=True)

    build_knowledge_base(root, projects=("Alpha",))
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")

    assert store.search(
        ("project.Alpha",),
        "SYMLINK-PROJECTS-ROOT-EVIDENCE",
        max_results=10,
        project_id="Alpha",
    ) == []


def test_system_archives_are_auditable_but_never_eligible_evidence(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    current = root / "docs" / "current.md"
    archived = root / "docs" / "archive" / "old.md"
    current.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    current.write_text("CURRENT-SYSTEM-TEAL-EVIDENCE\n", encoding="utf-8")
    archived.write_text("ARCHIVED-SYSTEM-TEAL-EVIDENCE\n", encoding="utf-8")

    build_knowledge_base(root)

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    assert store.search(
        ("system.agentlab",),
        "CURRENT-SYSTEM-TEAL-EVIDENCE",
        max_results=10,
    )
    assert store.search(
        ("system.agentlab",),
        "ARCHIVED-SYSTEM-TEAL-EVIDENCE",
        max_results=10,
    ) == []
    space = knowledge_status(root)["spaces"][0]
    assert space["authority_counts"] == {"audit": 1, "canonical": 2}
    assert space["lifecycle_counts"] == {"active": 2, "deprecated": 1}


def test_system_scaffold_covers_runtime_tests_scripts_templates_and_web_ui(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    sources = {
        "agentlab.sh": "ROOT-ENTRY-COPPER-EVIDENCE\n",
        "tests/test_runtime.py": "TEST-CONTRACT-COPPER-EVIDENCE\n",
        "scripts/verify.py": "SCRIPT-COPPER-EVIDENCE\n",
        "agent_templates/coder.md": "TEMPLATE-COPPER-EVIDENCE\n",
        "web_ui/server.py": "WEB-COPPER-EVIDENCE\n",
        ".github/workflows/ci.yml": "CI-COPPER-EVIDENCE\n",
    }
    for relative, content in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    build_knowledge_base(root)

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    hits = store.search(
        ("system.agentlab",),
        "COPPER-EVIDENCE",
        max_results=20,
    )
    assert {hit.source.path for hit in hits} >= set(sources)


def test_activation_is_sequential_validated_and_auditable(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, mode="off")
    source = root / "agent_runtime" / "governance.py"
    source.parent.mkdir(parents=True)
    source.write_text("STAGED-RAG-GOVERNANCE-EVIDENCE\n", encoding="utf-8")

    with pytest.raises(ValueError, match="build the knowledge base"):
        activate_knowledge_mode(root, "shadow", actor="tester", reason="start rollout")

    build_knowledge_base(root)
    shadow = activate_knowledge_mode(root, "shadow", actor="tester", reason="observe retrieval")
    assert shadow["transition"] == "off->shadow"

    with pytest.raises(ValueError, match="validate shadow"):
        activate_knowledge_mode(root, "assist", actor="tester", reason="inject evidence")

    shadow_validation = validate_knowledge_stage(
        root,
        project="AgentLab",
        task_id="task_shadow_validation",
        request_text="STAGED-RAG-GOVERNANCE-EVIDENCE",
        domain="code_engineering",
    )
    assert shadow_validation["status"] == "PASS"
    assert shadow_validation["mode"] == "shadow"

    assist = activate_knowledge_mode(root, "assist", actor="tester", reason="inject evidence")
    assert assist["transition"] == "shadow->assist"
    with pytest.raises(ValueError, match="validate assist"):
        activate_knowledge_mode(root, "enforce", actor="tester", reason="enforce evidence")

    assist_validation = validate_knowledge_stage(
        root,
        project="AgentLab",
        task_id="task_assist_validation",
        request_text="STAGED-RAG-GOVERNANCE-EVIDENCE",
        domain="code_engineering",
    )
    assert assist_validation["status"] == "PASS"
    enforce = activate_knowledge_mode(root, "enforce", actor="tester", reason="enforce evidence")
    assert enforce["transition"] == "assist->enforce"

    rollback = activate_knowledge_mode(root, "assist", actor="tester", reason="keep normal tasks non-blocking")
    assert rollback["transition"] == "enforce->assist"
    assert knowledge_status(root)["mode"] == "assist"
    receipts = root / ".agentlab_runtime" / "knowledge" / "receipts"
    assert (receipts / "latest_activation.json").is_file()
    assert (receipts / "latest_validation.json").is_file()


def test_task_bootstraps_missing_spaces_once_without_rescanning_every_request(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(
        root,
        mode="assist",
        refresh_on_prepare=False,
        bootstrap_missing_spaces=True,
    )
    source = root / "projects" / "Crown_of_Ash" / "project_brain" / "world.yml"
    source.parent.mkdir(parents=True)
    source.write_text("fact: ONCE-INDEXED-ASH-EVIDENCE\n", encoding="utf-8")
    request = KnowledgeTaskRequest(
        root,
        "Crown_of_Ash",
        "task_bootstrap_001",
        "ONCE-INDEXED-ASH-EVIDENCE",
        "longform_narrative",
    )

    first = prepare_task(request)
    first_status = knowledge_status(root)
    source.write_text("fact: CHANGED-BUT-NOT-COMMITTED\n", encoding="utf-8")
    second = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Crown_of_Ash",
            "task_bootstrap_002",
            "ONCE-INDEXED-ASH-EVIDENCE",
            "longform_narrative",
        )
    )
    second_status = knowledge_status(root)

    assert first.status == "READY"
    assert second.status == "READY"
    first_paths = [item.source.path for item in first.evidence_bundle.items]
    assert len(first_paths) == len(set(first_paths))
    assert first.evidence_bundle.items[0].namespace == "project.Crown_of_Ash"
    spaces = {item["namespace"]: item for item in first_status["spaces"]}
    assert spaces["system.agentlab"]["record_count"] >= 1
    assert spaces["project.Crown_of_Ash"]["record_count"] == 1
    assert spaces["domain.longform_narrative"]["record_count"] == 1
    assert {
        item["namespace"]: item["revision"] for item in first_status["spaces"]
    } == {
        item["namespace"]: item["revision"] for item in second_status["spaces"]
    }


def test_task_outside_allowlist_uses_system_knowledge_without_creating_project_memory(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(
        root,
        mode="assist",
        refresh_on_prepare=False,
        bootstrap_missing_spaces=True,
        project_allowlist=["AgentLab", "Crown_of_Ash", "NovelGen"],
    )
    system_source = root / "agent_runtime" / "policy.py"
    system_source.parent.mkdir(parents=True)
    system_source.write_text("SYSTEM-ONLY-GOVERNANCE-EVIDENCE\n", encoding="utf-8")
    demo_source = root / "projects" / "DemoProject" / "project_brain" / "facts.yml"
    demo_source.parent.mkdir(parents=True)
    demo_source.write_text("fact: DEMO-MUST-STAY-OUT\n", encoding="utf-8")

    prepared = prepare_task(
        KnowledgeTaskRequest(
            root,
            "DemoProject",
            "task_demo_without_memory",
            "SYSTEM-ONLY-GOVERNANCE-EVIDENCE",
            "code_engineering",
        )
    )

    assert prepared.status == "READY"
    assert prepared.requirement.namespaces == ("system.agentlab",)
    assert prepared.warnings == (
        "project DemoProject is excluded by knowledge indexing.project_allowlist; "
        "retrieval is limited to system knowledge",
    )
    assert {item["namespace"] for item in knowledge_status(root)["spaces"]} == {
        "system.agentlab"
    }
    assert all(item.source.path != "projects/DemoProject/project_brain/facts.yml" for item in prepared.evidence_bundle.items)


def test_task_outside_allowlist_cannot_read_another_projects_shared_domain(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(
        root,
        mode="assist",
        refresh_on_prepare=False,
        bootstrap_missing_spaces=True,
        project_allowlist=["AgentLab", "Crown_of_Ash", "NovelGen"],
    )
    source = root / "projects" / "AgentLab" / "project_brain" / "facts.yml"
    source.parent.mkdir(parents=True)
    source.write_text("fact: SHARED-CODE-DOMAIN-EVIDENCE\n", encoding="utf-8")
    build_knowledge_base(root, projects=["AgentLab"])
    before = {
        item["namespace"]: item["revision"] for item in knowledge_status(root)["spaces"]
    }

    prepared = prepare_task(
        KnowledgeTaskRequest(
            root,
            "DemoProject",
            "task_demo_shared_domain",
            "SHARED-CODE-DOMAIN-EVIDENCE",
            "code_engineering",
        )
    )
    after_status = knowledge_status(root)

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.requirement.namespaces == (
        "system.agentlab",
        "domain.code_engineering",
    )
    assert prepared.evidence_bundle.items == ()
    assert "project.DemoProject" not in {
        item["namespace"] for item in after_status["spaces"]
    }
    assert before == {
        item["namespace"]: item["revision"] for item in after_status["spaces"]
    }


def test_task_bootstraps_its_domain_membership_when_domain_already_exists(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(
        root,
        mode="assist",
        refresh_on_prepare=False,
        bootstrap_missing_spaces=True,
    )
    for project, marker in (
        ("NovelOne", "NOVEL-ONE-LILAC"),
        ("NovelTwo", "NOVEL-TWO-LILAC"),
    ):
        path = root / "projects" / project / "project_brain" / "world.yml"
        path.parent.mkdir(parents=True)
        path.write_text(f"fact: {marker}\n", encoding="utf-8")

    for project, marker in (
        ("NovelOne", "NOVEL-ONE-LILAC"),
        ("NovelTwo", "NOVEL-TWO-LILAC"),
    ):
        prepared = prepare_task(
            KnowledgeTaskRequest(
                root,
                project,
                f"task_{project.lower()}",
                marker,
                "longform_narrative",
            )
        )
        assert prepared.status == "READY"

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    assert store.search(
        ("domain.longform_narrative",),
        "LILAC",
        max_results=10,
    ) == []
    hits = store.search(
        ("domain.longform_narrative",),
        "LILAC",
        max_results=10,
        allow_cross_project=True,
    )
    assert {hit.project_id for hit in hits} == {"NovelOne", "NovelTwo"}


def test_global_build_indexes_large_media_as_metadata_only(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, mode="off")
    media = root / "projects" / "Film" / "production" / "score.wav"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"RIFF" + (b"0" * 1_000_100))
    _write_current_artifacts(root, "Film", "production/score.wav")

    build_knowledge_base(root, projects=["Film"], project_domains={"Film": "media_production"})
    status = knowledge_status(root)

    spaces = {item["namespace"]: item for item in status["spaces"]}
    assert spaces["project.Film"]["record_count"] == 2
    assert spaces["project.Film"]["modality_counts"] == {"audio": 1, "structured": 1}
    store = KnowledgeStore(root)
    hits = store.search(
        ["project.Film"],
        "score.wav",
        max_results=3,
        authorities=["accepted"],
        modalities=["audio"],
        project_id="Film",
    )
    assert hits[0].metadata["raw_payload_indexed"] is False


def test_rebuild_reclassifies_project_domain_and_tombstones_previous_membership(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, mode="off")
    source = root / "projects" / "AgentLab" / "project_brain" / "chapter_pipeline.yml"
    source.parent.mkdir(parents=True)
    source.write_text("feature: chapter narrative governance\n", encoding="utf-8")

    build_knowledge_base(
        root,
        projects=["AgentLab"],
        project_domains={"AgentLab": "longform_narrative"},
    )
    (root / ".agentlab_runtime" / "knowledge" / "receipts" / "latest_build.json").unlink()
    rebuilt = build_knowledge_base(root, projects=["AgentLab"])
    status = knowledge_status(root)

    assert rebuilt["project_domains"] == {"AgentLab": "code_engineering"}
    spaces = {item["namespace"]: item for item in status["spaces"]}
    assert spaces["domain.code_engineering"]["eligible_record_count"] == 1
    assert spaces["domain.longform_narrative"]["eligible_record_count"] == 0
    assert spaces["domain.longform_narrative"]["lifecycle_counts"] == {"tombstoned": 1}


def test_prepare_task_builds_namespaced_auditable_evidence(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    source = root / "agent_runtime" / "promotion.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def promote_candidate():\n    return 'governed promotion requires evidence'\n",
        encoding="utf-8",
    )
    project_brain = root / "projects" / "AgentLab" / "project_brain"
    project_brain.mkdir(parents=True)
    (project_brain / "project_fact_snapshot.yml").write_text(
        "project: AgentLab\nfacts:\n  promotion: governed promotion requires evidence\n",
        encoding="utf-8",
    )

    request = KnowledgeTaskRequest(
        agentlab_root=root,
        project="AgentLab",
        task_id="task_001",
        request_text="Where is governed promotion evidence enforced?",
        domain="code_engineering",
    )
    first = prepare_task(request)
    second = prepare_task(request)

    assert first.status == "READY"
    assert first.retrieval_view.namespaces == (
        "system.agentlab",
        "domain.code_engineering",
        "project.AgentLab",
    )
    assert first.context_ref == second.context_ref
    assert first.evidence_bundle.bundle_id == second.evidence_bundle.bundle_id
    assert first.evidence_bundle.items
    evidence = first.evidence_bundle.items[0]
    assert evidence.locator.startswith(evidence.source.path + "#L")
    assert len(evidence.source.content_hash) == 64
    assert evidence.authority in {"canonical", "accepted"}
    assert evidence.lifecycle == "active"
    assert evidence.channel == "keyword"
    assert first.evidence_bundle.trace.index_snapshot

    storage_root = root / ".agentlab_runtime" / "knowledge"
    assert (storage_root / "catalog.sqlite3").is_file()
    assert len(list((storage_root / "spaces").glob("*.sqlite3"))) == 3
    assert not list(root.glob("*.sqlite3"))


def test_source_refs_and_namespaces_reject_path_escape() -> None:
    digest = "0" * 64
    with pytest.raises(ValueError, match="unsafe knowledge source path"):
        SourceRef("/etc/passwd", digest)
    with pytest.raises(ValueError, match="unsafe knowledge source path"):
        SourceRef("docs/../../secret.txt", digest)


def test_prepare_task_isolates_projects_and_excludes_unpromoted_sources(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    for project, phrase in (("Alpha", "alpha-only governed fact"), ("Beta", "beta-only governed fact")):
        brain = root / "projects" / project / "project_brain"
        brain.mkdir(parents=True)
        (brain / "project_fact_snapshot.yml").write_text(
            f"project: {project}\nfact: {phrase}\n",
            encoding="utf-8",
        )
    alpha = root / "projects" / "Alpha"
    for relative in (
        "candidates/task_001/candidate.md",
        "runs/task_001/audit_report.md",
        "archive/facts/old.md",
    ):
        path = alpha / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("alpha-only governed fact from an ineligible source", encoding="utf-8")

    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="Alpha",
            task_id="task_002",
            request_text="alpha-only governed fact",
            domain="research",
        )
    )

    assert prepared.status == "READY"
    assert {item.namespace for item in prepared.evidence_bundle.items} == {"project.Alpha"}
    paths = {item.source.path for item in prepared.evidence_bundle.items}
    assert "projects/Alpha/project_brain/project_fact_snapshot.yml" in paths
    assert not any("candidates/" in path or "/runs/" in path or "/archive/" in path for path in paths)
    assert not any("Beta" in path for path in paths)

    with pytest.raises(ValueError, match="unsafe project"):
        prepare_task(
            KnowledgeTaskRequest(
                agentlab_root=root,
                project="../Beta",
                task_id="task_003",
                request_text="beta-only governed fact",
            )
        )


def test_prepare_task_never_reads_another_project_from_shared_domain(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    alpha = root / "projects" / "Alpha" / "project_brain" / "facts.yml"
    beta = root / "projects" / "Beta" / "project_brain" / "facts.yml"
    alpha.parent.mkdir(parents=True)
    beta.parent.mkdir(parents=True)
    alpha.write_text("fact: ALPHA-PUBLIC-FACT\n", encoding="utf-8")
    beta.write_text("fact: BETA-PRIVATE-CROSS-PROJECT-SECRET\n", encoding="utf-8")
    build_knowledge_base(
        root,
        projects=("Alpha", "Beta"),
        project_domains={
            "Alpha": "longform_narrative",
            "Beta": "longform_narrative",
        },
    )

    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="Alpha",
            task_id="task_cross_project_guard",
            request_text="BETA-PRIVATE-CROSS-PROJECT-SECRET",
            domain="longform_narrative",
        )
    )

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.items == ()


def test_candidate_audit_and_external_authority_never_enter_task_evidence(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    store = KnowledgeStore(root)
    records = []
    for authority in (
        AuthorityLevel.CANDIDATE,
        AuthorityLevel.AUDIT,
        AuthorityLevel.EXTERNAL,
    ):
        content = f"INELIGIBLE-RUBY-EVIDENCE {authority.value}"
        source = SourceRef(
            f"untrusted/{authority.value}.md",
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
            authority.value,
        )
        records.append(
            KnowledgeRecord.create(
                namespace="system.agentlab",
                project_id=None,
                source=source,
                content=content,
                authority=authority,
                modality=Modality.TEXT,
                object_kind="untrusted_source",
            )
        )
    store.sync_records("system.agentlab", records, scope="untrusted_fixture")

    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_004",
            request_text="INELIGIBLE-RUBY-EVIDENCE",
            domain="research",
        )
    )

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.items == ()


def test_prepare_task_tombstones_deleted_sources_and_recovers(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    brain = root / "projects" / "Alpha" / "project_brain"
    brain.mkdir(parents=True)
    fact = brain / "project_fact_snapshot.yml"
    fact.write_text("fact: recoverable-zebra-evidence\n", encoding="utf-8")
    request = KnowledgeTaskRequest(
        agentlab_root=root,
        project="Alpha",
        task_id="task_010",
        request_text="recoverable-zebra-evidence",
        domain="research",
    )

    initial = prepare_task(request)
    fact.unlink()
    deleted = prepare_task(request)
    fact.write_text("fact: recoverable-zebra-evidence\n", encoding="utf-8")
    recovered = prepare_task(request)

    assert initial.status == "READY"
    assert deleted.status == "INSUFFICIENT_EVIDENCE"
    assert deleted.evidence_bundle.items == ()
    assert recovered.status == "READY"
    assert recovered.evidence_bundle.items[0].record_id == initial.evidence_bundle.items[0].record_id


def test_prepare_task_applies_metadata_filters_and_reports_missing_channels(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, required_channels=["keyword", "semantic"])
    code = root / "agent_runtime" / "hidden.py"
    code.parent.mkdir(parents=True)
    code.write_text("FILTERABLE-ORCHID-EVIDENCE\n", encoding="utf-8")
    guide = root / "docs" / "guide.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("FILTERABLE-ORCHID-EVIDENCE\n", encoding="utf-8")

    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_020",
            request_text="FILTERABLE-ORCHID-EVIDENCE",
            domain="code_engineering",
            file_hints=("docs/",),
        )
    )

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.missing_channels == ("semantic",)
    assert prepared.evidence_bundle.items
    assert {item.source.path for item in prepared.evidence_bundle.items} == {"docs/guide.md"}
    assert any("semantic retrieval adapter is not configured" in warning for warning in prepared.warnings)


def test_evaluate_outcome_requires_evidence_and_only_proposes_candidate_memory(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    brain = root / "projects" / "Alpha" / "project_brain"
    brain.mkdir(parents=True)
    snapshot = brain / "project_fact_snapshot.yml"
    snapshot.write_text("fact: evidence-backed-cobalt-rule\n", encoding="utf-8")
    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="Alpha",
            task_id="task_030",
            request_text="evidence-backed-cobalt-rule",
            domain="research",
        )
    )
    original_snapshot = snapshot.read_text(encoding="utf-8")

    missing = evaluate_outcome(
        {"claims": [{"claim": "Cobalt is governed", "evidence_refs": []}]},
        prepared.context_ref,
    )
    accepted = evaluate_outcome(
        {
            "claims": [
                {
                    "claim": "Cobalt is governed",
                    "evidence_refs": [prepared.evidence_bundle.items[0].evidence_id],
                }
            ],
            "knowledge_updates": [
                {"fact": "Cobalt is governed", "authority": "canonical"}
            ],
        },
        prepared.context_ref,
    )

    assert missing.status == "INSUFFICIENT_EVIDENCE"
    assert missing.errors
    assert accepted.status == "PROPOSE_ONLY"
    assert accepted.proposed_records[0]["authority"] == "candidate"
    assert accepted.warnings
    assert snapshot.read_text(encoding="utf-8") == original_snapshot

    reloaded = evaluate_outcome(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "task_id": "task_030",
            "claims": [
                {
                    "claim": "Cobalt is governed",
                    "evidence_refs": [prepared.evidence_bundle.items[0].evidence_id],
                }
            ],
        },
        prepared.context_ref,
    )
    assert reloaded.status == "PROPOSE_ONLY"

    snapshot.write_text("fact: changed after retrieval\n", encoding="utf-8")
    stale = evaluate_outcome(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "task_id": "task_030",
            "claims": [
                {
                    "claim": "Cobalt is governed",
                    "evidence_refs": [prepared.evidence_bundle.items[0].evidence_id],
                }
            ],
        },
        prepared.context_ref,
    )
    assert stale.status == "INSUFFICIENT_EVIDENCE"
    assert any("source hash changed" in error for error in stale.errors)


def test_sync_committed_rejects_project_outside_allowlist_without_creating_memory(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(root, project_allowlist=["AgentLab", "Crown_of_Ash", "NovelGen"])
    production = root / "projects" / "DemoProject" / "production" / "spec.md"
    production.parent.mkdir(parents=True)
    production.write_text("DEMO-PROMOTION-MUST-STAY-OUT\n", encoding="utf-8")

    receipt = sync_committed(
        {
            "agentlab_root": root,
            "project": "DemoProject",
            "status": "promoted",
            "promoted_paths": ["projects/DemoProject/production/spec.md"],
        }
    )

    assert receipt.status == "REJECTED"
    assert receipt.index_snapshot is None
    assert receipt.warnings == (
        "project DemoProject is excluded by knowledge indexing.project_allowlist",
    )
    assert knowledge_status(root)["spaces"] == []


def test_sync_committed_indexes_only_governed_project_truth(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    production = root / "projects" / "Alpha" / "production" / "spec.md"
    production.parent.mkdir(parents=True)
    production.write_text("PROMOTED-INDIGO-EVIDENCE\n", encoding="utf-8")
    unselected = root / "projects" / "Alpha" / "production" / "unselected.md"
    unselected.write_text("FORGED-PASS-MUST-NOT-PROMOTE\n", encoding="utf-8")
    _write_current_artifacts(root, "Alpha", "production/spec.md")
    candidate = root / "projects" / "Alpha" / "runs" / "task_040" / "artifacts" / "draft.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("CANDIDATE-INDIGO-EVIDENCE\n", encoding="utf-8")

    rejected = sync_committed(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "status": "promoted",
            "promoted_paths": ["projects/Alpha/runs/task_040/artifacts/draft.md"],
        }
    )
    forged = sync_committed(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "status": "pass",
            "promoted_paths": ["projects/Alpha/production/unselected.md"],
        }
    )
    synced = sync_committed(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "status": "promoted",
            "promoted_paths": ["projects/Alpha/production/spec.md"],
        }
    )
    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="Alpha",
            task_id="task_041",
            request_text="PROMOTED-INDIGO-EVIDENCE",
            domain="general_production",
        )
    )

    assert rejected.status == "REJECTED"
    assert forged.status == "REJECTED"
    assert "not selected by current project truth" in forged.warnings[0]
    assert synced.status == "SYNCED"
    assert synced.namespaces == ("project.Alpha", "domain.code_engineering")
    assert synced.indexed_paths == ("projects/Alpha/production/spec.md",)
    assert prepared.status == "READY"
    assert {item.source.path for item in prepared.evidence_bundle.items} == {
        "projects/Alpha/production/spec.md"
    }


def test_sole_blueprint_entrypoint_expands_only_hash_verified_components(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    project = root / "projects" / "Alpha"
    policy = project / "production" / "canonical" / "policy.yml"
    policy.parent.mkdir(parents=True)
    policy.write_text("status: active\nmarker: VERIFIED-POLICY\n", encoding="utf-8")
    scale = project / "production" / "series_scale_decision.yml"
    scale.write_text("planned_total_chapters: 1980\n", encoding="utf-8")
    length = project / "production" / "chapter_length_policy.yml"
    length.write_text("target: 5200\n", encoding="utf-8")
    cards = project / "production" / "chapter_cards"
    cards.mkdir()
    (cards / "ch001.yml").write_text("chapter: 1\n", encoding="utf-8")
    component_paths = (
        "production/series_scale_decision.yml",
        "production/chapter_length_policy.yml",
        "production/canonical",
        "production/chapter_cards",
    )
    authority = project / "production" / "blueprint_authority.yml"
    authority.write_text(
        yaml.safe_dump(
            {
                "schema_version": "crown-blueprint-authority/v1",
                "project": "Alpha",
                "status": "active",
                "sole_writer_entrypoint": True,
                "conflict_action": "fail_closed_before_context_compilation",
                "components": [
                    {
                        "path": relative,
                        "sha256": artifact_sha256(project / relative),
                    }
                    for relative in component_paths
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_current_artifacts(root, "Alpha", "production/blueprint_authority.yml")
    unrelated_brain = project / "project_brain" / "candidate_plan.yml"
    unrelated_brain.parent.mkdir()
    unrelated_brain.write_text("status: candidate\n", encoding="utf-8")

    built_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Alpha",
            domain="longform_narrative",
        )
    }

    assert "projects/Alpha/production/blueprint_authority.yml" in built_paths
    assert "projects/Alpha/production/canonical/policy.yml" in built_paths
    assert "projects/Alpha/project_brain/candidate_plan.yml" not in built_paths

    policy.write_text("status: active\nmarker: TAMPERED\n", encoding="utf-8")
    rebuilt_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Alpha",
            domain="longform_narrative",
        )
    }

    assert rebuilt_paths == set()


def test_project_specific_blueprint_indexes_hash_verified_registered_sources(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    project = root / "projects" / "Novel"
    bible = project / "production" / "bible"
    outlines = project / "production" / "outlines"
    manuscript = project / "production" / "manuscript"
    for directory, marker in (
        (bible, "VERIFIED-BIBLE"),
        (outlines, "VERIFIED-OUTLINE"),
        (manuscript, "VERIFIED-MANUSCRIPT"),
    ):
        directory.mkdir(parents=True)
        (directory / "current.md").write_text(marker + "\n", encoding="utf-8")
    authority = project / "production" / "blueprint_authority.yml"
    authority.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-authority/v1",
                "project": "Novel",
                "status": "registered_pending_generic_validation",
                "authority_kind": "project_specific",
                "source_artifacts": {
                    f"source_{name}": {
                        "artifact_id": name,
                        "version": "v1",
                        "path": f"production/{name}/",
                        "sha256": artifact_sha256(project / "production" / name),
                    }
                    for name in ("bible", "outlines", "manuscript")
                },
                "story_contract": {
                    "target_total_chapters": 100,
                    "accepted_chapters": 10,
                    "next_production_chapter": 11,
                },
                "authority_rules": {
                    "direct_production_edit_forbidden": True,
                    "one_current_version_per_artifact_id": True,
                },
                "production_gate": {"runtime_standard": "task-runtime-v2"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_current_artifacts(root, "Novel", "production/blueprint_authority.yml")
    unbound_fact_snapshot = project / "project_brain" / "project_fact_snapshot.yml"
    unbound_fact_snapshot.parent.mkdir()
    unbound_fact_snapshot.write_text(
        "fact: UNBOUND-GENERIC-MEMORY\n",
        encoding="utf-8",
    )

    built_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Novel",
            domain="longform_narrative",
        )
    }

    assert "projects/Novel/production/blueprint_authority.yml" in built_paths
    assert "projects/Novel/production/bible/current.md" in built_paths
    assert "projects/Novel/production/outlines/current.md" in built_paths
    assert "projects/Novel/production/manuscript/current.md" in built_paths
    assert "projects/Novel/project_brain/project_fact_snapshot.yml" not in built_paths

    unbound_fact_snapshot.write_text(
        "fact: CHANGED-UNBOUND-GENERIC-MEMORY\n",
        encoding="utf-8",
    )
    unchanged_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Novel",
            domain="longform_narrative",
        )
    }
    assert unchanged_paths == built_paths

    _write_current_artifacts(
        root,
        "Novel",
        "production/blueprint_authority.yml",
        "project_brain/project_fact_snapshot.yml",
    )
    bound_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Novel",
            domain="longform_narrative",
        )
    }
    assert "projects/Novel/project_brain/project_fact_snapshot.yml" in bound_paths

    (bible / "current.md").write_text("TAMPERED\n", encoding="utf-8")
    rebuilt_paths = {
        item.source.path
        for item in SourceCollector(root).collect_project(
            "Novel",
            domain="longform_narrative",
        )
    }

    assert rebuilt_paths == set()


def test_sync_failure_marks_index_stale_without_touching_committed_truth(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    production = root / "projects" / "Alpha" / "production" / "spec.md"
    production.parent.mkdir(parents=True)
    production.write_text("durable production truth\n", encoding="utf-8")
    _write_current_artifacts(root, "Alpha", "production/spec.md")
    broken_runtime = root / ".agentlab_runtime" / "knowledge"
    broken_runtime.parent.mkdir(parents=True)
    broken_runtime.write_text("not a directory", encoding="utf-8")

    receipt = sync_committed(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "status": "promoted",
            "promoted_paths": ["projects/Alpha/production/spec.md"],
        }
    )

    assert receipt.status == "INDEX_STALE"
    assert receipt.stale_namespaces == (
        "project.Alpha",
        "domain.code_engineering",
    )
    assert production.read_text(encoding="utf-8") == "durable production truth\n"
    assert any("truth was not rolled back" in warning for warning in receipt.warnings)


def test_sync_committed_preserves_authority_and_updates_domain_shard(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    canonical = root / "projects" / "Novel" / "project_brain" / "canon.md"
    accepted = root / "projects" / "Novel" / "production" / "chapter.md"
    canonical.parent.mkdir(parents=True)
    accepted.parent.mkdir(parents=True)
    canonical.write_text("CANON-VIOLET-EVIDENCE\n", encoding="utf-8")
    accepted.write_text("CHAPTER-VIOLET-EVIDENCE\n", encoding="utf-8")
    _write_current_artifacts(root, "Novel", "production/chapter.md")

    receipt = sync_committed(
        {
            "agentlab_root": root,
            "project": "Novel",
            "status": "promoted",
            "domain": "longform_narrative",
            "promoted_paths": [
                "projects/Novel/project_brain/canon.md",
                "projects/Novel/production/chapter.md",
            ],
        }
    )

    assert receipt.status == "SYNCED"
    assert receipt.namespaces == (
        "project.Novel",
        "domain.longform_narrative",
    )
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    project_hits = store.search(
        ("project.Novel",),
        "VIOLET-EVIDENCE",
        max_results=10,
        authorities=(AuthorityLevel.CANONICAL, AuthorityLevel.ACCEPTED),
        project_id="Novel",
    )
    domain_hits = store.search(
        ("domain.longform_narrative",),
        "VIOLET-EVIDENCE",
        max_results=10,
        authorities=(AuthorityLevel.CANONICAL, AuthorityLevel.ACCEPTED),
        project_id="Novel",
    )
    assert {hit.authority for hit in project_hits} == {
        AuthorityLevel.CANONICAL.value,
        AuthorityLevel.ACCEPTED.value,
    }
    assert {hit.source.path for hit in domain_hits} == {
        "projects/Novel/project_brain/canon.md",
        "projects/Novel/production/chapter.md",
    }


def test_sync_committed_retires_superseded_hash_for_same_source(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    canon = root / "projects" / "Novel" / "project_brain" / "canon.md"
    canon.parent.mkdir(parents=True)
    canon.write_text("OLD-CANON-OBSIDIAN-EVIDENCE\n", encoding="utf-8")
    receipt = {
        "agentlab_root": root,
        "project": "Novel",
        "status": "accepted",
        "domain": "longform_narrative",
        "committed_paths": ["projects/Novel/project_brain/canon.md"],
    }
    assert sync_committed(receipt).status == "SYNCED"

    canon.write_text("NEW-CANON-PEARL-EVIDENCE\n", encoding="utf-8")
    assert sync_committed(receipt).status == "SYNCED"

    old = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_old_canon",
            "OLD-CANON-OBSIDIAN-EVIDENCE",
            "longform_narrative",
        )
    )
    new = prepare_task(
        KnowledgeTaskRequest(
            root,
            "Novel",
            "task_new_canon",
            "NEW-CANON-PEARL-EVIDENCE",
            "longform_narrative",
        )
    )

    assert old.status == "INSUFFICIENT_EVIDENCE"
    assert old.evidence_bundle.items == ()
    assert new.status == "READY"
    assert {item.source.path for item in new.evidence_bundle.items} == {
        "projects/Novel/project_brain/canon.md"
    }


def test_prepare_task_skips_stale_spaces_instead_of_serving_old_evidence(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    canon = root / "projects" / "Novel" / "project_brain" / "canon.md"
    canon.parent.mkdir(parents=True)
    canon.write_text("STALE-INDEX-CERULEAN-EVIDENCE\n", encoding="utf-8")
    request = KnowledgeTaskRequest(
        root,
        "Novel",
        "task_stale_space",
        "STALE-INDEX-CERULEAN-EVIDENCE",
        "longform_narrative",
    )
    assert prepare_task(request).status == "READY"
    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    store.mark_stale("project.Novel")
    store.mark_stale("domain.longform_narrative")

    prepared = prepare_task(request)

    assert prepared.status == "INSUFFICIENT_EVIDENCE"
    assert prepared.evidence_bundle.items == ()
    assert any("stale knowledge spaces skipped" in warning for warning in prepared.warnings)


def test_sync_committed_rejects_missing_governed_path(tmp_path: Path) -> None:
    _write_config(tmp_path)

    receipt = sync_committed(
        {
            "agentlab_root": tmp_path,
            "project": "Alpha",
            "status": "promoted",
            "promoted_paths": ["projects/Alpha/production/missing.md"],
        }
    )

    assert receipt.status == "REJECTED"
    assert "missing" in receipt.warnings[0]


def test_incremental_domain_membership_is_retired_after_reclassification(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    path = root / "projects" / "Alpha" / "production" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text("RECLASSIFY-ORANGE-EVIDENCE\n", encoding="utf-8")
    _write_current_artifacts(root, "Alpha", "production/spec.md")
    synced = sync_committed(
        {
            "agentlab_root": root,
            "project": "Alpha",
            "status": "promoted",
            "domain": "code_engineering",
            "promoted_paths": ["projects/Alpha/production/spec.md"],
        }
    )
    assert synced.status == "SYNCED"

    build_knowledge_base(
        root,
        projects=("Alpha",),
        project_domains={"Alpha": "research"},
    )

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    old_hits = store.search(
        ("domain.code_engineering",),
        "RECLASSIFY-ORANGE-EVIDENCE",
        max_results=10,
        project_id="Alpha",
    )
    new_hits = store.search(
        ("domain.research",),
        "RECLASSIFY-ORANGE-EVIDENCE",
        max_results=10,
        project_id="Alpha",
    )
    assert old_hits == []
    assert {hit.source.path for hit in new_hits} == {
        "projects/Alpha/production/spec.md"
    }


def test_full_build_retires_bootstrapped_project_records_deleted_from_truth(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    path = root / "projects" / "Alpha" / "project_brain" / "obsolete.md"
    path.parent.mkdir(parents=True)
    path.write_text("OBSOLETE-AZURE-EVIDENCE\n", encoding="utf-8")
    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="Alpha",
            task_id="task_bootstrap_obsolete",
            request_text="OBSOLETE-AZURE-EVIDENCE",
            domain="code_engineering",
        )
    )
    assert prepared.status == "READY"

    path.unlink()
    build_knowledge_base(root, projects=("Alpha",))

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    assert store.search(
        ("project.Alpha",),
        "OBSOLETE-AZURE-EVIDENCE",
        max_results=10,
    ) == []


def test_full_build_indexes_only_hash_and_lineage_bound_current_narrative_edition(
    tmp_path: Path,
) -> None:
    root = tmp_path
    _write_config(root)
    project = root / "projects" / "Novel"
    old = project / "release_objects" / "editions" / "edition-001" / "chapter_001.md"
    current = project / "release_objects" / "editions" / "edition-002" / "chapter_001.md"
    old.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    old.write_text("HISTORICAL-SCARLET-EDITION\n", encoding="utf-8")
    current.write_text("CURRENT-SCARLET-EDITION\n", encoding="utf-8")
    undeclared = current.parent / "chapter_999.md"
    undeclared.write_text("UNDECLARED-SCARLET-EDITION\n", encoding="utf-8")
    (project / "project_artifact_index.yml").write_text(
        yaml.safe_dump(
            {
                "current_release": {
                    "edition_id": "edition-002",
                    "release_slot": "main",
                    "candidate_set_id": "candidate-002",
                    "candidate_set_sha256": "a" * 64,
                    "chapter_ids": [1],
                    "promotion_receipt": (
                        "release_objects/editions/edition-002/promotion_receipt.yml"
                    ),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (current.parent / "promotion_receipt.yml").write_text(
        yaml.safe_dump(
            {
                "status": "promoted",
                "edition_id": "edition-002",
                "release_slot": "main",
                "candidate_set_id": "candidate-002",
                "candidate_set_sha256": "a" * 64,
                "chapters": [
                    {
                        "chapter_id": 1,
                        "artifact_path": (
                            "release_objects/editions/edition-002/chapter_001.md"
                        ),
                        "artifact_sha256": hashlib.sha256(current.read_bytes()).hexdigest(),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    build_knowledge_base(root, projects=("Novel",))

    store = KnowledgeStore(root, ".agentlab_runtime/knowledge", "auto")
    assert store.search(
        ("project.Novel",),
        "HISTORICAL-SCARLET-EDITION",
        max_results=10,
        project_id="Novel",
    ) == []
    current_hits = store.search(
        ("project.Novel",),
        "CURRENT-SCARLET-EDITION",
        max_results=10,
        project_id="Novel",
    )
    assert {hit.source.path for hit in current_hits} == {
        "projects/Novel/release_objects/editions/edition-002/chapter_001.md"
    }
    assert store.search(
        ("project.Novel",),
        "UNDECLARED-SCARLET-EDITION",
        max_results=10,
        project_id="Novel",
    ) == []

    receipt_path = current.parent / "promotion_receipt.yml"
    valid_receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    index_path = project / "project_artifact_index.yml"
    valid_index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    mismatch_cases = (
        ("receipt", "candidate_set_id", "candidate-other"),
        ("receipt", "candidate_set_sha256", "b" * 64),
        ("receipt", "release_slot", "preview"),
        ("index", "promotion_receipt", "release_objects/editions/other/receipt.yml"),
    )
    for target, field, value in mismatch_cases:
        receipt_data = dict(valid_receipt)
        index_data = yaml.safe_load(yaml.safe_dump(valid_index, sort_keys=False))
        if target == "receipt":
            receipt_data[field] = value
        else:
            index_data["current_release"][field] = value
        receipt_path.write_text(
            yaml.safe_dump(receipt_data, sort_keys=False),
            encoding="utf-8",
        )
        index_path.write_text(
            yaml.safe_dump(index_data, sort_keys=False),
            encoding="utf-8",
        )
        build_knowledge_base(root, projects=("Novel",))
        assert store.search(
            ("project.Novel",),
            "CURRENT-SCARLET-EDITION",
            max_results=10,
            project_id="Novel",
        ) == []

    receipt_path.write_text(
        yaml.safe_dump(valid_receipt, sort_keys=False),
        encoding="utf-8",
    )
    index_path.write_text(
        yaml.safe_dump(valid_index, sort_keys=False),
        encoding="utf-8",
    )
    current.write_text("TAMPERED-CURRENT-SCARLET-EDITION\n", encoding="utf-8")
    build_knowledge_base(root, projects=("Novel",))
    assert store.search(
        ("project.Novel",),
        "TAMPERED-CURRENT-SCARLET-EDITION",
        max_results=10,
        project_id="Novel",
    ) == []


def test_keyword_retrieval_has_explicit_bm25_degraded_mode(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root, keyword_backend="bm25")
    source = root / "agent_runtime" / "fallback.py"
    source.parent.mkdir(parents=True)
    source.write_text("DEGRADED-AMBER-EVIDENCE\n", encoding="utf-8")

    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_050",
            request_text="DEGRADED-AMBER-EVIDENCE",
            domain="code_engineering",
        )
    )

    assert prepared.status == "READY"
    assert prepared.evidence_bundle.trace.degraded is True
    keyword_step = next(
        step for step in prepared.evidence_bundle.trace.steps if step.get("stage") == "keyword"
    )
    assert keyword_step["backend"] == ["degraded_bm25"]

    _write_config(root, keyword_backend="auto")
    recovered = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_051",
            request_text="DEGRADED-AMBER-EVIDENCE",
            domain="code_engineering",
        )
    )
    assert recovered.status == "READY"
    recovered_step = next(
        step for step in recovered.evidence_bundle.trace.steps if step.get("stage") == "keyword"
    )
    assert recovered_step["backend"] == ["sqlite_fts5"]


def test_fts_failure_degrades_backend_without_marking_current_content_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path
    _write_config(root, refresh_on_prepare=False, bootstrap_missing_spaces=True)
    source = root / "projects" / "Novel" / "project_brain" / "facts.yml"
    source.parent.mkdir(parents=True)
    source.write_text("FTS-DEGRADE-SAFE-EVIDENCE\n", encoding="utf-8")

    def broken_fts(*_args: object, **_kwargs: object) -> list[object]:
        raise sqlite3.OperationalError("simulated FTS failure")

    monkeypatch.setattr(KnowledgeStore, "_search_fts", broken_fts)
    request = KnowledgeTaskRequest(
        root,
        "Novel",
        "task_fts_degrade",
        "FTS-DEGRADE-SAFE-EVIDENCE",
        "longform_narrative",
    )
    first = prepare_task(request)
    second = prepare_task(request)
    statuses = {item["status"] for item in knowledge_status(root)["spaces"]}

    assert first.status == "READY"
    assert second.status == "READY"
    assert statuses == {"active"}
    assert not any("stale knowledge spaces skipped" in item for item in second.warnings)


def test_legacy_jsonl_import_downgrades_hash_mismatches_to_stale_audit(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    source_root = root / "legacy_sources"
    source_root.mkdir()
    good = source_root / "good.md"
    bad = source_root / "bad.md"
    good.write_text("LEGACY-GREEN-EVIDENCE\n", encoding="utf-8")
    bad.write_text("current content\n", encoding="utf-8")
    documents = [
        Document.from_file(
            rel_path="legacy_sources/good.md",
            text="LEGACY-GREEN-EVIDENCE\n",
            source_category=SourceCategory.DOCS,
            size_bytes=good.stat().st_size,
        ),
        Document.from_file(
            rel_path="legacy_sources/bad.md",
            text="LEGACY-STALE-EVIDENCE\n",
            source_category=SourceCategory.DOCS,
            size_bytes=len("LEGACY-STALE-EVIDENCE\n"),
        ),
    ]
    index = root / ".agentlab_runtime" / "legacy" / "index.jsonl"
    save_index(documents, index)

    receipt = import_legacy_jsonl(root, index, namespace="system.agentlab")
    good_result = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_060",
            request_text="LEGACY-GREEN-EVIDENCE",
            domain="research",
        )
    )
    stale_result = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=root,
            project="AgentLab",
            task_id="task_061",
            request_text="LEGACY-STALE-EVIDENCE",
            domain="research",
        )
    )

    assert receipt["active_count"] == 1
    assert receipt["stale_count"] == 1
    assert receipt["audit_count"] == 2
    assert good_result.status == "INSUFFICIENT_EVIDENCE"
    assert good_result.evidence_bundle.items == ()
    assert stale_result.status == "INSUFFICIENT_EVIDENCE"

    with pytest.raises(ValueError, match="legacy import cannot assign eligible authority"):
        import_legacy_jsonl(
            root,
            index,
            namespace="system.agentlab",
            authority=AuthorityLevel.ACCEPTED,
        )


def test_domain_profiles_generalize_code_narrative_research_and_media_metadata(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    code = root / "agent_runtime" / "domain_code.py"
    code.parent.mkdir(parents=True)
    code.write_text("CODE-VIOLET-EVIDENCE\n", encoding="utf-8")
    narrative = root / "projects" / "Novel" / "production" / "chapter.md"
    narrative.parent.mkdir(parents=True)
    narrative.write_text("NARRATIVE-SILVER-EVIDENCE\n", encoding="utf-8")
    research = root / "projects" / "Study" / "project_brain" / "citations.yml"
    research.parent.mkdir(parents=True)
    research.write_text("citation: RESEARCH-COPPER-EVIDENCE\n", encoding="utf-8")
    media = root / "projects" / "Film" / "production" / "hero.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"\x89PNG\r\n\x1a\nRAW-PIXELS-MUST-NOT-BE-INDEXED")
    for project, production_path in (
        ("Novel", "production/chapter.md"),
        ("Film", "production/hero.png"),
    ):
        _write_current_artifacts(root, project, production_path)

    code_context = prepare_task(
        KnowledgeTaskRequest(root, "AgentLab", "task_070", "CODE-VIOLET-EVIDENCE", "code_engineering")
    )
    narrative_context = prepare_task(
        KnowledgeTaskRequest(root, "Novel", "task_071", "NARRATIVE-SILVER-EVIDENCE chapter", "longform_narrative")
    )
    research_context = prepare_task(
        KnowledgeTaskRequest(root, "Study", "task_072", "RESEARCH-COPPER-EVIDENCE citation", "research")
    )
    media_context = prepare_task(
        KnowledgeTaskRequest(root, "Film", "task_073", "hero.png image", "media_production")
    )

    code_item = code_context.evidence_bundle.items[0]
    narrative_item = narrative_context.evidence_bundle.items[0]
    research_item = research_context.evidence_bundle.items[0]
    media_item = media_context.evidence_bundle.items[0]
    assert code_item.modality == "code"
    assert narrative_item.object_kind == "longform_narrative"
    assert narrative_item.modality == "text"
    assert research_item.object_kind == "research"
    assert research_item.modality == "structured"
    assert media_item.object_kind == "media_asset"
    assert media_item.modality == "image"
    assert media_item.metadata["raw_payload_indexed"] is False
    assert "RAW-PIXELS" not in media_item.excerpt
