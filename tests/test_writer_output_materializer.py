from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent_runtime.writer_output_materializer import (
    REQUIRED_WRITER_OUTPUTS,
    materialize_writer_candidate_content,
)


def _blocks(task_id: str = "task_ch01", *, omit: str | None = None) -> str:
    values = {
        "fiction_draft.md": "# Chapter 1\n\nA substantive candidate draft.\n",
        "continuity_ledger.yml": (
            "schema_version: 1\nchapter: 1\nbaseline_mode: reset\n"
            "timeline:\n  monotonic: true\nwriter_value: kept\n"
        ),
        "state_transition_proposal.yml": (
            "schema_version: 1\nstatus: candidate\nrequires_user_promotion: true\n"
            "events:\n  - event_type: plot\n    scope: candidate_only\n"
        ),
        "narrative_delivery_receipt.yml": (
            "schema_version: 1\nstatus: pass\ncandidate_only: true\n"
        ),
    }
    return "\n".join(
        f"<!-- AGENTLAB_EDIT: runs/{task_id}/{name} -->\n```text\n{content}```\n<!-- END AGENTLAB_EDIT -->"
        for name, content in values.items()
        if name != omit
    )


def test_materializer_writes_all_writer_candidates_without_fences(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"

    ok = materialize_writer_candidate_content(_blocks(), run_dir, "task_ch01")

    assert ok is True
    assert (
        (run_dir / "fiction_draft.md")
        .read_text(encoding="utf-8")
        .startswith("# Chapter 1")
    )
    ledger = yaml.safe_load(
        (run_dir / "continuity_ledger.yml").read_text(encoding="utf-8")
    )
    assert ledger["writer_value"] == "kept"
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "pass"
    assert contract["materialized_outputs"] == sorted(
        [
            "fiction_draft.md",
            "continuity_ledger.yml",
            "state_transition_proposal.yml",
            "narrative_delivery_receipt.yml",
        ]
    )
    assert contract["normalizations"] == []


def test_materializer_normalizes_duplicate_end_token_and_records_it(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    malformed = _blocks().replace(
        "<!-- END AGENTLAB_EDIT -->",
        "<!-- END END AGENTLAB_EDIT -->",
        1,
    )

    ok = materialize_writer_candidate_content(malformed, run_dir, "task_ch01")

    assert ok is True
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "pass"
    assert contract["normalizations"] == [
        {"id": "duplicate_end_token", "count": 1}
    ]
    capture = (run_dir / "writer_role_session_capture.md").read_text(encoding="utf-8")
    assert "<!-- END END AGENTLAB_EDIT -->" in capture


def test_materializer_normalizes_event_scope_copied_from_event_type(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    copied_scope = _blocks().replace(
        "event_type: plot\n    scope: candidate_only",
        "event_type: plot\n    scope: plot",
    )

    ok = materialize_writer_candidate_content(copied_scope, run_dir, "task_ch01")

    assert ok is True
    proposal = yaml.safe_load(
        (run_dir / "state_transition_proposal.yml").read_text(encoding="utf-8")
    )
    assert proposal["events"][0]["scope"] == "candidate_only"
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["normalizations"] == [
        {"id": "event_scope_copied_from_event_type", "count": 1}
    ]


def test_materializer_does_not_normalize_explicit_production_scope(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    production_scope = _blocks().replace(
        "scope: candidate_only",
        "scope: production",
        1,
    )

    ok = materialize_writer_candidate_content(production_scope, run_dir, "task_ch01")

    assert ok is False
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["normalizations"] == []
    assert "invalid_writer_output_schema:state_transition_proposal.yml" in contract["issues"]


@pytest.mark.parametrize(
    "scope",
    ["character_action", "character_relationship_progress"],
)
def test_materializer_normalizes_known_candidate_scope_category(
    tmp_path: Path,
    scope: str,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    category_scope = _blocks().replace(
        "scope: candidate_only",
        f"scope: {scope}",
        1,
    )

    ok = materialize_writer_candidate_content(category_scope, run_dir, "task_ch01")

    assert ok is True
    proposal = yaml.safe_load(
        (run_dir / "state_transition_proposal.yml").read_text(encoding="utf-8")
    )
    assert proposal["events"][0]["scope"] == "candidate_only"
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["normalizations"] == [
        {"id": "event_scope_category_to_candidate_only", "count": 1}
    ]


def test_materializer_is_transactional_when_required_output_is_missing(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    incomplete = _blocks(omit="narrative_delivery_receipt.yml")

    ok = materialize_writer_candidate_content(incomplete, run_dir, "task_ch01")

    assert ok is False
    assert not (run_dir / "fiction_draft.md").exists()
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "blocked"
    assert "missing_writer_output:narrative_delivery_receipt.yml" in contract["issues"]


def test_materializer_rejects_cross_run_target(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    cross_run = _blocks().replace(
        "runs/task_ch01/fiction_draft.md",
        "runs/task_ch02/fiction_draft.md",
    )

    ok = materialize_writer_candidate_content(cross_run, run_dir, "task_ch01")

    assert ok is False
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert (
        "writer_output_wrong_run:runs/task_ch02/fiction_draft.md" in contract["issues"]
    )


def test_materializer_rejects_present_but_noncanonical_writer_yaml(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    noncanonical = _blocks().replace(
        "schema_version: 1\nstatus: candidate\nrequires_user_promotion: true\n"
        "events:\n  - event_type: plot\n    scope: candidate_only\n",
        "schema_version: 2\nproposed_transitions:\n  - action: update_state\n",
    )

    ok = materialize_writer_candidate_content(noncanonical, run_dir, "task_ch01")

    assert ok is False
    assert not (run_dir / "fiction_draft.md").exists()
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "blocked"
    assert (
        "invalid_writer_output_schema:state_transition_proposal.yml"
        in contract["issues"]
    )


def test_materializer_rejects_short_governed_chapter_before_writing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "task_ch01"
    run_dir.mkdir(parents=True)
    (run_dir / "chapter_packet.yml").write_text(
        yaml.safe_dump(
            {
                "chapter": 1,
                "baseline_mode": "reset",
                "chapter_intent": {"hard_character_range": [3000, 8000]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ok = materialize_writer_candidate_content(_blocks(), run_dir, "task_ch01")

    assert ok is False
    assert not (run_dir / "fiction_draft.md").exists()
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert "draft_character_count_out_of_range" in contract["issues"]
    assert contract["measurements"]["fiction_draft_characters"] == len(
        "# Chapter 1\n\nA substantive candidate draft."
    )


def test_materializer_rejects_substantive_paragraph_copied_from_previous_chapter(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Crown_of_Ash"
    previous_dir = project_root / "runs" / "task_ch01"
    run_dir = project_root / "runs" / "task_ch02"
    previous_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    repeated = "这是一段不应在相邻章节中被逐字复制的实质叙事内容。" * 12
    previous_draft = "# 第1章\n\n" + repeated + "\n\n" + ("前章独有内容。" * 500)
    current_draft = "# 第2章\n\n" + repeated + "\n\n" + ("本章全新内容。" * 500)
    (previous_dir / "fiction_draft.md").write_text(previous_draft, encoding="utf-8")
    (run_dir / "chapter_packet.yml").write_text(
        yaml.safe_dump(
            {
                "chapter": 2,
                "baseline_mode": "continuation",
                "chapter_intent": {"hard_character_range": [3000, 8000]},
                "previous_candidate_sources": [
                    "runs/task_ch01/fiction_draft.md",
                    "runs/task_ch01/continuity_ledger.yml",
                    "runs/task_ch01/state_transition_proposal.yml",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    values = {
        "fiction_draft.md": current_draft,
        "continuity_ledger.yml": yaml.safe_dump(
            {
                "schema_version": 1,
                "chapter": 2,
                "baseline_mode": "continuation",
                "timeline": {"monotonic": True},
                "plot_state_changes": ["new plot"],
                "character_changes": ["new character state"],
                "relationship_or_worldline_changes": ["new relationship state"],
                "foreshadowing": ["new foreshadowing state"],
            },
            sort_keys=False,
        ),
        "state_transition_proposal.yml": yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "chapter": 2,
                "requires_user_promotion": True,
                "events": [{"event_type": "plot", "scope": "candidate_only"}],
            },
            sort_keys=False,
        ),
        "narrative_delivery_receipt.yml": yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "candidate_only": True,
                "checks": {
                    "chapter_and_title": "pass",
                    "required_beats": "pass",
                    "continuity_outputs": "pass",
                    "production_untouched": "pass",
                    "deprecated_sources_excluded": "pass",
                },
            },
            sort_keys=False,
        ),
    }
    content = "\n\n".join(
        f"<!-- AGENTLAB_EDIT: runs/task_ch02/{name} -->\n{value.rstrip()}\n"
        "<!-- END AGENTLAB_EDIT -->"
        for name, value in values.items()
    )

    assert not materialize_writer_candidate_content(content, run_dir, "task_ch02")
    assert not (run_dir / "fiction_draft.md").exists()
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert any(
        issue.startswith("draft_repeats_previous_candidate:")
        for issue in contract["issues"]
    )


# ---------------------------------------------------------------------------
# Phase 1R — v2 prose-only Writer tests
# ---------------------------------------------------------------------------


def _v2_prose_block(task_id: str = "task_ch10") -> str:
    return (
        f"<!-- AGENTLAB_EDIT: runs/{task_id}/fiction_draft.md -->\n"
        "# 章十 · 试炼之焰\n\n"
        "烈焰在凯恩指尖跳跃，不是灼烧，是辨认。\n"
        "<!-- END AGENTLAB_EDIT -->"
    )


def _v2_blocks_with_forbidden_outputs(task_id: str = "task_ch10") -> str:
    """Writer v2 content that illegally includes v1 artifacts."""
    prose = (
        f"<!-- AGENTLAB_EDIT: runs/{task_id}/fiction_draft.md -->\n"
        "# 章十 · 试炼之焰\n\n"
        "烈焰在凯恩指尖跳跃。\n"
        "<!-- END AGENTLAB_EDIT -->"
    )
    ledger = (
        f"<!-- AGENTLAB_EDIT: runs/{task_id}/continuity_ledger.yml -->\n"
        "schema_version: 1\nchapter: 10\n"
        "<!-- END AGENTLAB_EDIT -->"
    )
    receipt = (
        f"<!-- AGENTLAB_EDIT: runs/{task_id}/narrative_delivery_receipt.yml -->\n"
        "schema_version: 1\nstatus: pass\ncandidate_only: true\n"
        "<!-- END AGENTLAB_EDIT -->"
    )
    return "\n".join([prose, ledger, receipt])


def test_writer_v2_materializes_only_fiction_draft(tmp_path: Path) -> None:
    """writer_v2_content_outputs_exactly_fiction_draft_md"""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch10"
    result = materialize_writer_v2_content(
        _v2_prose_block(), run_dir, "task_ch10",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-001",
    )

    assert result["status"] == "pass"
    assert result["non_prose_output_count"] == 0
    assert result["writer_self_receipt_present"] is False
    assert result["prose_sha256"] != ""
    receipt = result.get("agentlab_receipt")
    assert receipt is not None
    assert receipt["issuer"] == "AgentLab"
    assert receipt["prose_sha256"] == result["prose_sha256"]
    assert receipt["observed_provider"] == "deepseek"
    assert receipt["observed_model"] == "deepseek-v4-pro"
    assert receipt["observed_call_id"] == "call-001"
    assert receipt["writer_cannot_overwrite"] is True
    assert (run_dir / "fiction_draft.md").is_file()
    content = (run_dir / "fiction_draft.md").read_text(encoding="utf-8")
    assert "章十" in content


def test_writer_v2_rejects_forbidden_v1_outputs(tmp_path: Path) -> None:
    """writer_non_prose_content_output_count_is_zero — forbidden v1 outputs
    (ledger, receipt) are rejected at the edit-block level and block the run."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch10"
    result = materialize_writer_v2_content(
        _v2_blocks_with_forbidden_outputs(), run_dir, "task_ch10"
    )

    assert result["status"] == "blocked"
    assert result["non_prose_output_count"] > 0
    assert not (run_dir / "fiction_draft.md").exists()


def _write_live_writer_session_binding(run_dir: Path, task_id: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    project_root = run_dir.parent.parent
    root = project_root.parent.parent
    brief_path = project_root / "candidates" / "test" / "brief_ch010.yml"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        yaml.safe_dump(
            {
                "chapter": 10,
                "pov": "Kane",
                "scene_goal": "test the flame",
                "irreversible_plot_change": "the flame identifies Kane",
                "closing_state": "the trial continues",
                "character_state_change": "Kane chooses observation",
                "reader_question": "What does the flame know?",
                "target_character_range": [1, 100],
                "must_preserve": ["Kane remains active"],
                "creative_freedom": ["dialogue rhythm"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = run_dir / "narrative_v2_writer_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "job_kind": "narrative_generation",
                "run_mode": "generate_candidate",
                "project": "ProbeNovel",
                "task_id": task_id,
                "chapter_id": 10,
                "candidate_only": True,
                "production_modified": False,
                "external_context_approval_required": True,
                "creative_brief_source": {
                    "path": brief_path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(brief_path.read_bytes()).hexdigest(),
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec_sha256 = "b" * 64
    plan_path = run_dir / "workflow_plan.yml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "project": "ProbeNovel",
                "task_id": task_id,
                "agentlab_root": str(root),
                "project_root": str(project_root),
                "repo_path": str(project_root / "repo"),
                "run_dir": str(run_dir),
                "user_request_path": str(request_path),
                "execution_backend": "agentlab_orchestrated_cli",
                "budget_mode": "balanced",
                "route": {
                    "task_size": "small",
                    "agents": ["Writer"],
                    "route_key": "narrative_generation_v2",
                },
                "included_agents": {
                    "Writer": {"required_outputs": ["fiction_draft.md"]}
                },
                "execution_policy": {
                    "external_context_approval_required": True
                },
                "notes": [
                    f"narrative_live_preflight_spec_sha256:{spec_sha256}"
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    activation_dir = project_root / "runs" / "_narrative_v2_preflight_batches"
    activation_dir.mkdir()
    (activation_dir / f"{spec_sha256}.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "active",
                "project": "ProbeNovel",
                "preflight_spec_sha256": spec_sha256,
                "candidate_only": True,
                "production_modified": False,
                "task_count": 1,
                "tasks": [
                    {
                        "task_id": task_id,
                        "request_path": request_path.relative_to(root).as_posix(),
                        "request_sha256": hashlib.sha256(
                            request_path.read_bytes()
                        ).hexdigest(),
                        "workflow_plan_path": plan_path.relative_to(
                            root
                        ).as_posix(),
                        "workflow_plan_sha256": hashlib.sha256(
                            plan_path.read_bytes()
                        ).hexdigest(),
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "narrative_v2_writer_session_receipt.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "job_kind": "narrative_generation",
                "run_mode": "generate_candidate",
                "project": "ProbeNovel",
                "task_id": task_id,
                "chapter_id": 10,
                "candidate_only": True,
                "production_modified": False,
                "external_context_approval_required": True,
                "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "compiled_packet_sha256": "a" * 64,
                "prose_length_contract": {
                    "unit": "han_characters_excluding_markdown_headings",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_live_writer_delivery_materializes_prose_and_agentlab_receipt(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_live_writer_result,
    )

    run_dir = tmp_path / "projects" / "ProbeNovel" / "runs" / "task_ch10"
    _write_live_writer_session_binding(run_dir, "task_ch10")
    result = SimpleNamespace(
        status="completed",
        provider="deepseek",
        model="deepseek-v4-pro",
        content=_v2_prose_block(),
        raw_usage={"provider_session_id": "writer-call-1"},
    )

    delivery = materialize_live_writer_result(result, run_dir, "task_ch10")

    assert delivery["status"] == "pass"
    prose_hash = hashlib.sha256((run_dir / "fiction_draft.md").read_bytes()).hexdigest()
    receipt = yaml.safe_load(
        (run_dir / "writer_execution_receipt.yml").read_text(encoding="utf-8")
    )
    contract = yaml.safe_load(
        (run_dir / "writer_v2_output_contract.yml").read_text(encoding="utf-8")
    )
    assert receipt["issuer"] == "AgentLab"
    assert receipt["prose_sha256"] == prose_hash
    assert contract["status"] == "pass"
    assert contract["prose_sha256"] == prose_hash
    assert contract["non_prose_output_count"] == 0
    assert contract["writer_self_receipt_present"] is False


def test_live_writer_delivery_failure_keeps_no_prose_or_success_receipt(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_live_writer_result,
    )

    run_dir = tmp_path / "projects" / "ProbeNovel" / "runs" / "task_ch10"
    _write_live_writer_session_binding(run_dir, "task_ch10")
    result = SimpleNamespace(
        status="completed",
        provider="deepseek",
        model="deepseek-v4-pro",
        content=_v2_blocks_with_forbidden_outputs(),
        raw_usage={},
    )

    delivery = materialize_live_writer_result(result, run_dir, "task_ch10")

    assert delivery["status"] == "blocked"
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "writer_execution_receipt.yml").exists()
    contract = yaml.safe_load(
        (run_dir / "writer_v2_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "blocked"
    assert contract["issues"]


def test_live_writer_delivery_rejects_noncompleted_result_before_materializing(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_live_writer_result,
    )

    run_dir = tmp_path / "projects" / "ProbeNovel" / "runs" / "task_ch10"
    _write_live_writer_session_binding(run_dir, "task_ch10")
    result = SimpleNamespace(
        status="failed",
        provider="deepseek",
        model="deepseek-v4-pro",
        content=_v2_prose_block(),
        raw_usage={},
    )

    delivery = materialize_live_writer_result(result, run_dir, "task_ch10")

    assert delivery["status"] == "blocked"
    assert delivery["issues"] == ["live_writer_result_not_completed"]
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "writer_execution_receipt.yml").exists()


def test_live_writer_delivery_rejects_stale_session_binding(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_live_writer_result,
    )

    run_dir = tmp_path / "projects" / "ProbeNovel" / "runs" / "task_ch10"
    _write_live_writer_session_binding(run_dir, "task_ch10")
    request_path = run_dir / "narrative_v2_writer_request.yml"
    request_path.write_text(
        request_path.read_text(encoding="utf-8") + "changed: true\n",
        encoding="utf-8",
    )
    result = SimpleNamespace(
        status="completed",
        provider="deepseek",
        model="deepseek-v4-pro",
        content=_v2_prose_block(),
        raw_usage={},
    )

    delivery = materialize_live_writer_result(result, run_dir, "task_ch10")

    assert delivery["status"] == "blocked"
    assert delivery["issues"] == ["live_writer_session_request_hash_mismatch"]
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "writer_execution_receipt.yml").exists()


def test_registered_writer_delivery_selects_v2_materializer_from_request(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_registered_writer_result,
    )

    run_dir = tmp_path / "projects" / "ProbeNovel" / "runs" / "task_ch10"
    _write_live_writer_session_binding(run_dir, "task_ch10")
    result = SimpleNamespace(
        status="completed",
        provider="deepseek",
        model="deepseek-v4-pro",
        content=_v2_prose_block(),
        raw_usage={"provider_session_id": "writer-call-2"},
    )

    delivery = materialize_registered_writer_result(result, run_dir, "task_ch10")

    assert delivery["status"] == "pass"
    assert Path(delivery["contract_path"]).name == "writer_v2_output_contract.yml"
    assert Path(delivery["output_path"]).name == "fiction_draft.md"
    assert (run_dir / "writer_execution_receipt.yml").is_file()


def test_registered_writer_delivery_preserves_legacy_four_output_path(
    tmp_path: Path,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_registered_writer_result,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    result = SimpleNamespace(
        status="completed",
        provider="legacy",
        model="legacy-model",
        content=_blocks("task_ch01"),
        raw_usage={},
    )

    delivery = materialize_registered_writer_result(result, run_dir, "task_ch01")

    assert delivery["status"] == "pass"
    assert Path(delivery["contract_path"]).name == "writer_output_contract.yml"
    assert (run_dir / "fiction_draft.md").is_file()
    assert (run_dir / "continuity_ledger.yml").is_file()


@pytest.mark.parametrize("invalid_content", ["not structured", ""])
def test_registered_writer_delivery_clears_stale_legacy_outputs_after_failure(
    tmp_path: Path,
    invalid_content: str,
) -> None:
    from agent_runtime.narrative.production.live_writer import (
        materialize_registered_writer_result,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    valid_result = SimpleNamespace(
        status="completed",
        provider="legacy",
        model="legacy-model",
        content=_blocks("task_ch01"),
        raw_usage={},
    )
    invalid_result = SimpleNamespace(
        status="completed",
        provider="legacy",
        model="legacy-model",
        content=invalid_content,
        raw_usage={},
    )

    first_delivery = materialize_registered_writer_result(
        valid_result,
        run_dir,
        "task_ch01",
    )
    retry_delivery = materialize_registered_writer_result(
        invalid_result,
        run_dir,
        "task_ch01",
    )

    assert first_delivery["status"] == "pass"
    assert retry_delivery["status"] == "blocked"
    assert Path(retry_delivery["contract_path"]).name == "writer_output_contract.yml"
    assert all(not (run_dir / name).exists() for name in REQUIRED_WRITER_OUTPUTS)
    contract = yaml.safe_load(
        (run_dir / "writer_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "blocked"


# ---------------------------------------------------------------------------
# Phase 1R correction 1 — boundary tests for materialize_writer_v2_content
# ---------------------------------------------------------------------------


def _v2_block_raw(path: str, content: str) -> str:
    return (
        f"<!-- AGENTLAB_EDIT: {path} -->\n"
        f"{content}\n"
        "<!-- END AGENTLAB_EDIT -->"
    )


def test_v2_materializer_rejects_non_fiction_block(tmp_path: Path) -> None:
    """Arbitrary scorecard/metadata blocks are rejected."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = "\n".join([
        _v2_block_raw("runs/task_ch01/fiction_draft.md", "# 章一 · 开始\n\nprose"),
        _v2_block_raw("runs/task_ch01/scorecard.yml", "score: 5"),
    ])

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("non_fiction_block_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_unknown_output_name(tmp_path: Path) -> None:
    """An arbitrary metadata name (not fiction_draft.md) blocks the run."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = "\n".join([
        _v2_block_raw("runs/task_ch01/fiction_draft.md", "# 章一 · 开始\n\nprose"),
        _v2_block_raw("runs/task_ch01/metadata.yml", "key: value"),
    ])

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("non_fiction_block_rejected" in i for i in result["issues"])


def test_v2_materializer_rejects_duplicate_fiction_block(tmp_path: Path) -> None:
    """Duplicate fiction_draft.md blocks are rejected."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = "\n".join([
        _v2_block_raw("runs/task_ch01/fiction_draft.md", "# 章一 · 开始\n\nprose A"),
        _v2_block_raw("runs/task_ch01/fiction_draft.md", "# 章一 · 开始\n\nprose B"),
    ])

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("duplicate_fiction_draft_block" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_blank_fiction_block(tmp_path: Path) -> None:
    """A fiction_draft.md block with only whitespace is rejected —
    the parse layer may drop it (missing_fiction_draft_md) or the validator
    may reject it as empty (fiction_draft_block_empty)."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    # Use whitespace so the block is syntactically present but semantically empty.
    content = _v2_block_raw("runs/task_ch01/fiction_draft.md", "   ")

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any(
        "fiction_draft_block_empty" in i
        or "missing_fiction_draft_md" in i
        for i in result["issues"]
    )
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_absolute_path(tmp_path: Path) -> None:
    """Absolute paths in edit blocks are rejected."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = _v2_block_raw("/etc/fiction_draft.md", "# prose")

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("absolute_path_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_traversal_path(tmp_path: Path) -> None:
    """Traversal (..) in edit block paths is rejected."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = _v2_block_raw(
        "runs/task_ch01/../other/fiction_draft.md", "# prose"
    )

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("traversal_path_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_cross_run_path(tmp_path: Path) -> None:
    """A fiction_draft.md targeting another task_id is rejected."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = _v2_block_raw(
        "runs/task_ch02/fiction_draft.md", "# 章二\n\nprose for ch02"
    )

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("cross_run_path_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_cross_run_substring_is_not_a_match(tmp_path: Path) -> None:
    """writer_target_path_is_exact_not_substring — a path like
    runs/task_ch01_extra/fiction_draft.md must NOT match task_id task_ch01."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    # task_id is "task_ch01" but the path uses "task_ch01_extra" — substring
    # would incorrectly match; exact path-component match rejects it.
    content = _v2_block_raw(
        "runs/task_ch01_extra/fiction_draft.md",
        "# 章一\n\nprose for extra task\n",
    )

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert any("cross_run_path_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_persisted_receipt_hash_equals_written_prose_bytes(
    tmp_path: Path,
) -> None:
    """persisted_receipt_hash_equals_written_prose_bytes — the receipt
    hash is computed from the actual written file bytes, not the
    pre-write string, and the receipt is persisted to disk."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )
    import hashlib
    import yaml as _yaml

    run_dir = tmp_path / "runs" / "task_ch20"
    result = materialize_writer_v2_content(
        _v2_prose_block("task_ch20"), run_dir, "task_ch20",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-rcpt",
    )

    assert result["status"] == "pass"
    assert (run_dir / "fiction_draft.md").is_file()

    # Receipt must be persisted to disk.
    receipt_path = run_dir / "writer_execution_receipt.yml"
    assert receipt_path.is_file(), "receipt not persisted to disk"
    receipt_on_disk = _yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    assert receipt_on_disk["issuer"] == "AgentLab"
    assert receipt_on_disk["observed_provider"] == "deepseek"

    # Hash in receipt must equal hash of the actual written file bytes.
    file_hash = hashlib.sha256(
        (run_dir / "fiction_draft.md").read_bytes()
    ).hexdigest()
    assert result["prose_sha256"] == file_hash
    assert receipt_on_disk["prose_sha256"] == file_hash
    assert result.get("agentlab_receipt", {}).get("prose_sha256") == file_hash
    assert result.get("receipt_path") == str(receipt_path)


def test_v2_failed_materialization_leaves_no_prose_or_receipt(
    tmp_path: Path,
) -> None:
    """failed_materialization_leaves_no_prose_or_receipt — on any block
    issue, neither fiction_draft.md nor the receipt is written."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    # Include a forbidden non-fiction block to trigger failure.
    content = "\n".join([
        _v2_block_raw("runs/task_ch01/fiction_draft.md", "# 章一\n\nprose"),
        _v2_block_raw("runs/task_ch01/scorecard.yml", "score: 5"),
    ])

    result = materialize_writer_v2_content(content, run_dir, "task_ch01")
    assert result["status"] == "blocked"
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "writer_execution_receipt.yml").exists()


def test_v2_validation_failure_removes_stale_prose_and_receipt(
    tmp_path: Path,
) -> None:
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_stale"
    run_dir.mkdir(parents=True)
    (run_dir / "fiction_draft.md").write_text("stale prose", encoding="utf-8")
    (run_dir / "writer_execution_receipt.yml").write_text(
        "issuer: stale\n", encoding="utf-8"
    )

    result = materialize_writer_v2_content(
        _v2_block_raw("runs/other_task/fiction_draft.md", "invalid"),
        run_dir,
        "task_stale",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_id="call-stale-cleanup",
    )

    assert result["status"] == "blocked"
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "writer_execution_receipt.yml").exists()


def test_v2_materializer_rejects_empty_source_hashes_in_brief(
    tmp_path: Path,
) -> None:
    """A creative brief with empty source_hashes is rejected at
    validation time."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 14,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {},
    }
    issues = validate_creative_brief(data)
    assert any("source_hashes_must_not_be_empty" in i for i in issues)


# ---------------------------------------------------------------------------
# Phase 1R correction 3 — nested path, provenance, and canonical bytes
# ---------------------------------------------------------------------------


def test_v2_materializer_rejects_nested_target_path(tmp_path: Path) -> None:
    """writer_target_equals_exact_run_fiction_path — a path like
    runs/task_ch01/sub/fiction_draft.md is NOT the contract target and
    must be rejected.  Only runs/<task_id>/fiction_draft.md is valid."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch01"
    content = _v2_block_raw(
        "runs/task_ch01/sub/fiction_draft.md",
        "# 章一\n\n嵌套路径中的散文。\n",
    )

    result = materialize_writer_v2_content(
        content, run_dir, "task_ch01",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-nested",
    )
    assert result["status"] == "blocked"
    assert any("cross_run_path_rejected" in i for i in result["issues"])
    assert not (run_dir / "fiction_draft.md").exists()


def test_v2_materializer_rejects_missing_provenance(tmp_path: Path) -> None:
    """observed_provenance_is_required_on_all_success_paths — when
    provider, model, or call_id is missing, the result is blocked even
    if every other check passes."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch99"

    # Empty provider.
    result1 = materialize_writer_v2_content(
        _v2_prose_block("task_ch99"), run_dir, "task_ch99",
        provider="", model="deepseek-v4-pro", call_id="call-001",
    )
    assert result1["status"] == "blocked"
    assert any("missing_observed_provenance" in i for i in result1["issues"])
    assert result1.get("agentlab_receipt") is None
    assert not (run_dir / "fiction_draft.md").exists()

    # Empty model.
    run_dir2 = tmp_path / "runs" / "task_ch98"
    result2 = materialize_writer_v2_content(
        _v2_prose_block("task_ch98"), run_dir2, "task_ch98",
        provider="deepseek", model="", call_id="call-001",
    )
    assert result2["status"] == "blocked"
    assert any("missing_observed_provenance" in i for i in result2["issues"])

    # All provenance present — passes.
    run_dir3 = tmp_path / "runs" / "task_ch97"
    result3 = materialize_writer_v2_content(
        _v2_prose_block("task_ch97"), run_dir3, "task_ch97",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-001",
    )
    assert result3["status"] == "pass"
    assert result3.get("agentlab_receipt") is not None


def test_v2_receipt_filename_is_writer_execution_receipt(tmp_path: Path) -> None:
    """required_writer_execution_receipt_is_persisted_atomically — the
    receipt filename on disk must be writer_execution_receipt.yml, not
    agentlab_writer_receipt.yml."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    run_dir = tmp_path / "runs" / "task_ch30"
    result = materialize_writer_v2_content(
        _v2_prose_block("task_ch30"), run_dir, "task_ch30",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-fname",
    )

    assert result["status"] == "pass"
    # Exact filename per contract.
    receipt_path = run_dir / "writer_execution_receipt.yml"
    assert receipt_path.is_file(), f"expected {receipt_path} to exist"
    # Old name must NOT exist.
    assert not (run_dir / "agentlab_writer_receipt.yml").exists()
    assert result.get("receipt_path") == str(receipt_path)


def test_v2_canonical_prose_bytes_match_written_file(
    tmp_path: Path,
) -> None:
    """canonical_prose_bytes_are_shared_by_validation_write_and_hash —
    prose with trailing whitespace is canonicalised to one newline before
    hashing, so the receipt hash always equals the written file hash."""
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )
    import hashlib

    run_dir = tmp_path / "runs" / "task_ch40"
    # Prose with trailing whitespace (not just newline).
    prose_with_whitespace = "# 章四十\n\n结尾有空白。  \n  \n"
    block = _v2_block_raw("runs/task_ch40/fiction_draft.md", prose_with_whitespace)

    result = materialize_writer_v2_content(
        block, run_dir, "task_ch40",
        provider="deepseek", model="deepseek-v4-pro", call_id="call-canon",
    )

    assert result["status"] == "pass"
    assert (run_dir / "fiction_draft.md").is_file()

    # Hash in result MUST equal hash of the written file bytes.
    file_bytes = (run_dir / "fiction_draft.md").read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    assert result["prose_sha256"] == file_hash

    # The receipt on disk must agree.
    import yaml as _yaml
    receipt = _yaml.safe_load(
        (run_dir / "writer_execution_receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["prose_sha256"] == file_hash


# ---------------------------------------------------------------------------
# Phase 1R correction 3 resume — pathlib source-key validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,expected_issue_substring",
    [
        ("", "source_hash_key_empty_or_whitespace"),
        ("   ", "source_hash_key_empty_or_whitespace"),
        ("\t", "source_hash_key_empty_or_whitespace"),
        ("relative/path.yml", "source_hash_key_not_canonical_absolute"),
        ("/", "source_hash_key_not_canonical"),
        ("//etc/passwd", "source_hash_key_not_canonical"),
        ("/a/./b/file.yml", "source_hash_key_has_dot_segments"),
        ("/a/../b/file.yml", "source_hash_key_has_dot_segments"),
    ],
)
def test_noncanonical_source_hash_keys_are_rejected(
    key: str, expected_issue_substring: str
) -> None:
    """canonical_existing_file_source_keys_only — every non-canonical form
    (empty, whitespace, relative, root-dir, double-slash, dot-segments) is
    rejected by pathlib semantics, not startswith."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 30,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            key: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        },
    }
    issues = validate_creative_brief(data)
    assert any(expected_issue_substring in i for i in issues), (
        f"expected '{expected_issue_substring}' in issues for key={key!r}, got {issues}"
    )


def test_valid_resolved_tmp_file_passes_source_key_validation(
    tmp_path: Path,
) -> None:
    """A resolved absolute path to an existing file passes validation."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    src = tmp_path / "bible" / "characters.yml"
    src.parent.mkdir(parents=True)
    src.write_text("characters:\n  - name: Kane\n", encoding="utf-8")

    data = {
        "schema_version": 2,
        "chapter_id": 31,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            str(src.resolve()): hashlib.sha256(src.read_bytes()).hexdigest(),
        },
    }
    issues = validate_creative_brief(data)
    assert not issues, f"unexpected issues for valid key: {issues}"
