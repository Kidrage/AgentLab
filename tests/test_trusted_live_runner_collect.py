from __future__ import annotations

import importlib
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.run_task import app
from agent_runtime.trusted_live_runner_collect import (
    build_trusted_live_runner_collect,
    selected_collect_path,
    write_trusted_live_runner_collect,
)


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _reason_set(values: list[str]) -> frozenset[str]:
    return frozenset(str(value) for value in values)


def test_selected_collect_path_is_separate_from_canonical() -> None:
    canonical = Path("acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect.yml")

    assert selected_collect_path(canonical, "run_crown_internal_writer_eval").name == (
        "trusted_live_runner_collect_writer.yml"
    )
    assert selected_collect_path(canonical, "run_crown_internal_media_smoke").name == (
        "trusted_live_runner_collect_media.yml"
    )


def test_selected_collect_metadata_accepts_canonical_top_level_summary() -> None:
    from agent_runtime.audit_helpers import selected_collect_metadata_by_item

    metadata = selected_collect_metadata_by_item(
        {
            "selected_item_report_paths": {
                "run_crown_internal_writer_eval": "trusted_live_runner_collect_writer.yml"
            },
            "selected_item_id": "run_crown_internal_writer_eval",
            "selected_item_collect_status": "pending_selected_item",
            "selected_item_status": "pending",
            "selected_item_accepted": False,
        }
    )

    assert metadata["run_crown_internal_writer_eval"] == {
        "selected_collect_report_path": "trusted_live_runner_collect_writer.yml",
        "selected_item_collect_status": "pending_selected_item",
        "selected_item_status": "pending",
        "selected_item_accepted": False,
    }


def test_trusted_live_runner_collect_refreshes_status_and_acceptance_reports(
    private_crown_project_root: Path,
) -> None:
    report = build_trusted_live_runner_collect(private_crown_project_root)

    assert report["report_type"] == "agentlab_trusted_live_runner_collect"
    assert report["status"] in {"pending_returned_artifacts", "pass", "artifact_qc_failed"}
    assert report["status"] == "pending_returned_artifacts"
    assert report["trusted_live_runner_status"]["status"] == "pending"
    assert report["trusted_live_runner_status"]["pending_item_count"] >= 1
    assert report["trusted_live_runner_status"]["stale_item_count"] >= 0
    pending_by_id = {item["id"]: item for item in report["pending_items"]}
    if "run_crown_internal_writer_eval" not in pending_by_id:
        assert pending_by_id["run_crown_internal_media_smoke"][
            "returned_candidate_artifacts_accepted"
        ] is False
        assert report["returned_candidate_artifacts_accepted_count"] == 1
        assert report["required_files_missing_count"] == 3
        assert report["acceptance_summary"]["objective_status"] == "complete"
        assert report["acceptance_summary"]["goal_status"] == "complete"
        assert report["active_selected_item_ids"] == [
            "run_crown_internal_writer_eval"
        ]
        assert report["deferred_selected_item_ids"] == [
            "run_crown_internal_media_smoke"
        ]
        return
    assert pending_by_id["run_crown_internal_writer_eval"]["required_files_exist"] is False
    assert pending_by_id["run_crown_internal_writer_eval"]["returned_candidate_artifacts_accepted"] is False
    assert pending_by_id["run_crown_internal_writer_eval"]["acceptance_blocker"] == "missing_required_files"
    assert pending_by_id["run_crown_internal_media_smoke"]["returned_candidate_artifacts_accepted"] is False
    if pending_by_id["run_crown_internal_media_smoke"]["required_files_exist"]:
        assert pending_by_id["run_crown_internal_media_smoke"]["acceptance_blocker"] == "observed_execution_error_or_stale_ledger"
        assert "observed_execution_error_or_stale_ledger" in report["acceptance_blockers"]
        assert report["required_files_missing_count"] == 7
    else:
        assert pending_by_id["run_crown_internal_media_smoke"]["acceptance_blocker"] == "missing_required_files"
        assert report["acceptance_blockers"] == ["missing_required_files"]
        assert report["required_files_missing_count"] == 10
    assert _reason_set(report["acceptance_blocker_reasons"]) in {
        frozenset({"missing_candidate_artifacts"}),
        frozenset({
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "media_live_artifacts_not_rerun_after_grok_session_pass",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "agy_session_health_blocked_before_private_writer_smoke",
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
        }),
    }
    assert report["returned_candidate_artifacts_accepted_count"] == 0
    assert report["operator_handoff_status"] in {"ready_for_trusted_runner", "needs_attention"}
    assert report["acceptance_summary"]["capability_overall_status"] == "candidate"
    assert report["acceptance_summary"]["objective_status"] == "partial"
    assert report["acceptance_summary"]["goal_status"] == "partial"
    assert report["acceptance_summary"]["acceptance_report_hygiene_status"] == "pass"
    assert report["acceptance_summary"]["acceptance_report_hygiene_canonical_text_artifact_count"] == 2
    assert report["acceptance_summary"]["acceptance_report_hygiene_canonical_text_issue_count"] == 0
    assert (
        report["acceptance_summary"][
            "acceptance_report_hygiene_stale_private_selected_command_hit_count"
        ]
        == 0
    )
    assert "trusted_live_runner_status" in report["refreshed_reports"]
    assert "trusted_live_runner_operator_handoff" in report["refreshed_reports"]
    assert "live_unblock_plan" in report["refreshed_reports"]
    assert "capability_acceptance" in report["refreshed_reports"]
    assert "objective_requirement_audit" in report["refreshed_reports"]
    assert "goal_completion_audit" in report["refreshed_reports"]
    assert "acceptance_report_hygiene" in report["refreshed_reports"]
    assert report["next_action"] == "run_writer_selected_item_only"
    assert report["active_selected_item_ids"] == ["run_crown_internal_writer_eval"]
    assert report["deferred_selected_item_ids"] == ["run_crown_internal_media_smoke"]
    assert "--only run_crown_internal_writer_eval" in report["recommended_selected_command"]
    assert report["secret_values_rendered"] is False
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_trusted_live_runner_collect_cli_writes_yaml(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "trusted_live_runner_collect.yml"

    result = runner.invoke(app, ["trusted-live-runner-collect", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_trusted_live_runner_collect"
    assert report["status"] == "pending_returned_artifacts"


def test_trusted_live_runner_collect_cli_writes_selected_item_summary(
    tmp_path: Path,
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = tmp_path / "trusted_live_runner_collect_writer.yml"

    result = runner.invoke(
        app,
        [
            "trusted-live-runner-collect",
            "--out",
            str(out),
            "--item",
            "run_crown_internal_writer_eval",
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["selected_item_id"] == "run_crown_internal_writer_eval"
    assert report["selected_item_collect_status"] == "pass"
    assert report["selected_item_status"] == "pass"
    assert report["selected_item_accepted"] is True
    assert report["selected_item_acceptance_blocker"] == "none"


def test_trusted_live_runner_collect_selected_pass_can_coexist_with_global_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    acceptance_dir = tmp_path.joinpath(
        "acceptance_runs", "agentlab_capability_acceptance"
    )
    acceptance_dir.mkdir(parents=True)
    acceptance_dir.joinpath("goal_acceptance_scope.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "scope_id": "writer_full_media_readiness",
                "status": "active",
                "acceptance_modes": {
                    "code_project": "full_acceptance",
                    "longform_narrative": "full_live_acceptance",
                    "production_pack_synthesis": "deterministic_scaffold_only",
                    "media_generation": "readiness_only",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    status_mod = importlib.import_module("trusted_live_runner_status")
    operator_mod = importlib.import_module("trusted_live_runner_operator_handoff")
    capability_mod = importlib.import_module("capability_acceptance")
    objective_mod = importlib.import_module("objective_requirement_audit")
    goal_mod = importlib.import_module("goal_completion_audit")

    def fake_status(root: Path, out: Path, request_path: Path | None = None) -> dict:
        return {
            "status": "pending",
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "expected_type": "narrative_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "expected_type": "media_live_smoke",
                    "status": "pending",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": False,
                    "acceptance_blocker": "observed_execution_error_or_stale_ledger",
                    "pending_reason": "grok_cli_transport_or_proxy_failed_in_live_smoke",
                    "next_action": "rerun_media_smoke_from_trusted_runtime",
                },
            ],
            "stale_items": [],
            "artifact_qc_failures": [],
        }

    monkeypatch.setattr(status_mod, "write_trusted_live_runner_status", fake_status)
    monkeypatch.setattr(
        operator_mod,
        "write_trusted_live_runner_operator_handoff",
        lambda root, out, request_path=None: {"status": "ready_for_trusted_runner"},
    )
    monkeypatch.setattr(
        capability_mod,
        "build_capability_acceptance_report",
        lambda root: {"overall_status": "candidate", "status_counts": {}},
    )
    monkeypatch.setattr(
        objective_mod,
        "write_objective_requirement_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )
    monkeypatch.setattr(
        goal_mod,
        "write_goal_completion_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )

    report = build_trusted_live_runner_collect(
        tmp_path,
        item_id="run_crown_internal_writer_eval",
    )

    assert report["status"] == "pending_returned_artifacts"
    assert report["trusted_live_runner_status"]["status"] == "pending"
    assert report["pending_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "expected_type": "media_live_smoke",
            "pending_reason": "grok_cli_transport_or_proxy_failed_in_live_smoke",
            "next_action": "rerun_media_smoke_from_trusted_runtime",
            "missing": [],
            "required_files_exist": True,
            "returned_candidate_artifacts_accepted": False,
            "acceptance_blocker": "observed_execution_error_or_stale_ledger",
        }
    ]
    assert report["selected_item_id"] == "run_crown_internal_writer_eval"
    assert report["selected_item_collect_status"] == "pass"
    assert report["selected_item_status"] == "pass"
    assert report["selected_item_accepted"] is True
    assert report["selected_item_required_files_exist"] is True
    assert report["selected_item_returned_candidate_artifacts_accepted"] is True
    assert report["selected_item_acceptance_blocker"] == "none"
    assert report["next_action"] == (
        "scoped_acceptance_complete_deferred_media_pending"
    )


def test_trusted_live_runner_collect_passes_after_all_returned_artifacts_are_accepted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tmp_path.joinpath("acceptance_runs", "agentlab_capability_acceptance").mkdir(parents=True)
    status_mod = importlib.import_module("trusted_live_runner_status")
    operator_mod = importlib.import_module("trusted_live_runner_operator_handoff")
    capability_mod = importlib.import_module("capability_acceptance")
    objective_mod = importlib.import_module("objective_requirement_audit")
    goal_mod = importlib.import_module("goal_completion_audit")

    def fake_status(root: Path, out: Path, request_path: Path | None = None) -> dict:
        return {
            "status": "pass",
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "expected_type": "narrative_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "expected_type": "media_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
            ],
            "stale_items": [],
            "artifact_qc_failures": [],
        }

    monkeypatch.setattr(status_mod, "write_trusted_live_runner_status", fake_status)
    monkeypatch.setattr(
        operator_mod,
        "write_trusted_live_runner_operator_handoff",
        lambda root, out, request_path=None: {"status": "ready_for_trusted_runner"},
    )
    monkeypatch.setattr(
        capability_mod,
        "build_capability_acceptance_report",
        lambda root: {"overall_status": "candidate", "status_counts": {}},
    )
    monkeypatch.setattr(
        objective_mod,
        "write_objective_requirement_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )
    monkeypatch.setattr(
        goal_mod,
        "write_goal_completion_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )

    report = build_trusted_live_runner_collect(tmp_path)

    assert report["status"] == "pass"
    assert report["trusted_live_runner_status"] == {
        "status": "pass",
        "pending_item_count": 0,
        "stale_item_count": 0,
        "artifact_qc_failure_count": 0,
    }
    assert report["acceptance_blockers"] == []
    assert report["acceptance_blocker_reasons"] == []
    assert report["pending_items"] == []
    assert report["required_files_missing_count"] == 0
    assert report["returned_candidate_artifacts_accepted_count"] == 2
    assert report["next_action"] == "refresh_promotion_or_human_acceptance_gate"
    assert report["selected_item_summaries"]["run_crown_internal_writer_eval"][
        "selected_item_collect_status"
    ] == "pass"
    assert report["selected_item_summaries"]["run_crown_internal_media_smoke"][
        "selected_item_accepted"
    ] is True


def test_trusted_live_runner_collect_rejects_pass_status_without_returned_acceptance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tmp_path.joinpath("acceptance_runs", "agentlab_capability_acceptance").mkdir(parents=True)
    status_mod = importlib.import_module("trusted_live_runner_status")
    operator_mod = importlib.import_module("trusted_live_runner_operator_handoff")
    capability_mod = importlib.import_module("capability_acceptance")
    objective_mod = importlib.import_module("objective_requirement_audit")
    goal_mod = importlib.import_module("goal_completion_audit")

    def fake_status(root: Path, out: Path, request_path: Path | None = None) -> dict:
        return {
            "status": "pass",
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "expected_type": "narrative_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "expected_type": "media_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": False,
                    "acceptance_blocker": "none",
                },
            ],
            "stale_items": [],
            "artifact_qc_failures": [],
        }

    monkeypatch.setattr(status_mod, "write_trusted_live_runner_status", fake_status)
    monkeypatch.setattr(
        operator_mod,
        "write_trusted_live_runner_operator_handoff",
        lambda root, out, request_path=None: {"status": "ready_for_trusted_runner"},
    )
    monkeypatch.setattr(
        capability_mod,
        "build_capability_acceptance_report",
        lambda root: {"overall_status": "candidate", "status_counts": {}},
    )
    monkeypatch.setattr(
        objective_mod,
        "write_objective_requirement_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )
    monkeypatch.setattr(
        goal_mod,
        "write_goal_completion_audit",
        lambda root, out: {"status": "partial", "status_counts": {}},
    )

    report = build_trusted_live_runner_collect(
        tmp_path,
        item_id="run_crown_internal_media_smoke",
    )

    assert report["status"] == "fail"
    assert report["next_action"] == "repair_trusted_live_runner_status_or_rerun_collect"
    assert report["trusted_live_runner_status"]["status"] == "pass"
    assert report["acceptance_blockers"] == ["returned_artifacts_not_accepted"]
    assert report["acceptance_blocker_reasons"] == [
        "status_pass_but_returned_artifacts_not_accepted"
    ]
    assert report["inconsistent_pass_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "status": "pass",
            "returned_candidate_artifacts_accepted": False,
            "acceptance_blocker": "returned_artifacts_not_accepted",
        }
    ]
    assert report["selected_item_status"] == "pass"
    assert report["selected_item_collect_status"] == "pending_selected_item"
    assert report["selected_item_accepted"] is False
    assert report["selected_item_returned_candidate_artifacts_accepted"] is False
    assert report["selected_item_acceptance_blocker"] == "returned_artifacts_not_accepted"
    assert report["selected_item_pending_reason"] == "status_pass_but_returned_artifacts_not_accepted"
    assert report["selected_item_next_action"] == "repair_trusted_live_runner_status_or_rerun_collect"


def test_canonical_collect_write_rewrites_acceptance_summary_after_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    base.mkdir(parents=True)
    out = base / "trusted_live_runner_collect.yml"
    status_mod = importlib.import_module("trusted_live_runner_status")
    operator_mod = importlib.import_module("trusted_live_runner_operator_handoff")
    capability_mod = importlib.import_module("capability_acceptance")
    objective_mod = importlib.import_module("objective_requirement_audit")
    goal_mod = importlib.import_module("goal_completion_audit")
    live_unblock_mod = importlib.import_module("live_unblock_plan")
    hygiene_mod = importlib.import_module("acceptance_report_hygiene")

    def collect_exists(root: Path) -> bool:
        return (
            root
            / "acceptance_runs"
            / "agentlab_capability_acceptance"
            / "trusted_live_runner_collect.yml"
        ).exists()

    def fake_status(root: Path, out: Path, request_path: Path | None = None) -> dict:
        return {
            "status": "pass",
            "items": [
                {
                    "id": "run_crown_internal_writer_eval",
                    "expected_type": "narrative_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
                {
                    "id": "run_crown_internal_media_smoke",
                    "expected_type": "media_live_smoke",
                    "status": "pass",
                    "missing": [],
                    "required_files_exist": True,
                    "returned_candidate_artifacts_accepted": True,
                    "acceptance_blocker": "none",
                },
            ],
            "stale_items": [],
            "artifact_qc_failures": [],
        }

    def fake_capability(root: Path) -> dict:
        if collect_exists(root):
            return {"overall_status": "pass", "status_counts": {"pass": 26}, "capabilities": []}
        return {"overall_status": "candidate", "status_counts": {"candidate": 1}, "capabilities": []}

    def fake_objective(root: Path, out: Path) -> dict:
        status = "complete" if collect_exists(root) else "partial"
        report = {"status": status, "status_counts": {"pass": 10} if status == "complete" else {"candidate": 2}}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return report

    def fake_goal(root: Path, out: Path) -> dict:
        status = "complete" if collect_exists(root) else "partial"
        report = {"status": status, "status_counts": {"pass": 7} if status == "complete" else {"candidate": 2}}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return report

    def fake_hygiene(root: Path, out: Path) -> dict:
        report = {
            "status": "pass",
            "canonical_text_artifact_count": 0,
            "canonical_text_issues": [],
            "stale_private_selected_command_hits": [],
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return report

    monkeypatch.setattr(status_mod, "write_trusted_live_runner_status", fake_status)
    monkeypatch.setattr(
        operator_mod,
        "write_trusted_live_runner_operator_handoff",
        lambda root, out, request_path=None: {"status": "ready_for_trusted_runner"},
    )
    monkeypatch.setattr(capability_mod, "build_capability_acceptance_report", fake_capability)
    monkeypatch.setattr(objective_mod, "write_objective_requirement_audit", fake_objective)
    monkeypatch.setattr(goal_mod, "write_goal_completion_audit", fake_goal)
    monkeypatch.setattr(live_unblock_mod, "build_live_unblock_plan", lambda root: {"status": "pass"})
    monkeypatch.setattr(hygiene_mod, "sync_snapshot_aliases", lambda base: None)
    monkeypatch.setattr(hygiene_mod, "write_acceptance_report_hygiene", fake_hygiene)

    report = write_trusted_live_runner_collect(tmp_path, out)
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    writer_collect = yaml.safe_load(
        out.with_name("trusted_live_runner_collect_writer.yml").read_text(encoding="utf-8")
    )

    for result in [report, written, writer_collect]:
        assert result["status"] == "pass"
        assert result["acceptance_summary"]["capability_overall_status"] == "pass"
        assert result["acceptance_summary"]["capability_status_counts"] == {"pass": 26}
        assert result["acceptance_summary"]["objective_status"] == "complete"
        assert result["acceptance_summary"]["goal_status"] == "complete"


def test_canonical_collect_write_refreshes_current_from_fresh_collect(
    private_crown_project_root: Path,
) -> None:
    del private_crown_project_root
    out = ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "trusted_live_runner_collect.yml"

    write_trusted_live_runner_collect(ROOT, out)

    collect = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert collect["selected_item_report_paths"] == {
        "run_crown_internal_writer_eval": (
            "acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect_writer.yml"
        ),
        "run_crown_internal_media_smoke": (
            "acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect_media.yml"
        ),
    }
    assert collect["selected_item_summaries"]["run_crown_internal_writer_eval"][
        "selected_item_id"
    ] == "run_crown_internal_writer_eval"
    assert collect["selected_item_summaries"]["run_crown_internal_media_smoke"][
        "selected_item_id"
    ] == "run_crown_internal_media_smoke"
    writer_collect = yaml.safe_load(
        out.with_name("trusted_live_runner_collect_writer.yml").read_text(encoding="utf-8")
    )
    media_collect = yaml.safe_load(
        out.with_name("trusted_live_runner_collect_media.yml").read_text(encoding="utf-8")
    )
    assert writer_collect["selected_item_report_source"].endswith("trusted_live_runner_collect.yml")
    assert writer_collect["selected_item_id"] == "run_crown_internal_writer_eval"
    assert "selected_item_summaries" not in writer_collect
    assert media_collect["selected_item_report_source"].endswith("trusted_live_runner_collect.yml")
    assert media_collect["selected_item_id"] == "run_crown_internal_media_smoke"
    assert "selected_item_summaries" not in media_collect

    current = yaml.safe_load(
        (ROOT / "acceptance_runs" / "agentlab_capability_acceptance" / "current.yml").read_text(
            encoding="utf-8"
        )
    )
    by_id = {item["id"]: item for item in current["capabilities"]}
    unblock_items = {
        item["id"]: item
        for item in by_id["internal_live_unblock_plan"]["details"]["items"]
    }
    media_return = unblock_items["run_crown_internal_media_smoke"]["current_return"]
    assert media_return["pending_reason"] in {
        "missing_candidate_artifacts",
        "media_live_artifacts_not_rerun_after_grok_session_pass",
    }
    if media_return["pending_reason"] == "missing_candidate_artifacts":
        assert media_return["next_action"] == "run_trusted_live_command_and_collect_required_artifacts"
    else:
        assert media_return["next_action"] == "rerun_trusted_media_smoke_with_current_grok_session"
    details = by_id["trusted_live_runner_collect"]["details"]
    assert _reason_set(details["acceptance_blocker_reasons"]) in {
        frozenset({"missing_candidate_artifacts"}),
        frozenset({
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "media_live_artifacts_not_rerun_after_grok_session_pass",
            "missing_candidate_artifacts",
        }),
        frozenset({
            "agy_session_health_blocked_before_private_writer_smoke",
            "grok_cli_transport_or_proxy_failed_in_live_smoke",
        }),
    }
    assert details["required_files_missing_count"] in {3, 5, 7, 10}
    assert details["returned_candidate_artifacts_accepted_count"] in {0, 1}
    assert details["acceptance_report_hygiene_canonical_text_artifact_count"] == 2
    assert details["acceptance_report_hygiene_canonical_text_issue_count"] == 0
    assert details["acceptance_report_hygiene_stale_private_selected_command_hit_count"] == 0
    hygiene = yaml.safe_load(
        (
            ROOT
            / "acceptance_runs"
            / "agentlab_capability_acceptance"
            / "acceptance_report_hygiene.yml"
        ).read_text(encoding="utf-8")
    )
    assert hygiene["status"] == "pass"
    assert hygiene["stale_snapshot_count"] == 0
    assert details["acceptance_report_hygiene_canonical_text_artifact_count"] == hygiene[
        "canonical_text_artifact_count"
    ]
    assert details["acceptance_report_hygiene_canonical_text_issue_count"] == len(
        hygiene["canonical_text_issues"]
    )
    assert details["acceptance_report_hygiene_stale_private_selected_command_hit_count"] == len(
        hygiene["stale_private_selected_command_hits"]
    )
