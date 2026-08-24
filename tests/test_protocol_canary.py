from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.protocol_canary import run_protocol_canaries
from agent_runtime.task_runtime_v2 import TaskRuntime


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
    assert all(run["accepted_work_items"] == run["work_item_count"] for run in report["runs"])

    first = report["runs"][0]
    rebuilt = TaskRuntime(tmp_path, project=first["project"]).rebuild_task(
        first["task_id"]
    )
    assert rebuilt["last_event_hash"] == first["last_event_hash"]


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
