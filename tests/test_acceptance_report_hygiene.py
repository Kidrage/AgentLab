from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.acceptance_report_hygiene import (
    _canonical_text_forbidden_hits,
    _private_selected_command_hits,
    build_acceptance_report_hygiene,
)
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_acceptance_report_hygiene_passes_for_current_canonical_reports() -> None:
    # Read-only against the repository acceptance area; never rewrites current.yml
    # or the evidence chain from tests.
    report = build_acceptance_report_hygiene(ROOT)

    assert report["report_type"] == "agentlab_acceptance_report_hygiene"
    assert report["status"] == "pass"
    assert report["canonical_issues"] == []
    assert report["canonical_text_issues"] == []
    assert report["stale_snapshots"] == []
    assert report["stale_marker_hits"] == []
    assert report["stale_private_selected_command_hits"] == []
    assert report["consistency_issues"] == []
    assert report["capability_current_evidence_chain"]["verification_status"] == "pass"
    assert report["capability_current_evidence_chain"]["issue_count"] == 0
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
        canonical_by_name["current_evidence_chain.yml"]["actual_report_type"]
        == "agentlab_capability_current_evidence_chain"
    )
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
    assert report["capability_current_evidence_chain"]["verification_status"] == "pass"


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


def test_acceptance_report_hygiene_flags_historical_paths_in_active_evidence(
    tmp_path: Path,
) -> None:
    """Isolated fixture: canonical acceptance claiming archive paths as current fails."""
    from agent_runtime.acceptance_report_hygiene import CANONICAL_REPORT_TYPES
    from agent_runtime.capability_evidence_chain import (
        CHAIN_FILENAME,
        REPORT_TYPE,
        compute_aggregate_digest,
        sha256_file,
    )

    root = tmp_path
    base = root / "acceptance_runs" / "agentlab_capability_acceptance"
    base.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "run_retention_policy.yml").write_text(
        "schema_version: 1\narchive_root: archive/run_history\n",
        encoding="utf-8",
    )
    (root / "config" / "content_project_governance.yml").write_text(
        "schema_version: 1\narchive_roots: [archive, _archive]\n",
        encoding="utf-8",
    )

    active = root / "agent_runtime" / "ok.py"
    active.parent.mkdir(parents=True)
    active.write_text("ok\n", encoding="utf-8")
    historical = (
        "projects/AgentLab/archive/run_history/pruning/runs/task_x/workflow_plan.yml"
    )
    hist_path = root / historical
    hist_path.parent.mkdir(parents=True)
    hist_path.write_text("old\n", encoding="utf-8")

    current = {
        "schema_version": 1,
        "report_type": "agentlab_capability_acceptance",
        "overall_status": "pass",
        "capabilities": [
            {
                "id": "demo",
                "title": "Demo",
                "status": "pass",
                "evidence": [historical],  # illegal as current
                "issues": [],
            }
        ],
    }
    current_path = base / "current.yml"
    current_path.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")

    # Minimal stubs for other canonical report types so missing does not dominate.
    for name, report_type in CANONICAL_REPORT_TYPES.items():
        if name in {"current.yml", CHAIN_FILENAME}:
            continue
        (base / name).write_text(
            yaml.safe_dump({"schema_version": 1, "report_type": report_type, "status": "pass"}),
            encoding="utf-8",
        )
    for name in (
        "role_session_acceptance_handoff.md",
        "private_live_smoke_approval_handoff.md",
    ):
        (base / name).write_text(
            "Canonical term: `private_role_session_acceptance_smoke`\n"
            "Legacy shorthand: `private live smoke`\n"
            "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1\n"
            "missing_candidate_artifacts\n"
            "ready_for_internal_live_smoke\n"
            "Legacy path:\n"
            "role_session_acceptance_handoff.md\n",
            encoding="utf-8",
        )

    # A valid-looking chain that still rebuilds from the illegal current.yml.
    chain = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "chain_id": "agentlab_capability_current",
        "source_report": {
            "path": "acceptance_runs/agentlab_capability_acceptance/current.yml",
            "report_type": "agentlab_capability_acceptance",
            "sha256": sha256_file(current_path),
            "overall_status": "pass",
        },
        "current_evidence": [],
        "historical_references": [
            {
                "path": historical,
                "class": "historical",
                "capability_ids": ["demo"],
            }
        ],
        "aggregate_digest": compute_aggregate_digest([]),
        "status": "fail",
        "issues": [],
    }
    (base / CHAIN_FILENAME).write_text(yaml.safe_dump(chain, sort_keys=False), encoding="utf-8")

    report = build_acceptance_report_hygiene(root)
    assert report["status"] == "fail"
    assert any(
        issue.get("reason")
        in {
            "historical_path_in_active_evidence",
            "source_pass_lists_historical_as_current_evidence",
            "source_pass_without_active_evidence",
            "pass_without_active_evidence",
        }
        for issue in report.get("consistency_issues") or []
    )
