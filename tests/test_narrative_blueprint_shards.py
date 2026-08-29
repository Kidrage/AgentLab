import hashlib
from pathlib import Path

import pytest
import yaml

from agent_runtime.narrative.blueprint_shards import (
    assemble_blueprint_shards,
    assemble_blueprint_volume_segments,
    build_blueprint_shard_plan,
    find_reusable_blueprint_shard_attempt,
    run_blueprint_shard_workflow,
    split_blueprint_shard,
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
            semantic_contract_path=task_root / "inputs" / "missing-semantics.yml",
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
            semantic_contract_path=task_root / "inputs" / "missing-semantics.yml",
        )
    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == before


def test_assembly_only_mode_does_not_require_live_outbound_authorization(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="ColdBlueprint")
    runtime.create_task(
        task_id="task-cold-blueprint",
        title="Cold blueprint",
        user_goal="Do not transmit during deterministic assembly.",
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
                "purpose": "Expired request retained only as historical evidence.",
                "minimal_fragment": "No transmission in assembly-only mode.",
                "expires_at": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
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
            semantic_contract_path=task_root / "inputs" / "missing-semantics.yml",
            revision=2,
            baseline_revision=1,
            assembly_only_baseline=True,
        )
    assert "external context request is expired" not in str(exc_info.value)


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


def test_volume_shard_can_be_split_for_bounded_generation_without_changing_volume() -> None:
    shard = build_blueprint_shard_plan(total_chapters=600, volume_count=15)[11]

    segments = split_blueprint_shard(shard, max_chapters=20)

    assert [(item.volume_id, item.start_chapter, item.end_chapter) for item in segments] == [
        ("V12", 441, 460),
        ("V12", 461, 480),
    ]
    assert [chapter for item in segments for chapter in item.chapters] == list(
        shard.chapters
    )
    assert split_blueprint_shard(shard, max_chapters=40) == (shard,)


def test_bounded_generation_segments_reassemble_as_one_valid_volume() -> None:
    volume = build_blueprint_shard_plan(total_chapters=40, volume_count=1)[0]
    segments = split_blueprint_shard(volume, max_chapters=20)

    assembled = assemble_blueprint_volume_segments(
        volume,
        segments,
        {
            (segment.start_chapter, segment.end_chapter): _render_shard(
                segment.start_chapter, segment.end_chapter
            )
            for segment in segments
        },
    )

    assert assembled.count("## C") == 40
    assert assembled.index("## C001") < assembled.index("## C040")
    assert validate_blueprint_shard(volume, assembled) == ()


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


def test_assembly_strips_writer_report_envelopes_from_valid_shards() -> None:
    plan = build_blueprint_shard_plan(total_chapters=2, volume_count=1)
    shard = _render_shard(1, 2).replace(
        "- promise: 伏笔",
        "- promise: 伏笔\n"
        "- volume: 1\n"
        "- forbidden_early_payoffs: C002前不得揭露父辈暗账。",
    )
    wrapped = "\n".join(
        [
            "# Writer Report",
            "Generated two chapter cards.",
            "<!-- AGENTLAB_EDIT: story_blueprint -->",
            shard.rstrip(),
            "<!-- /AGENTLAB_EDIT -->",
            "## stderr",
            "禁止蓝图；禁止生成范围外章节。",
            "provider diagnostic that must not enter the artifact",
            "",
        ]
    )

    assembled = assemble_blueprint_shards(
        plan,
        {"V01": wrapped},
        title="山河有约",
        protocol_ref="narrative.blueprint.v1",
        required_fields=(
            "objective",
            "conflict",
            "turn",
            "consequence",
            "promise",
            "volume",
            "forbidden_early_payoffs",
        ),
    )

    assert assembled.count("\n## C") == 2
    assert "Writer Report" not in assembled
    assert "AGENTLAB_EDIT" not in assembled
    assert "stderr" not in assembled
    assert "provider diagnostic" not in assembled
    assert "- volume: V01" in assembled
    assert "C002前不得揭露父辈暗账" in assembled
    assert "禁止蓝图" not in assembled
    assert "禁止生成范围外章节" not in assembled


@pytest.mark.parametrize(
    ("opener", "closer"),
    (
        ("<<<<<< AGENTLAB_EDIT: story_blueprint", ">>>>>>"),
        ("<<<< AGENTLAB_EDIT", ">>>>"),
        ("<<<<<<< AGENTLAB_EDIT", ">>>>>>> AGENTLAB_EDIT"),
        ("<<<< AGENTLAB_EDIT", ">>>> AGENTLAB_EDIT"),
        (
            "<<<< AGENTLAB_EDIT candidate:story_blueprint >>>>",
            "<<<< END_AGENTLAB_EDIT >>>>",
        ),
        (
            "<<<<< AGENTLAB_EDIT: story_blueprint >>>>>",
            "<<<<< END_AGENTLAB_EDIT >>>>>",
        ),
        (
            "<<<< AGENTLAB_EDIT: story_blueprint >>>>",
            "<<<< END_AGENTLAB_EDIT >>>>",
        ),
        (
            "<<<<AGENTLAB_EDIT:story_blueprint>>>>",
            ">>>>END_AGENTLAB_EDIT>>>>",
        ),
    ),
)
def test_assembly_strips_real_chevron_agent_edit_delimiters(
    opener: str, closer: str
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = "\n".join(
        [
            "# Writer Report (CLI Agent: agy)",
            "## Output",
            opener,
            _render_shard(1, 1).rstrip(),
            closer,
            "## stderr",
            "provider diagnostic that must not enter the artifact",
            "",
        ]
    )

    assembled = assemble_blueprint_shards(
        plan,
        {"V01": wrapped},
        title="山河有约",
        protocol_ref="narrative.blueprint.v1",
    )

    assert assembled.count("\n## C") == 1
    assert closer not in assembled
    assert "provider diagnostic" not in assembled


def test_assembly_normalizes_redundant_identity_fields_from_candidate_envelope() -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = "\n".join(
        [
            "<<<<<<< AGENTLAB_EDIT candidate",
            "## C001 正名",
            "- chapter_id: C999",
            "- title: 人物名",
            "- volume: 1",
            "- objective: 目标",
            ">>>>>>> AGENTLAB_EDIT candidate",
            "## stderr",
            "provider diagnostic",
        ]
    )

    assembled = assemble_blueprint_shards(
        plan,
        {"V01": wrapped},
        title="山河有约",
        protocol_ref="narrative.blueprint.v1",
        required_fields=("chapter_id", "title", "volume", "objective"),
    )

    assert "- chapter_id: C001" in assembled
    assert "- title: 正名" in assembled
    assert "- volume: V01" in assembled
    assert "AGENTLAB_EDIT" not in assembled
    assert "provider diagnostic" not in assembled


@pytest.mark.parametrize("near_miss", (">>>", ">>>>", ">>>>>", ">>>>>>>"))
def test_assembly_rejects_near_miss_cli_agent_edit_delimiters(
    near_miss: str,
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = (
        _render_shard(1, 1)
        + near_miss
        + "\n- provider_report: metadata that must remain visible to validation\n"
    )

    with pytest.raises(ValueError, match="undeclared card content"):
        assemble_blueprint_shards(
            plan,
            {"V01": wrapped},
            title="山河有约",
            protocol_ref="narrative.blueprint.v1",
        )


def test_assembly_rejects_asymmetric_cli_agent_edit_delimiter() -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = (
        "<<<< AGENTLAB_EDIT\n"
        + _render_shard(1, 1)
        + ">>>>>\n- provider_report: metadata that must remain visible to validation\n"
        + "## stderr\nprovider diagnostic\n"
    )

    with pytest.raises(ValueError, match="undeclared card content"):
        assemble_blueprint_shards(
            plan,
            {"V01": wrapped},
            title="山河有约",
            protocol_ref="narrative.blueprint.v1",
        )


@pytest.mark.parametrize(
    "malformed_opener",
    (
        "<<<< AGENTLAB_EDIT >>>>>",
        "<<<< AGENTLAB_EDIT garbage >>>>",
    ),
)
def test_assembly_rejects_asymmetric_or_malformed_chevron_openers(
    malformed_opener: str,
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = (
        malformed_opener
        + "\n"
        + _render_shard(1, 1)
        + ">>>>\n- provider_report: metadata that must remain visible to validation\n"
        + "## stderr\nprovider diagnostic\n"
    )

    with pytest.raises(ValueError, match="undeclared card content"):
        assemble_blueprint_shards(
            plan,
            {"V01": wrapped},
            title="山河有约",
            protocol_ref="narrative.blueprint.v1",
        )


def test_assembly_strips_cli_markdown_fence_before_stderr() -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = "\n".join(
        [
            "# Writer Report (CLI Agent: agy)",
            "## Output",
            "```AGENTLAB_EDIT",
            _render_shard(1, 1).rstrip(),
            "```",
            "",
            "## stderr",
            "provider diagnostic that must not enter the artifact",
            "",
        ]
    )

    assembled = assemble_blueprint_shards(
        plan,
        {"V01": wrapped},
        title="山河有约",
        protocol_ref="narrative.blueprint.v1",
    )

    assert "```" not in assembled
    assert "provider diagnostic" not in assembled


@pytest.mark.parametrize(
    ("opener", "closer"),
    (
        (
            "<!-- AGENTLAB_EDIT_START: story_blueprint -->",
            "<!-- AGENTLAB_EDIT_END: story_blueprint -->",
        ),
        (
            "<!-- AGENTLAB_EDIT: story_blueprint -->",
            "<!-- /AGENTLAB_EDIT -->",
        ),
        ("<!-- BEGIN AGENTLAB_EDIT -->", "<!-- END AGENTLAB_EDIT -->"),
        (
            "<!-- BEGIN AGENTLAB_EDIT: story_blueprint -->",
            "<!-- END AGENTLAB_EDIT -->",
        ),
        (
            "<!-- BEGIN AGENTLAB_EDIT artifact_id=story_blueprint -->",
            "<!-- END AGENTLAB_EDIT -->",
        ),
    ),
)
def test_assembly_strips_real_html_agent_edit_delimiters(
    opener: str, closer: str
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = "\n".join(
        [
            opener,
            _render_shard(1, 1).rstrip(),
            closer,
            "## stderr",
            "provider diagnostic that must not enter the artifact",
            "",
        ]
    )

    assembled = assemble_blueprint_shards(
        plan,
        {"V01": wrapped},
        title="山河有约",
        protocol_ref="narrative.blueprint.v1",
    )

    assert "AGENTLAB_EDIT_END" not in assembled
    assert "<!-- /AGENTLAB_EDIT -->" not in assembled
    assert "provider diagnostic" not in assembled


@pytest.mark.parametrize(
    "orphan_closer",
    (
        "<<<< END_AGENTLAB_EDIT >>>>",
        ">>>>END_AGENTLAB_EDIT>>>>",
        "<!-- /AGENTLAB_EDIT -->",
        ">>>>\nAGENTLAB_EDIT",
    ),
)
def test_assembly_rejects_orphan_or_malformed_named_trailers(
    orphan_closer: str,
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    wrapped = (
        _render_shard(1, 1)
        + orphan_closer
        + "\n- provider_report: metadata that must remain visible to validation\n"
        + "## stderr\nprovider diagnostic\n"
    )

    with pytest.raises(ValueError, match="undeclared card content"):
        assemble_blueprint_shards(
            plan,
            {"V01": wrapped},
            title="山河有约",
            protocol_ref="narrative.blueprint.v1",
        )


def test_assembly_rejects_fields_smuggled_after_a_provider_trailer() -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    raw = "## C001 章名\n# Writer Report\n- objective: smuggled\n"

    with pytest.raises(ValueError, match="C001 missing field: objective"):
        assemble_blueprint_shards(
            plan,
            {"V01": raw},
            title="Fixture",
            protocol_ref="narrative.blueprint.v1",
            required_fields=("objective",),
        )


@pytest.mark.parametrize(
    "leaked_content",
    (
        "- provider_report: metadata",
        "- 生产提示: 不得生成范围外章节",
        "provider_report: leaked metadata",
    ),
)
def test_assembly_rejects_undeclared_chapter_card_fields(
    leaked_content: str,
) -> None:
    plan = build_blueprint_shard_plan(total_chapters=1, volume_count=1)
    raw = f"## C001 章名\n- objective: 目标\n{leaked_content}\n"

    with pytest.raises(ValueError, match="undeclared card content|field contract mismatch"):
        assemble_blueprint_shards(
            plan,
            {"V01": raw},
            title="Fixture",
            protocol_ref="narrative.blueprint.v1",
            required_fields=("objective",),
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

    # A successful child is not reusable until a validated baseline composite
    # proves that it belonged to the assembled revision.
    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=3,
        )
        is None
    )
    attempts["attempt-writer-assembled-003"] = {
        "status": "succeeded",
        "output_validation": {"status": "pass"},
        "outcome": {"composite_child_attempt_ids": [valid_id]},
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
            baseline_revision=2,
        )
        is None
    )

    assert (
        find_reusable_blueprint_shard_attempt(
            task_root=tmp_path,
            attempts=attempts,
            shard=shard,
            baseline_revision=3,
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
    ) == (
        "V14 contains forbidden phrase: 夺得本宇宙唯一解释权",
        "V14 contains forbidden phrase: 白光巨手",
    )
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


def test_segment_semantics_ignore_chapter_rules_outside_the_segment() -> None:
    segment = split_blueprint_shard(
        build_blueprint_shard_plan(total_chapters=40, volume_count=1)[0],
        max_chapters=20,
    )[0]
    text = _render_shard(1, 20).replace("- objective: 目标", "- objective: 近段契约", 1)
    contract = {
        "chapter_rules": {
            "C001": {"required_phrases": ["近段契约"]},
            "C040": {"required_phrases": ["远段契约"]},
        }
    }

    assert validate_blueprint_shard_semantics(segment, text, contract) == ()
