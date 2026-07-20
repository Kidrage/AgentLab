from __future__ import annotations

from pathlib import Path
import hashlib

import pytest
import yaml

from agent_runtime.knowledge_system import (
    AuthorityLevel,
    KnowledgeRecord,
    KnowledgeTaskRequest,
    Modality,
    SourceRef,
    evaluate_outcome,
    import_legacy_jsonl,
    prepare_task,
    sync_committed,
)
from agent_runtime.local_search.document import Document, SourceCategory
from agent_runtime.local_search.storage import save_index
from agent_runtime.knowledge_system.storage import KnowledgeStore


def _write_config(
    root: Path,
    *,
    mode: str = "assist",
    required_channels: list[str] | None = None,
    keyword_backend: str = "auto",
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
                "retrieval": {
                    "top_k": 6,
                    "required_channels": required_channels or ["keyword"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


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


def test_sync_committed_indexes_only_governed_project_truth(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    production = root / "projects" / "Alpha" / "production" / "spec.md"
    production.parent.mkdir(parents=True)
    production.write_text("PROMOTED-INDIGO-EVIDENCE\n", encoding="utf-8")
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
    assert synced.status == "SYNCED"
    assert synced.indexed_paths == ("projects/Alpha/production/spec.md",)
    assert prepared.status == "READY"
    assert {item.source.path for item in prepared.evidence_bundle.items} == {
        "projects/Alpha/production/spec.md"
    }


def test_sync_failure_marks_index_stale_without_touching_committed_truth(tmp_path: Path) -> None:
    root = tmp_path
    _write_config(root)
    production = root / "projects" / "Alpha" / "production" / "spec.md"
    production.parent.mkdir(parents=True)
    production.write_text("durable production truth\n", encoding="utf-8")
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
    assert receipt.stale_namespaces == ("project.Alpha",)
    assert production.read_text(encoding="utf-8") == "durable production truth\n"
    assert any("truth was not rolled back" in warning for warning in receipt.warnings)


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
    assert receipt["audit_count"] == 1
    assert good_result.status == "READY"
    assert good_result.evidence_bundle.items[0].source.kind == "legacy_jsonl"
    assert stale_result.status == "INSUFFICIENT_EVIDENCE"


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
