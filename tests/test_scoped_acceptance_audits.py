from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import agent_runtime.goal_completion_audit as goal_module
import agent_runtime.objective_requirement_audit as objective_module
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def _persisted_writer_request_is_current(root: Path) -> bool:
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_request.yml"
    report = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    writer = next(
        (
            item
            for item in report.get("items", [])
            if isinstance(item, dict) and item.get("id") == "run_crown_internal_writer_eval"
        ),
        {},
    )
    package = report.get("local_runner_package") or {}
    return (
        writer.get("assigned_worker") == "agy"
        and "--writer-worker agy" in str(writer.get("command") or "")
        and "command -v agy" in (package.get("preflight_commands") or [])
    )


AUDITS = (
    pytest.param(
        goal_module,
        goal_module.build_goal_completion_audit,
        "agentlab_goal_completion_audit",
        "goal_items",
        8,
        "support_crown_longform_governance",
        "goal-completion-audit",
        id="goal",
    ),
    pytest.param(
        objective_module,
        objective_module.build_objective_requirement_audit,
        "agentlab_objective_requirement_audit",
        "requirements",
        11,
        "test_crown_longform_1500_chapter_governance_and_live_generation",
        "objective-requirement-audit",
        id="objective",
    ),
)


@pytest.mark.parametrize(
    ("module", "builder", "report_type", "items_key", "item_count", "crown_id", "command"),
    AUDITS,
)
def test_current_scoped_acceptance_audits_are_complete(
    private_crown_project_root: Path,
    module,
    builder,
    report_type: str,
    items_key: str,
    item_count: int,
    crown_id: str,
    command: str,
) -> None:
    del module, command
    report = builder(private_crown_project_root)
    items = {item["id"]: item for item in report[items_key]}

    assert report["report_type"] == report_type
    writer_request_current = _persisted_writer_request_is_current(private_crown_project_root)
    computed_counts: dict[str, int] = {}
    for item in items.values():
        computed_counts[item["status"]] = computed_counts.get(item["status"], 0) + 1
    assert report["status_counts"] == computed_counts
    expected_status = (
        "fail"
        if computed_counts.get("fail")
        else "partial"
        if any(computed_counts.get(status) for status in ("candidate", "warn", "blocked"))
        else "complete"
    )
    assert report["status"] == expected_status
    assert len(items) == item_count
    assert report["source_report_health"]["status"] == "pass"
    assert report["source_report_health"]["checked"] == len(report["source_reports"])
    assert report["acceptance_scope"]["valid"] is True
    assert report["acceptance_scope"]["acceptance_modes"] == {
        "code_project": "full_acceptance",
        "longform_narrative": "full_live_acceptance",
        "production_pack_synthesis": "deterministic_scaffold_only",
        "media_generation": "readiness_only",
    }
    readiness = yaml.safe_load(
        (
            private_crown_project_root
            / "acceptance_runs"
            / "agentlab_capability_acceptance"
            / "internal_live_readiness.yml"
        ).read_text(encoding="utf-8")
    ) or {}
    assert report["session_health_summary"]["status"] == readiness.get("status")
    assert report["session_health_summary"]["issue_count"] == len(
        readiness.get("session_health_issues") or []
    )
    assert {item["id"] for item in report["deferred_internal_live_smokes"]} == {
        "run_crown_internal_media_smoke"
    }
    assert report["frontdesk_runtime_boundary"]["agentlab_internal_route_blocked"] is False
    assert report["frontdesk_runtime_boundary"]["current_agentlab_execution_path_affected"] is False
    assert report["acceptance_report_hygiene_summary"]["status"] == "pass"
    assert report["role_session_execution_boundary"][
        "approval_gate_before_private_context"
    ] is True

    crown = items[crown_id]
    writer_acceptance = crown["details"]["writer_selected_acceptance"]
    assert writer_acceptance["complete"] is (
        writer_acceptance["returned_artifacts_accepted"]
        and writer_acceptance["selected_collect_accepted"]
    )
    assert crown["status"] == (
        "pass"
        if writer_acceptance["complete"]
        else "candidate"
        if writer_request_current
        else "fail"
    )
    pending_ids = {item["id"] for item in report["pending_internal_live_smokes"]}
    assert pending_ids == (
        set() if writer_acceptance["complete"] else {"run_crown_internal_writer_eval"}
    )
    assert report["active_acceptance_blockers"]["status"] == (
        "clear" if writer_acceptance["complete"] else "pending"
    )
    assert all(item["evidence_health"]["status"] == "pass" for item in items.values())
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


@pytest.mark.parametrize(
    ("module", "builder", "report_type", "items_key", "item_count", "crown_id", "command"),
    AUDITS,
)
def test_scoped_audits_reopen_when_selected_writer_acceptance_is_pending(
    private_crown_project_root: Path,
    monkeypatch,
    module,
    builder,
    report_type: str,
    items_key: str,
    item_count: int,
    crown_id: str,
    command: str,
) -> None:
    del report_type, item_count, command
    original_read_yaml = module._read_yaml

    def pending_writer_read(path: Path) -> dict:
        data = deepcopy(original_read_yaml(path))
        if path.name == "current.yml":
            for capability in data.get("capabilities", []):
                if capability.get("id") == "crown_formal_live_narrative_eval":
                    capability.update(
                        status="candidate",
                        issues=["Writer returned artifacts are pending"],
                    )
        elif path.name == "trusted_live_runner_status.yml":
            for item in data.get("items", []):
                if item.get("id") == "run_crown_internal_writer_eval":
                    item.update(
                        status="pending",
                        required_files_exist=False,
                        returned_candidate_artifacts_accepted=False,
                        acceptance_blocker="missing_required_files",
                        pending_reason="missing_candidate_artifacts",
                        missing=["fiction_draft.md"],
                    )
        elif path.name == "trusted_live_runner_collect.yml":
            summary = data.setdefault("selected_item_summaries", {}).setdefault(
                "run_crown_internal_writer_eval", {}
            )
            summary.update(
                selected_item_collect_status="pending_selected_item",
                selected_item_status="pending",
                selected_item_accepted=False,
            )
            if data.get("selected_item_id") == "run_crown_internal_writer_eval":
                data.update(
                    selected_item_collect_status="pending_selected_item",
                    selected_item_status="pending",
                    selected_item_accepted=False,
                )
        return data

    monkeypatch.setattr(module, "_read_yaml", pending_writer_read)
    report = builder(private_crown_project_root)
    items = {item["id"]: item for item in report[items_key]}

    assert report["status"] == (
        "partial"
        if _persisted_writer_request_is_current(private_crown_project_root)
        else "fail"
    )
    assert items[crown_id]["status"] in {"candidate", "warn"}
    assert {item["id"] for item in report["pending_internal_live_smokes"]} == {
        "run_crown_internal_writer_eval"
    }
    assert report["active_acceptance_blockers"]["status"] == "pending"
    assert {
        item["id"] for item in report["active_acceptance_blockers"]["current_blockers"]
    } == {"writer_missing_returned_artifacts"}
    assert {item["id"] for item in report["deferred_internal_live_smokes"]} == {
        "run_crown_internal_media_smoke"
    }


@pytest.mark.parametrize(
    ("module", "builder", "report_type", "items_key", "item_count", "crown_id", "command"),
    AUDITS,
)
def test_scoped_acceptance_audit_cli_writes_current_report(
    tmp_path: Path,
    private_crown_project_root: Path,
    module,
    builder,
    report_type: str,
    items_key: str,
    item_count: int,
    crown_id: str,
    command: str,
) -> None:
    del private_crown_project_root
    del module, builder, crown_id
    out = tmp_path / f"{command}.yml"

    result = RUNNER.invoke(app, [command, "--out", str(out)])

    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == report_type
    computed_counts: dict[str, int] = {}
    for item in report[items_key]:
        computed_counts[item["status"]] = computed_counts.get(item["status"], 0) + 1
    assert report["status_counts"] == computed_counts
    expected_status = (
        "fail"
        if computed_counts.get("fail")
        else "partial"
        if any(computed_counts.get(status) for status in ("candidate", "warn", "blocked"))
        else "complete"
    )
    assert report["status"] == expected_status
    assert result.exit_code == (1 if expected_status == "fail" else 0)
    assert len(report[items_key]) == item_count
    assert report["source_report_health"]["checked"] == len(report["source_reports"])
