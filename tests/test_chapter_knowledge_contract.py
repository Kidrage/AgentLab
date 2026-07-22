from pathlib import Path
import hashlib

import yaml
import pytest

from agent_runtime.narrative.knowledge_contract import ChapterKnowledgeContractError
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
