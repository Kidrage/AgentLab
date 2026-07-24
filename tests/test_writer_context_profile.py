from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent_runtime"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _plan(root: Path) -> SimpleNamespace:
    project_root = root / "projects" / "Crown_of_Ash"
    run_dir = project_root / "runs" / "task_ch002"
    return SimpleNamespace(
        project_root=project_root,
        run_dir=run_dir,
        user_request_path=run_dir / "user_request.md",
        skills={"selected": []},
    )


def _prepare_context(root: Path, *, profile: str | None) -> SimpleNamespace:
    plan = _plan(root)
    project_root = Path(plan.project_root)
    run_dir = Path(plan.run_dir)
    _write(
        root / "config" / "agent_registry.yml",
        "agents:\n  Writer:\n    template_path: agent_templates/writer.md\n",
    )
    _write(root / "agent_templates" / "writer.md", "# Writer\n")
    _write(Path(plan.user_request_path), "write chapter two\n")
    _write(run_dir / "mission_contract.yml", "task_domain: creative_writing\n")
    _write(project_root / "project_brain" / "project_fact_snapshot.yml", "large: snapshot\n")
    _write(project_root / "project_artifact_index.yml", "large: artifact_index\n")
    _write(project_root / "production" / "chapter_cards" / "index.yml", "large: all_cards\n")
    _write(project_root / "production" / "chapter_cards" / "ch002.yml", "chapter: 2\n")
    _write(project_root / "production" / "canonical" / "characters.yml", "characters: []\n")
    _write(project_root / "production" / "canonical" / "magic_rules.yml", "rules: []\n")
    _write(run_dir / "candidate_fact_ledger.yml", "events: []\n")
    previous = project_root / "runs" / "task_ch001"
    _write(previous / "fiction_draft.md", "previous prose\n")
    _write(previous / "continuity_ledger.yml", "chapter: 1\n")

    packet = {
        "must_read": [
            "project_brain/project_fact_snapshot.yml",
            "project_artifact_index.yml",
            "production/chapter_cards/index.yml",
            "production/chapter_cards/ch002.yml",
            "production/canonical/characters.yml",
            "production/canonical/magic_rules.yml",
            "runs/task_ch002/candidate_fact_ledger.yml",
            "runs/task_ch001/fiction_draft.md",
            "runs/task_ch001/continuity_ledger.yml",
        ],
        "knowledge_contract": {
            "evidence_groups": {
                "chapter_card": ["production/chapter_cards/ch002.yml"],
                "character_state": ["production/canonical/characters.yml"],
                "timeline_world_rules": ["production/canonical/magic_rules.yml"],
                "prior_continuity": [
                    "runs/task_ch001/fiction_draft.md",
                    "runs/task_ch001/continuity_ledger.yml",
                ],
            }
        },
        "story_authority": {
            "candidate_fact_ledger": "runs/task_ch002/candidate_fact_ledger.yml",
        },
        "previous_candidate_sources": [
            "runs/task_ch001/fiction_draft.md",
            "runs/task_ch001/continuity_ledger.yml",
        ],
    }
    if profile is not None:
        packet["writer_context_profile"] = profile
    _write(
        run_dir / "chapter_packet.yml",
        yaml.safe_dump(packet, sort_keys=False),
    )
    return plan


def test_compact_writer_context_keeps_relevant_sources_without_full_snapshots(
    tmp_path: Path,
) -> None:
    from agent_runner import writer_context_source_files

    plan = _prepare_context(tmp_path, profile="chapter_relevance_v1")
    files = writer_context_source_files(
        tmp_path,
        plan,
        Path(plan.run_dir) / "writer_role_session_capture.md",
    )
    relative = {path.relative_to(tmp_path).as_posix() for path in files}

    assert "config/agent_registry.yml" not in relative
    assert (
        "projects/Crown_of_Ash/project_brain/project_fact_snapshot.yml"
        not in relative
    )
    assert "projects/Crown_of_Ash/project_artifact_index.yml" not in relative
    assert "projects/Crown_of_Ash/production/chapter_cards/index.yml" not in relative
    assert "projects/Crown_of_Ash/production/chapter_cards/ch002.yml" in relative
    assert "projects/Crown_of_Ash/production/canonical/characters.yml" in relative
    assert "projects/Crown_of_Ash/production/canonical/magic_rules.yml" in relative
    assert "projects/Crown_of_Ash/runs/task_ch002/candidate_fact_ledger.yml" in relative
    assert "projects/Crown_of_Ash/runs/task_ch001/fiction_draft.md" in relative
    assert "agent_templates/writer.md" in relative


def test_unspecified_writer_context_profile_preserves_legacy_full_context(
    tmp_path: Path,
) -> None:
    from agent_runner import writer_context_source_files

    plan = _prepare_context(tmp_path, profile=None)
    files = writer_context_source_files(
        tmp_path,
        plan,
        Path(plan.run_dir) / "writer_role_session_capture.md",
    )
    relative = {path.relative_to(tmp_path).as_posix() for path in files}

    assert "config/agent_registry.yml" in relative
    assert "projects/Crown_of_Ash/project_brain/project_fact_snapshot.yml" in relative
    assert "projects/Crown_of_Ash/production/chapter_cards/index.yml" in relative


def test_strict_v3_reset_keeps_declared_fact_snapshot_authority(
    tmp_path: Path,
) -> None:
    from agent_runner import writer_context_source_files

    plan = _prepare_context(tmp_path, profile="chapter_relevance_v1")
    packet_path = Path(plan.run_dir) / "chapter_packet.yml"
    packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
    packet["knowledge_contract"]["evidence_groups"]["prior_continuity"] = [
        "project_brain/project_fact_snapshot.yml"
    ]
    packet["story_authority"][
        "authority_mode"
    ] = "strict_v3_chapter_knowledge_contract"
    packet["previous_candidate_sources"] = []
    _write(packet_path, yaml.safe_dump(packet, sort_keys=False))

    files = writer_context_source_files(
        tmp_path,
        plan,
        Path(plan.run_dir) / "writer_role_session_capture.md",
    )
    relative = {path.relative_to(tmp_path).as_posix() for path in files}

    assert "projects/Crown_of_Ash/project_brain/project_fact_snapshot.yml" in relative
    assert "projects/Crown_of_Ash/production/chapter_cards/ch002.yml" in relative
    assert "projects/Crown_of_Ash/production/canonical/characters.yml" in relative
