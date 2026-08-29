from __future__ import annotations

from pathlib import Path
import hashlib

import pytest
import yaml

from agent_runtime.narrative.metric_universe import (
    TOOL_ID,
    metric_universe_issues,
    project_metric_universe,
)


def _subject(path: Path, *, project: str, suffix: str = "001") -> dict[str, str]:
    runtime_binding = {
        "task_id": f"task_metric_subject_{suffix}",
        "attempt_id": f"attempt_metric_subject_{suffix}",
        "work_item_id": f"work-metric-subject-{suffix}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-hard-continuity-audit/v1",
                "project": project,
                "status": "pass",
                "blocking_findings": [],
                "runtime_binding": runtime_binding,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return runtime_binding


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    subject_path: Path,
    runtime_binding: dict[str, str],
) -> None:
    task_id = runtime_binding["task_id"]
    attempt_id = runtime_binding["attempt_id"]
    work_item_id = runtime_binding["work_item_id"]
    output_sha256 = hashlib.sha256(subject_path.read_bytes()).hexdigest()
    projection = {
        "work_items": {
            work_item_id: {
                "work_item_id": work_item_id,
                "kind": "narrative-hard-continuity-audit",
                "assigned_agent_id": "canon_timeline_steward",
            }
        },
        "attempts": {
            attempt_id: {
                "attempt_id": attempt_id,
                "work_item_id": work_item_id,
                "status": "succeeded",
                "execution_contract": {"role": "Reviewer"},
            }
        },
    }
    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.list_tasks",
        lambda _self, include_legacy=False: [{"task_id": task_id}],
    )
    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.load_task",
        lambda _self, selected_task_id: (
            projection
            if selected_task_id == task_id
            else (_ for _ in ()).throw(KeyError(selected_task_id))
        ),
    )
    monkeypatch.setattr(
        "agent_runtime.task_runtime_v2.TaskRuntime.verify_attempt_execution_receipt",
        lambda _self, selected_task_id, selected_attempt_id: {
            "ok": True,
            "task_id": selected_task_id,
            "attempt_id": selected_attempt_id,
            "output_sha256": output_sha256,
        },
    )


def test_metric_universe_projector_binds_complete_authority_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agentlab"
    project = "Crown_of_Ash"
    project_root = root / "projects" / project
    subject_root = (
        project_root
        / "acceptance"
        / "metric-subjects"
        / "hard_continuity_errors"
    )
    subject_path = subject_root / "001.yml"
    runtime_binding = _subject(subject_path, project=project)
    _patch_runtime(
        monkeypatch,
        subject_path=subject_path,
        runtime_binding=runtime_binding,
    )

    result = project_metric_universe(
        root,
        project=project,
        task_id="task_p5_metric_universe",
        attempt_id="attempt_p5_metric_universe",
        metric_id="hard_continuity_errors",
    )
    artifact_path = project_root / result["artifact"]["path"]
    document = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))

    assert document["producer"]["tool_id"] == TOOL_ID
    assert document["producer"]["input_count"] == 1
    assert metric_universe_issues(project_root, document) == []

    _subject(subject_root / "002.yml", project=project, suffix="002")
    assert metric_universe_issues(project_root, document) == [
        "projector_input_invalid"
    ]


def test_metric_universe_rejects_forged_projector_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agentlab"
    project = "Crown_of_Ash"
    project_root = root / "projects" / project
    subject_path = (
        project_root
        / "acceptance"
        / "metric-subjects"
        / "hard_continuity_errors"
        / "001.yml"
    )
    runtime_binding = _subject(
        subject_path,
        project=project,
    )
    _patch_runtime(
        monkeypatch,
        subject_path=subject_path,
        runtime_binding=runtime_binding,
    )
    result = project_metric_universe(
        root,
        project=project,
        task_id="task_p5_metric_universe",
        attempt_id="attempt_p5_metric_universe",
        metric_id="hard_continuity_errors",
    )
    document = yaml.safe_load(
        (project_root / result["artifact"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    document["producer"]["tool_id"] = "untrusted.projector"

    assert metric_universe_issues(project_root, document) == [
        "projector_identity_invalid"
    ]


def test_metric_universe_rejects_self_report_without_runtime_attempt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentlab"
    project = "Crown_of_Ash"
    project_root = root / "projects" / project
    _subject(
        project_root
        / "acceptance"
        / "metric-subjects"
        / "hard_continuity_errors"
        / "001.yml",
        project=project,
    )

    with pytest.raises(
        ValueError,
        match="does not match successful runtime attempts",
    ):
        project_metric_universe(
            root,
            project=project,
            task_id="task_p5_metric_universe",
            attempt_id="attempt_p5_metric_universe",
            metric_id="hard_continuity_errors",
        )


def test_metric_universe_rejects_symlinked_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agentlab"
    project = "Crown_of_Ash"
    project_root = root / "projects" / project
    subject_root = (
        project_root
        / "acceptance"
        / "metric-subjects"
        / "hard_continuity_errors"
    )
    subject_path = subject_root / "001.yml"
    runtime_binding = _subject(subject_path, project=project)
    _patch_runtime(
        monkeypatch,
        subject_path=subject_path,
        runtime_binding=runtime_binding,
    )
    outside = tmp_path / "outside"
    _subject(outside / "hidden.yml", project=project, suffix="hidden")
    (subject_root / "linked-authority").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="may not use symlinks"):
        project_metric_universe(
            root,
            project=project,
            task_id="task_p5_metric_universe",
            attempt_id="attempt_p5_metric_universe",
            metric_id="hard_continuity_errors",
        )
