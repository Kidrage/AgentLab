from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.writer_output_materializer import (
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
