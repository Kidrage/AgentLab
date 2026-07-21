from pathlib import Path
import hashlib
from unittest.mock import patch

import yaml

from agent_runtime.background_job_controller import (
    consume_process_receipt,
    create_crown_delivery_job,
    schedule_next_attempt,
    write_process_receipt,
)
from agent_runtime.background_job_worker import _continuous_audit_manifest, execute_action


def _complete(
    root: Path,
    attempt: dict,
    *,
    result: dict | None = None,
) -> dict:
    write_process_receipt(
        root,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        attempt_id=attempt["attempt_id"],
        idempotency_key=attempt["idempotency_key"],
        lease_token=attempt["lease_token"],
        outcome="success",
        exit_code=0,
        result=result or {"status": "pass"},
        now="2026-07-21T16:00:30Z",
    )
    return consume_process_receipt(
        root,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        now="2026-07-21T16:00:31Z",
    )


def test_crown_reset_parent_job_persists_20_chapter_rag_cadence(tmp_path: Path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)

    state = create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        eval_id="crown-rag-reset-20260721",
        start_chapter=1,
        end_chapter=20,
        batch_size=5,
        continuity_checkpoint_cadence=5,
        heavy_audit_cadence=20,
        writer_worker="claude_code",
        chapter_state_plan="production/chapter_cards/index.yml",
        parent_task_id="task_crown_rag_reset_ch01_ch20",
        knowledge_contract_required=True,
    )

    assert state["parent_task_id"] == "task_crown_rag_reset_ch01_ch20"
    assert state["current_batch"] == {"number": 1, "start": 1, "end": 5}
    assert state["config"]["continuity_checkpoint_cadence"] == 5
    assert state["config"]["heavy_audit_cadence"] == 20
    assert state["config"]["knowledge_contract_required"] is True
    assert state["candidate_only"] is True
    assert state["production_allowed"] is False


def test_first_five_chapters_schedule_checkpoint_not_heavy_audit(tmp_path: Path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        eval_id="crown-rag-reset-20260721",
        start_chapter=1,
        end_chapter=20,
        batch_size=5,
        continuity_checkpoint_cadence=5,
        heavy_audit_cadence=20,
        writer_worker="claude_code",
        chapter_state_plan="production/chapter_cards/index.yml",
        parent_task_id="task_crown_rag_reset_ch01_ch20",
        knowledge_contract_required=True,
        now="2026-07-21T16:00:00Z",
    )
    preflight = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        now="2026-07-21T16:00:01Z",
    )
    assert preflight and preflight["action"] == "preflight"
    _complete(tmp_path, preflight)
    generation = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        now="2026-07-21T16:00:32Z",
    )
    assert generation and generation["action"] == "generate_batch"
    _complete(tmp_path, generation)
    deterministic = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        now="2026-07-21T16:00:33Z",
    )
    assert deterministic and deterministic["action"] == "deterministic_check"
    state = _complete(tmp_path, deterministic)

    assert state["status"] == "awaiting_continuity_checkpoint"
    checkpoint = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        now="2026-07-21T16:00:34Z",
    )
    assert checkpoint and checkpoint["action"] == "continuity_checkpoint"


def test_continuity_checkpoint_freezes_five_candidate_hashes_and_evidence_versions(
    tmp_path: Path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    expected_hashes: list[str] = []
    for chapter in range(1, 6):
        task_id = f"task_narrative_eval_ch{chapter:02d}_crown-rag-reset-20260721"
        run = project / "runs" / task_id
        run.mkdir(parents=True)
        prose = f"# 第{chapter}章 标题{chapter}\n\n正文{chapter}。\n"
        (run / "fiction_draft.md").write_text(prose, encoding="utf-8")
        expected_hashes.append(hashlib.sha256(prose.encode("utf-8")).hexdigest())
        (run / "chapter_packet.yml").write_text(
            yaml.safe_dump(
                {
                    "chapter": chapter,
                    "knowledge_contract": {
                        "status": "pass",
                        "evidence_version": f"evidence-{chapter}",
                    },
                }
            ),
            encoding="utf-8",
        )

    result = execute_action(
        {
            "action": "continuity_checkpoint",
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "crown-rag-reset-ch01-ch20",
            "candidate_only": True,
            "production_allowed": False,
            "batch": {"number": 1, "start": 1, "end": 5},
            "config": {"eval_id": "crown-rag-reset-20260721"},
        }
    )

    assert result["outcome"] == "success"
    snapshot_path = tmp_path / result["result"]["checkpoint_path"]
    snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    assert [item["fiction_draft_sha256"] for item in snapshot["chapters"]] == expected_hashes
    assert [item["knowledge_evidence_version"] for item in snapshot["chapters"]] == [
        f"evidence-{chapter}" for chapter in range(1, 6)
    ]
    assert snapshot["chapters"][0]["predecessor_sha256"] is None
    assert snapshot["chapters"][1]["predecessor_sha256"] == expected_hashes[0]


def test_generation_requires_chapter_knowledge_contract_for_reset_job(tmp_path: Path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    observed: dict = {}

    def fake_run(_root, _project, **kwargs):
        observed.update(kwargs)
        return {
            "status": "pass",
            "layers": {
                "L2_real_chapter_sample": {
                    "status": "pass",
                    "completed_chapter_count": 5,
                    "selected_chapter_count": 5,
                }
            },
        }

    request = {
        "action": "generate_batch",
        "agentlab_root": str(tmp_path),
        "project": "Crown_of_Ash",
        "job_id": "crown-rag-reset-ch01-ch20",
        "candidate_only": True,
        "production_allowed": False,
        "batch": {"number": 1, "start": 1, "end": 5},
        "config": {
            "narrative_adapter": "crown",
            "suite": "crown-rag-reset-v1",
            "eval_id": "crown-rag-reset-20260721",
            "writer_worker": "claude_code",
            "chapter_state_plan": "production/chapter_cards/index.yml",
            "writer_budget": "balanced",
            "knowledge_contract_required": True,
        },
    }

    with patch("agent_runtime.narrative_eval.run_narrative_eval", side_effect=fake_run):
        result = execute_action(request)

    assert result["outcome"] == "success"
    assert observed["require_knowledge_contract"] is True


def test_final_heavy_audit_request_covers_the_full_twenty_chapter_window(
    tmp_path: Path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
        eval_id="crown-rag-reset-20260721",
        start_chapter=1,
        end_chapter=20,
        batch_size=5,
        continuity_checkpoint_cadence=5,
        heavy_audit_cadence=20,
        writer_worker="claude_code",
        chapter_state_plan="production/chapter_cards/index.yml",
        parent_task_id="task_crown_rag_reset_ch01_ch20",
        knowledge_contract_required=True,
        now="2026-07-21T16:00:00Z",
    )

    for batch_number in range(1, 5):
        if batch_number == 1:
            preflight = schedule_next_attempt(
                tmp_path,
                project="Crown_of_Ash",
                job_id="crown-rag-reset-ch01-ch20",
            )
            assert preflight and preflight["action"] == "preflight"
            _complete(tmp_path, preflight)
        generation = schedule_next_attempt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="crown-rag-reset-ch01-ch20",
        )
        assert generation and generation["action"] == "generate_batch"
        _complete(tmp_path, generation)
        deterministic = schedule_next_attempt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="crown-rag-reset-ch01-ch20",
        )
        assert deterministic and deterministic["action"] == "deterministic_check"
        _complete(tmp_path, deterministic)
        if batch_number < 4:
            checkpoint = schedule_next_attempt(
                tmp_path,
                project="Crown_of_Ash",
                job_id="crown-rag-reset-ch01-ch20",
            )
            assert checkpoint and checkpoint["action"] == "continuity_checkpoint"
            _complete(tmp_path, checkpoint)

    heavy = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-rag-reset-ch01-ch20",
    )
    assert heavy and heavy["action"] == "heavy_audit"
    request = yaml.safe_load(Path(heavy["action_request_path"]).read_text(encoding="utf-8"))

    assert request["batch"]["start"] == 1
    assert request["batch"]["end"] == 20
    assert request["audit_window"]["audit_chapters"] == list(range(1, 21))
    assert [item["chapter_id"] for item in request["narrative_execution_plan"]["chapters"]] == list(
        range(1, 21)
    )


def test_heavy_audit_blocks_when_writer_knowledge_evidence_has_drifted(
    tmp_path: Path,
) -> None:
    project = tmp_path / "projects" / "Crown_of_Ash"
    source = project / "project_brain" / "facts.yml"
    source.parent.mkdir(parents=True)
    source.write_text("fact: changed\n", encoding="utf-8")
    task_id = "task_narrative_eval_ch01_crown-rag-reset-20260721"
    run = project / "runs" / task_id
    run.mkdir(parents=True)
    (run / "chapter_packet.yml").write_text(
        yaml.safe_dump(
            {
                "chapter": 1,
                "knowledge_contract": {
                    "status": "pass",
                    "namespace": "project.Crown_of_Ash",
                    "index_snapshot": "snapshot-1",
                    "evidence_version": "stale-version",
                    "evidence_groups": {
                        "chapter_card": ["project_brain/facts.yml"],
                        "character_state": ["project_brain/facts.yml"],
                        "timeline_world_rules": ["project_brain/facts.yml"],
                        "foreshadowing": ["project_brain/facts.yml"],
                        "prior_continuity": ["project_brain/facts.yml"],
                    },
                    "source_hashes": {
                        "project_brain/facts.yml": "0" * 64,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = execute_action(
        {
            "action": "heavy_audit",
            "attempt_id": "attempt-001-heavy-audit",
            "agentlab_root": str(tmp_path),
            "project": "Crown_of_Ash",
            "job_id": "crown-rag-reset-ch01-ch20",
            "candidate_only": True,
            "production_allowed": False,
            "batch": {"number": 4, "start": 1, "end": 1},
            "audit_window": {"audit_chapters": [1]},
            "config": {
                "narrative_adapter": "crown",
                "eval_id": "crown-rag-reset-20260721",
                "knowledge_contract_required": True,
            },
        }
    )

    assert result["outcome"] == "failed"
    assert result["result"]["reason"] == "knowledge_contract_drift"
    validation = result["result"]["knowledge_contract_validation"]
    assert validation["status"] == "blocked"
    assert any("source_hash_drift" in issue for issue in validation["issues"])


def test_continuous_audit_manifest_requires_one_passed_review_of_all_twenty_chapters() -> None:
    chapter_records = [
        {
            "chapter": chapter,
            "task_id": f"task-ch{chapter:02d}",
            "path": f"projects/Crown_of_Ash/runs/task-ch{chapter:02d}/fiction_draft.md",
            "sha256": f"{chapter:064x}",
        }
        for chapter in range(1, 21)
    ]
    request = {
        "project": "Crown_of_Ash",
        "job_id": "crown-rag-reset-ch01-ch20",
        "candidate_only": True,
        "config": {
            "start_chapter": 1,
            "end_chapter": 20,
            "knowledge_contract_required": True,
        },
        "prior_results": {
            "heavy_audit": {
                "task_id": "task-heavy-audit-01-20",
                "run_dir": "projects/Crown_of_Ash/runs/task-heavy-audit-01-20",
                "audit_chapters": list(range(1, 21)),
                "seal_decision": {"status": "pass", "allow_seal": True},
                "tiered_audit": {"status": "pass"},
                "knowledge_contract_validation": {
                    "status": "pass",
                    "chapters": [
                        {
                            "chapter": chapter,
                            "knowledge_evidence_version": f"evidence-{chapter}",
                        }
                        for chapter in range(1, 21)
                    ],
                },
            }
        },
    }

    manifest = _continuous_audit_manifest(request, chapter_records)

    assert manifest["status"] == "pass"
    assert manifest["continuous_review"] is True
    assert manifest["chapter_range"] == [1, 20]
    assert manifest["chapters"] == chapter_records
    assert manifest["knowledge_evidence_versions"]["20"] == "evidence-20"

    request["prior_results"]["heavy_audit"]["audit_chapters"] = list(range(16, 21))
    blocked = _continuous_audit_manifest(request, chapter_records)
    assert blocked["status"] == "blocked"
    assert "heavy_audit_did_not_cover_exact_chapter_range" in blocked["issues"]
