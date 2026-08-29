from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from agent_runtime.protocol_canary import run_protocol_canaries
from agent_runtime.task_runtime_v2 import InvalidTransition, TaskRuntime


ROOT = Path(__file__).resolve().parents[1]


def test_novel_and_code_canaries_recover_and_rebuild_deterministically(
    tmp_path: Path,
) -> None:
    report = run_protocol_canaries(
        ROOT,
        state_root=tmp_path,
        iterations=2,
    )

    assert report["schema_version"] == "protocol-canary-report/v1"
    assert report["ok"] is True
    assert report["iterations"] == 2
    assert len(report["runs"]) == 4
    assert {run["canary"] for run in report["runs"]} == {
        "CodeCanary",
        "NovelCanary",
    }
    assert all(run["recovery_injected"] for run in report["runs"])
    assert all(run["doctor_ok"] for run in report["runs"])
    assert all(
        run["accepted_work_items"] == run["work_item_count"] for run in report["runs"]
    )
    assert all(run["task_status"] == "completed" for run in report["runs"])
    assert all(
        run["successful_attempts"] == run["work_item_count"] for run in report["runs"]
    )
    assert all(run["artifact_contracts_satisfied"] for run in report["runs"])
    assert all(run["promotion_gates_satisfied"] for run in report["runs"])

    first = report["runs"][0]
    rebuilt = TaskRuntime(tmp_path, project=first["project"]).rebuild_task(
        first["task_id"]
    )
    assert rebuilt["last_event_hash"] == first["last_event_hash"]
    assert (
        "source-story-bible"
        in rebuilt["evidence_bindings"]["canary-input-evidence"]["source_hashes"]
    )
    human_gates = [
        gate
        for gate in rebuilt["protocol_gates"].values()
        if gate["evidence_kind"] == "human"
    ]
    assert human_gates
    assert all(
        gate["approval_receipt"]["signature_authority"]["public_key_sha256"]
        for gate in human_gates
    )
    expected_execution_kinds = {
        binding["node_id"]: binding["execution_kind"]
        for binding in rebuilt["task"]["compiled_protocol"]["role_bindings"]
    }
    assert {
        attempt["work_item_id"]: attempt["execution_contract"]["executor_type"]
        for attempt in rebuilt["attempts"].values()
    } == expected_execution_kinds
    assert all(
        str(source_hash).startswith("source-") or len(str(source_hash)) == 64
        for source_hash in rebuilt["evidence_bindings"]["canary-input-evidence"][
            "source_hashes"
        ].values()
    )

    selected = rebuilt["selected_artifact_version"]
    unapproved = copy.deepcopy(rebuilt)
    unapproved_version = f"{selected}-unapproved"
    unapproved["artifacts"][unapproved_version] = copy.deepcopy(
        rebuilt["artifacts"][selected]
    )
    unapproved["artifacts"][unapproved_version]["version_id"] = unapproved_version
    unapproved["selected_artifact_version"] = unapproved_version
    with pytest.raises(InvalidTransition, match="not bound to approval gates"):
        TaskRuntime(tmp_path, project=first["project"])._validate_protocol_completion(
            unapproved
        )


def test_protocol_canary_rejects_non_positive_iterations(tmp_path: Path) -> None:
    try:
        run_protocol_canaries(ROOT, state_root=tmp_path, iterations=0)
    except ValueError as exc:
        assert str(exc) == "canary iterations must be positive"
    else:
        raise AssertionError("expected invalid iteration count to fail")


def test_isolated_novel_canary_example_compiles() -> None:
    task = yaml.safe_load(
        (ROOT / "examples" / "novel_canary" / "task_facts.yml").read_text(
            encoding="utf-8"
        )
    )
    story = yaml.safe_load(
        (ROOT / task["source_story_bible"]).read_text(encoding="utf-8")
    )

    assert task["protocol_ref"] == "narrative.chapter.v1"
    assert story["isolation"] == "new_world_no_existing_canon"
    assert story["chapter_one"]["irreversible_change"]
