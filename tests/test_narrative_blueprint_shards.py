import hashlib
from pathlib import Path

import pytest
import yaml

from agent_runtime.narrative.blueprint_shards import (
    assemble_blueprint_shards,
    build_blueprint_shard_plan,
    find_reusable_blueprint_shard_attempt,
    run_blueprint_shard_workflow,
    validate_blueprint_shard_semantics,
    validate_blueprint_shard,
)
from agent_runtime.task_runtime_v2 import TaskRuntime


def test_expired_external_request_cannot_prepare_or_mutate_a_cold_task(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="ColdBlueprint")
    runtime.create_task(
        task_id="task-cold-blueprint",
        title="Cold blueprint",
        user_goal="Do not prepare with an expired outbound request.",
        protocol_ref="narrative.blueprint.v1",
        input_profile={
            "kind": "blueprint_build",
            "scope": "longform",
            "target_count": 600,
            "canon_impact": "new_project",
            "risk_flags": [],
            "project": "ColdBlueprint",
            "source_creative_brief": "inputs/brief.yml",
            "source_creative_brief_sha256": "a" * 64,
        },
        idempotency_key="create-cold-blueprint",
    )
    task_root = runtime._task_dir("task-cold-blueprint")
    request_path = task_root / "inputs" / "external-request.yml"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(
        yaml.safe_dump(
            {
                "purpose": "Expired request.",
                "minimal_fragment": "Do not transmit.",
                "expires_at": "2000-01-01T00:00:00Z",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger_path = task_root / "events.jsonl"
    before = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="external context request is expired"):
        run_blueprint_shard_workflow(
            tmp_path,
            project="ColdBlueprint",
            task_id="task-cold-blueprint",
            total_chapters=600,
            volume_count=15,
            blueprint_title="Fixture",
            writer_work_item_id="writer",
            story_artifact_type="story_blueprint",
            candidate_gate_id="candidate_hash_bound",
            context_artifact_types=["blueprint_direction"],
            required_fields=["objective"],
            writer_instruction_path=task_root / "inputs" / "missing.md",
            external_context_request_path=request_path,
        )

    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == before
    assert runtime.load_task("task-cold-blueprint")["task"].get(
        "compiled_protocol"
    ) is None

    sensitive_root = task_root / "inputs" / ".env-private"
    sensitive_root.mkdir()
    sensitive_request = sensitive_root / "request.yml"
    sensitive_request.write_text(
        yaml.safe_dump(
            {
                "purpose": "Hidden request.",
                "minimal_fragment": "Do not transmit.",
                "expires_at": "2999-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    alias = task_root / "inputs" / "alias"
    alias.symlink_to(sensitive_root, target_is_directory=True)
    with pytest.raises(ValueError, match="external context request path is forbidden"):
        run_blueprint_shard_workflow(
            tmp_path,
            project="ColdBlueprint",
            task_id="task-cold-blueprint",
            total_chapters=600,
            volume_count=15,
            blueprint_title="Fixture",
            writer_work_item_id="writer",
            story_artifact_type="story_blueprint",
            candidate_gate_id="candidate_hash_bound",
            context_artifact_types=["blueprint_direction"],
            required_fields=["objective"],
            writer_instruction_path=task_root / "inputs" / "missing.md",
            external_context_request_path=alias / "request.yml",
        )
    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == before


def test_blueprint_shard_plan_covers_600_chapters_as_15_volumes_of_40() -> None:
    plan = build_blueprint_shard_plan(total_chapters=600, volume_count=15)

    assert len(plan) == 15
    assert [(item.start_chapter, item.end_chapter) for item in plan] == [
        (start, start + 39) for start in range(1, 601, 40)
    ]
    assert [item.volume_id for item in plan] == [
        f"V{volume:02d}" for volume in range(1, 16)
    ]
    assert [chapter for item in plan for chapter in item.chapters] == list(
        range(1, 601)
    )


def _render_shard(start: int, end: int) -> str:
    cards = []
    for chapter in range(start, end + 1):
        cards.append(
            "\n".join(
                [
                    f"## C{chapter:03d} 章名",
                    "- objective: 目标",
                    "- conflict: 冲突",
                    "- turn: 转折",
                    "- consequence: 后果",
                    "- promise: 伏笔",
                ]
            )
        )
    return "\n\n".join(cards) + "\n"


def test_shard_validation_requires_every_card_and_field() -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[0]
    valid = _render_shard(1, 40)

    assert validate_blueprint_shard(shard, valid) == ()
    assert "missing chapters: C040" in validate_blueprint_shard(
        shard, _render_shard(1, 39)
    )
    assert "C001 missing field: promise" in validate_blueprint_shard(
        shard, valid.replace("- promise: 伏笔", "", 1)
    )


def test_shard_validation_binds_chapter_identity_to_heading() -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[0]
    cards = _render_shard(1, 40)
    cards = cards.replace(
        "## C001 章名\n- objective:",
        "## C001 章名\n- chapter_id: C299\n- title: 错名\n- objective:",
        1,
    )
    cards = cards.replace(
        "## C002 章名\n- objective:",
        "## C002 章名\n- chapter_id: C002\n- title: 章名\n- objective:",
        1,
    )
    for chapter in range(3, 41):
        cards = cards.replace(
            f"## C{chapter:03d} 章名\n- objective:",
            f"## C{chapter:03d} 章名\n- chapter_id: C{chapter:03d}\n- title: 章名\n- objective:",
            1,
        )

    issues = validate_blueprint_shard(
        shard, cards, required_fields=("chapter_id", "title")
    )

    assert "C001 chapter_id mismatch: C299" in issues
    assert "C001 title mismatch: 错名" in issues


def test_assembly_is_ordered_complete_and_rejects_invalid_shards() -> None:
    plan = build_blueprint_shard_plan(total_chapters=600, volume_count=15)
    outputs = {item.volume_id: _render_shard(*item.chapters[:: len(item.chapters) - 1]) for item in plan}

    assembled = assemble_blueprint_shards(
        plan, outputs, title="山河有约", protocol_ref="narrative.blueprint.v1"
    )

    assert assembled.startswith("# 山河有约：600章故事蓝本")
    assert assembled.count("\n## C") == 600
    assert assembled.index("## C001") < assembled.index("## C600")
    with pytest.raises(ValueError, match="V15"):
        assemble_blueprint_shards(
            plan,
            {**outputs, "V15": _render_shard(561, 599)},
            title="山河有约",
            protocol_ref="narrative.blueprint.v1",
        )


def test_selective_revision_reuses_only_a_validated_baseline_shard(tmp_path) -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[0]
    valid_id = "attempt-writer-rev3-v01-r04"
    invalid_id = "attempt-writer-rev3-v01-r05"
    for attempt_id, text in (
        (valid_id, _render_shard(1, 40)),
        (invalid_id, _render_shard(1, 39)),
    ):
        attempt_dir = tmp_path / "attempt_logs" / attempt_id
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "output.md").write_text(text, encoding="utf-8")
    attempts = {
        valid_id: {
            "status": "succeeded",
            "output_validation": {"status": "pass"},
        },
        invalid_id: {
            "status": "succeeded",
            "output_validation": {"status": "pass"},
        },
    }

    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=3,
        )
        == valid_id
    )
    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=4,
        )
        == valid_id
    )
    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=2,
        )
        is None
    )

    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=4,
            semantic_contract={"forbidden_phrases": ["目标"]},
        )
        is None
    )


def test_shard_semantic_contract_rejects_missing_and_forbidden_text() -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[13]
    contract = {
        "required_phrases": ["旧仙规则彻底崩解", "散尽全部既有权柄"],
        "forbidden_phrases": ["夺得本宇宙唯一解释权", "白光巨手"],
    }

    assert validate_blueprint_shard_semantics(
        shard,
        "旧仙规则彻底崩解；散尽全部既有权柄。\n"
        "- forbidden_early_payoffs: 禁止夺得本宇宙唯一解释权与白光巨手。",
        contract,
    ) == ()
    assert validate_blueprint_shard_semantics(
        shard,
        "旧仙规则彻底崩解，却夺得本宇宙唯一解释权。",
        contract,
    ) == (
        "V14 missing required phrase: 散尽全部既有权柄",
        "V14 contains forbidden phrase: 夺得本宇宙唯一解释权",
    )


def test_shard_semantic_contract_scopes_rules_to_exact_chapters() -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[0]
    text = _render_shard(1, 40).replace(
        "## C002 章名\n- objective: 目标",
        "## C002 章名\n- objective: 十六文用于买药与藏身，只留最后一文",
        1,
    )
    contract = {
        "chapter_rules": {
            "C002": {
                "required_phrases": ["十六文用于买药与藏身"],
                "forbidden_phrases": ["起章已经身无分文"],
            }
        }
    }

    assert validate_blueprint_shard_semantics(shard, text, contract) == ()
    assert validate_blueprint_shard_semantics(
        shard, text.replace("十六文用于买药与藏身", "起章已经身无分文"), contract
    ) == (
        "C002 missing required phrase: 十六文用于买药与藏身",
        "C002 contains forbidden phrase: 起章已经身无分文",
    )
