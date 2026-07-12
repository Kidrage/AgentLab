from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.acceptance_report_hygiene import (
    _canonical_text_forbidden_hits,
    _private_selected_command_hits,
    _request_session_health_warning_issues,
    build_acceptance_report_hygiene,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_acceptance_report_hygiene_passes_for_current_canonical_reports() -> None:
    report = build_acceptance_report_hygiene(ROOT)

    assert report["report_type"] == "agentlab_acceptance_report_hygiene"
    assert report["status"] == "pass"
    assert report["canonical_issues"] == []
    assert report["canonical_text_issues"] == []
    assert report["stale_snapshots"] == []
    assert report["stale_marker_hits"] == []
    assert report["stale_private_selected_command_hits"] == []
    assert report["consistency_issues"] == []
    assert "live_unblock_plan.yml" in report["private_selected_command_scan_artifacts"]
    assert report["non_authoritative_snapshot_count"] > 0
    assert "grok_media_preflight_current.yml" in report["non_authoritative_snapshots"]
    assert "provider_smoke_current.yml" in report["non_authoritative_snapshots"]
    assert "current_now.yml" not in report["non_authoritative_snapshots"]
    assert "objective_requirement_audit_check.yml" not in report["non_authoritative_snapshots"]

    canonical_by_name = {
        Path(item["path"]).name: item for item in report["canonical_reports"]
    }
    assert canonical_by_name["current.yml"]["actual_report_type"] == "agentlab_capability_acceptance"
    assert (
        canonical_by_name["trusted_live_runner_collect.yml"]["actual_report_type"]
        == "agentlab_trusted_live_runner_collect"
    )
    canonical_text_by_name = {
        Path(item["path"]).name: item for item in report["canonical_text_artifacts"]
    }
    assert canonical_text_by_name["role_session_acceptance_handoff.md"]["missing_markers"] == []
    assert canonical_text_by_name["private_live_smoke_approval_handoff.md"]["missing_markers"] == []
    assert canonical_text_by_name["role_session_acceptance_handoff.md"]["forbidden_marker_hits"] == []
    assert canonical_text_by_name["private_live_smoke_approval_handoff.md"]["forbidden_marker_hits"] == []


def test_acceptance_report_hygiene_flags_stale_role_session_handoff_text() -> None:
    hits = _canonical_text_forbidden_hits(
        "Paste this approval before asking Codex to run the private role-session acceptance smoke\n"
        "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current_writer/fiction_draft.md\n"
        "projects/Crown_of_Ash/runs/task_probe/artifacts/media_backend_live_internal_current_media/generation_ledger.yml\n",
        [
            "Paste this approval before asking Codex to run the private role-session acceptance smoke",
            "task_narrative_eval_ch01_current_writer",
            "media_backend_live_internal_current_media",
        ],
    )

    assert hits == [
        "Paste this approval before asking Codex to run the private role-session acceptance smoke",
        "task_narrative_eval_ch01_current_writer",
        "media_backend_live_internal_current_media",
    ]


def test_acceptance_report_hygiene_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "acceptance_report_hygiene.yml"

    result = runner.invoke(app, ["acceptance-report-hygiene", "--out", str(out)])

    assert result.exit_code == 0, result.output
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_acceptance_report_hygiene"
    assert report["status"] == "pass"
    assert report["canonical_text_artifact_count"] >= 2
    assert report["stale_snapshot_count"] == 0
    assert report["stale_private_selected_command_hits"] == []
    assert report["consistency_issues"] == []


def test_acceptance_report_hygiene_flags_selected_private_commands_without_approval_env(
    tmp_path: Path,
) -> None:
    (tmp_path / "live_unblock_plan.yml").write_text(
        "trusted_runner_command: AGENTLAB_TRUSTED_LIVE_RUNNER=1\n"
        "  acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.sh\n"
        "  --only run_crown_internal_writer_eval\n",
        encoding="utf-8",
    )

    hits = _private_selected_command_hits(tmp_path)

    assert hits == [
        {
            "path": "live_unblock_plan.yml",
            "line": 2,
            "item": "run_crown_internal_writer_eval",
            "reason": "selected_private_role_session_command_missing_approval_env",
            "required_env": "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1",
        }
    ]


def test_acceptance_report_hygiene_flags_stale_request_session_health_warnings(
    tmp_path: Path,
) -> None:
    base = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    base.mkdir(parents=True)
    (base / "internal_live_readiness.yml").write_text(
        yaml.safe_dump(
            {
                "report_type": "agentlab_internal_live_readiness",
                "status": "ready_for_internal_live_smoke",
                "session_health_issues": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "trusted_live_runner_request.yml").write_text(
        yaml.safe_dump(
            {
                "report_type": "agentlab_trusted_live_runner_request",
                "session_health_warnings": [
                    {"id": "current_grok_session_health", "status": "blocked"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    issues = _request_session_health_warning_issues(base)

    assert issues == [
        {
            "path": "acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.yml",
            "reason": "session_health_warnings_do_not_match_current_readiness",
            "readiness_path": "acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml",
            "current_readiness_issue_ids": [],
            "request_warning_ids": ["current_grok_session_health"],
        }
    ]
