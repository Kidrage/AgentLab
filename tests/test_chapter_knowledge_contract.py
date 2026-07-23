from pathlib import Path
import hashlib

import yaml
import pytest

from agent_runtime.narrative.knowledge_contract import ChapterKnowledgeContractError
from agent_runtime.narrative.state_store import NarrativeStateStore
from agent_runtime.narrative_delivery import build_chapter_packet


def _write(project: Path, relative: str, content: str) -> str:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return relative


def test_required_chapter_knowledge_contract_is_grouped_and_hash_bound(
    tmp_path: Path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    character = _write(project, "production/characters/char-001.yml", "id: char-001\nage: 29\n")
    fact_authority = _write(
        project,
        "production/fact_authority.yml",
        "schema_version: narrative-fact-authority/v1\n"
        "project: Crown_of_Ash\n"
        "authority_id: crown-character-age-standard\n"
        "revision: 1\n"
        "status: active\n"
        "effective_at: '2026-07-23T00:00:00Z'\n"
        "supersedes_authority_sha256: null\n"
        "facts:\n"
        "- fact_id: char-001.age\n"
        "  target: characters\n"
        "  entity_id: char-001\n"
        "  field: age\n"
        "  value: 29\n",
    )
    fact_authority_sha256 = hashlib.sha256(
        (project / fact_authority).read_bytes()
    ).hexdigest()
    _write(
        project,
        "project_artifact_index.yml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "project": "Crown_of_Ash",
                "artifacts": [
                    {
                        "artifact_id": "crown_fact_authority_01",
                        "status": "current",
                        "production_path": fact_authority,
                        "production_sha256": fact_authority_sha256,
                        "authority_id": "crown-character-age-standard",
                        "authority_revision": 1,
                    }
                ],
                "current": {
                    "crown_fact_authority_01": fact_authority,
                },
            },
            sort_keys=False,
        ),
    )
    NarrativeStateStore(
        project / "project_brain",
        project="Crown_of_Ash",
    ).bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Crown_of_Ash",
            "precedence": ["single_active_fact_authority"],
            "sources": [
                {
                    "path": fact_authority,
                    "sha256": fact_authority_sha256,
                }
            ],
            "base_state": {
                "characters": {"char-001": {"age": 29}},
                "fact_authorities": {
                    "crown-character-age-standard": {
                        "revision": 1,
                        "source_path": fact_authority,
                        "source_sha256": fact_authority_sha256,
                    }
                },
            },
        }
    )
    timeline = _write(project, "production/timeline/timeline-001.yml", "id: timeline-001\nday: 1\n")
    foreshadowing = _write(project, "production/foreshadowing/seed-001.yml", "id: seed-001\nstatus: planted\n")
    _write(project, "project_brain/project_fact_snapshot.yml", "schema_version: 1\nfacts: []\n")
    card_path = project / "production" / "chapter_cards" / "ch001.yml"
    card_path.parent.mkdir(parents=True)
    card_path.write_text(
        yaml.safe_dump(
            {
                "id": "chapter-card-001",
                "chapter": 1,
                "knowledge_requirements": {
                    "character_state": [character],
                    "timeline_world_rules": [timeline],
                    "foreshadowing": [foreshadowing],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    indexed = [
        "production/chapter_cards/ch001.yml",
        character,
        fact_authority,
        timeline,
        foreshadowing,
        "project_brain/project_fact_snapshot.yml",
    ]
    _write(
        project,
        "project_brain/knowledge_index_snapshot.yml",
        yaml.safe_dump(
            {
                "namespace": "project.Crown_of_Ash",
                "index_snapshot": "crown-snapshot-001",
                "formal_fact_roots": ["production", "project_brain"],
                "indexed_paths": [f"projects/Crown_of_Ash/{item}" for item in indexed],
                "indexed_source_hashes": {
                    f"projects/Crown_of_Ash/{item}": hashlib.sha256(
                        (project / item).read_bytes()
                    ).hexdigest()
                    for item in indexed
                },
            },
            sort_keys=False,
        ),
    )

    packet = build_chapter_packet(
        tmp_path,
        "Crown_of_Ash",
        "task-ch01",
        1,
        baseline_mode="reset",
        require_knowledge_contract=True,
    )

    contract = packet["knowledge_contract"]
    assert contract["status"] == "pass"
    assert contract["namespace"] == "project.Crown_of_Ash"
    assert contract["allowed_canonical_roots"] == ["production", "project_brain"]
    assert contract["missing_groups"] == []
    assert set(contract["evidence_groups"]) == {
        "chapter_card",
        "character_state",
        "timeline_world_rules",
        "foreshadowing",
        "prior_continuity",
    }
    assert contract["evidence_groups"]["chapter_card"] == [
        "production/chapter_cards/ch001.yml"
    ]
    assert contract["evidence_groups"]["character_state"] == [
        character,
        fact_authority,
    ]
    assert contract["evidence_groups"]["prior_continuity"] == [
        "project_brain/project_fact_snapshot.yml"
    ]
    assert contract["index_snapshot"] == "crown-snapshot-001"
    expected_hash = hashlib.sha256((project / character).read_bytes()).hexdigest()
    assert contract["source_hashes"][character] == expected_hash
    assert packet["source_of_truth"]["knowledge_index_snapshot"] == (
        "project_brain/knowledge_index_snapshot.yml"
    )
    assert set(contract["source_hashes"]).issubset(set(packet["must_read"]))
    assert packet["knowledge_contract"]["forbidden_roots"] == [
        "acceptance_runs",
        "agent_docs",
        "archive",
        "background_jobs",
        "candidates",
        "runs",
    ]

    original_authority = (project / fact_authority).read_text(encoding="utf-8")
    original_index = (project / "project_artifact_index.yml").read_text(
        encoding="utf-8"
    )
    (project / fact_authority).write_text(
        original_authority.replace("value: 29", "value: 30"),
        encoding="utf-8",
    )
    tampered_index = yaml.safe_load(original_index)
    tampered_index["artifacts"][0]["production_sha256"] = hashlib.sha256(
        (project / fact_authority).read_bytes()
    ).hexdigest()
    (project / "project_artifact_index.yml").write_text(
        yaml.safe_dump(tampered_index, sort_keys=False),
        encoding="utf-8",
    )
    (project / character).write_text("id: char-001\nage: 30\n", encoding="utf-8")
    with pytest.raises(
        ChapterKnowledgeContractError,
        match="event ledger binding mismatch",
    ):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01-coordinated-tamper",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )

    (project / fact_authority).write_text(original_authority, encoding="utf-8")
    (project / "project_artifact_index.yml").write_text(
        original_index,
        encoding="utf-8",
    )
    (project / character).write_text("id: char-001\nage: 30\n", encoding="utf-8")
    with pytest.raises(
        ChapterKnowledgeContractError,
        match="fact authority projection mismatch",
    ):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01-conflict",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )

    (project / character).write_text("id: char-001\nage: 29\n", encoding="utf-8")
    _write(
        project,
        "project_brain/project_state_contract.yml",
        "active_fact_authority:\n"
        "  path: production/fact_authority.yml\n"
        "  authority_id: crown-character-age-standard\n"
        "  revision: 1\n"
        f"  sha256: {fact_authority_sha256}\n",
    )
    (project / fact_authority).unlink()
    with pytest.raises(
        ChapterKnowledgeContractError,
        match="missing declared active fact authority",
    ):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01-missing-authority",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )

    (project / "project_brain/project_state_contract.yml").unlink()
    _write(
        project,
        "project_brain/narrative_governance_v3.yml",
        "schema_version: crown-narrative-governance/v3\n"
        "authority:\n"
        "  event_log_is_authoritative: true\n",
    )
    with pytest.raises(
        ChapterKnowledgeContractError,
        match="missing active fact authority",
    ):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01-missing-opted-in-authority",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )


def test_required_contract_blocks_a_canonical_source_missing_from_project_rag(
    tmp_path: Path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    character = _write(project, "production/characters/char-001.yml", "id: char-001\nage: 29\n")
    timeline = _write(project, "production/timeline/timeline-001.yml", "id: timeline-001\n")
    foreshadowing = _write(project, "production/foreshadowing/seed-001.yml", "id: seed-001\n")
    fact = _write(project, "project_brain/project_fact_snapshot.yml", "schema_version: 1\n")
    card = _write(
        project,
        "production/chapter_cards/ch001.yml",
        yaml.safe_dump(
            {
                "chapter": 1,
                "knowledge_requirements": {
                    "character_state": [character],
                    "timeline_world_rules": [timeline],
                    "foreshadowing": [foreshadowing],
                },
            }
        ),
    )
    indexed = [timeline, foreshadowing, fact, card]
    _write(
        project,
        "project_brain/knowledge_index_snapshot.yml",
        yaml.safe_dump(
            {
                "namespace": "project.Crown_of_Ash",
                "index_snapshot": "snapshot-missing-character",
                "formal_fact_roots": ["production", "project_brain"],
                "indexed_paths": [f"projects/Crown_of_Ash/{item}" for item in indexed],
                "indexed_source_hashes": {
                    f"projects/Crown_of_Ash/{item}": hashlib.sha256(
                        (project / item).read_bytes()
                    ).hexdigest()
                    for item in indexed
                },
            }
        ),
    )

    with pytest.raises(ChapterKnowledgeContractError, match="not present in project RAG"):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )


def test_required_chapter_knowledge_contract_blocks_missing_group(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    _write(project, "project_brain/project_fact_snapshot.yml", "schema_version: 1\nfacts: []\n")
    _write(
        project,
        "project_brain/knowledge_index_snapshot.yml",
        "namespace: project.Crown_of_Ash\nindex_snapshot: crown-snapshot-001\n",
    )
    _write(
        project,
        "production/chapter_cards/ch001.yml",
        yaml.safe_dump(
            {
                "chapter": 1,
                "knowledge_requirements": {
                    "character_state": ["production/characters/missing.yml"],
                    "timeline_world_rules": ["production/timeline/missing.yml"],
                    "foreshadowing": ["production/foreshadowing/missing.yml"],
                },
            }
        ),
    )

    with pytest.raises(ChapterKnowledgeContractError, match="missing chapter evidence"):
        build_chapter_packet(
            tmp_path,
            "Crown_of_Ash",
            "task-ch01",
            1,
            baseline_mode="reset",
            require_knowledge_contract=True,
        )
