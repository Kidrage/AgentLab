from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from agent_runtime.narrative_heavy_audit import (
    materialize_narrative_heavy_audit_content,
    materialize_narrative_heavy_audit_result,
    prepare_crown_narrative_heavy_audit,
)


def _block(name: str, data: dict) -> str:
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return (
        f"<!-- AGENTLAB_EDIT: {name} -->\n"
        f"{content}"
        "<!-- END AGENTLAB_EDIT -->"
    )


def test_materializes_reviewer_heavy_audit_outputs_transactionally(tmp_path: Path) -> None:
    content = "\n\n".join(
        [
            _block(
                "fiction_review.yml",
                {
                    "schema_version": 1,
                    "status": "pass",
                    "candidate_only": True,
                    "production_modified": False,
                    "chapter_range": [1, 10],
                    "findings": [],
                },
            ),
            _block(
                "continuity_failure_report.yml",
                {
                    "schema_version": 1,
                    "status": "pass",
                    "candidate_only": True,
                    "production_modified": False,
                    "chapter_range": [1, 10],
                    "blocking_issue_count": 0,
                    "failures": [],
                },
            ),
        ]
    )

    assert materialize_narrative_heavy_audit_content(
        content,
        tmp_path,
        "task_audit",
        "Reviewer",
    )
    assert (tmp_path / "fiction_review.yml").exists()
    assert (tmp_path / "continuity_failure_report.yml").exists()


def test_rejects_heavy_audit_attempt_to_replace_draft(tmp_path: Path) -> None:
    content = _block(
        "fiction_draft.md",
        {"schema_version": 1, "status": "rewritten"},
    )

    assert not materialize_narrative_heavy_audit_content(
        content,
        tmp_path,
        "task_audit",
        "Reviewer",
    )
    assert not (tmp_path / "fiction_draft.md").exists()
    contract = yaml.safe_load(
        (tmp_path / "narrative_heavy_audit_reviewer_output_contract.yml").read_text(
            encoding="utf-8"
        )
    )
    assert contract["status"] == "blocked"
    assert "unexpected_heavy_audit_output:fiction_draft.md" in contract["issues"]


def test_failed_reviewer_retry_removes_stale_materialized_outputs(tmp_path: Path) -> None:
    for name in ("fiction_review.yml", "continuity_failure_report.yml"):
        (tmp_path / name).write_text("stale: true\n", encoding="utf-8")

    result = SimpleNamespace(status="task_failed", content="")

    assert not materialize_narrative_heavy_audit_result(
        result,
        tmp_path,
        "task_audit",
        "Reviewer",
    )
    assert not (tmp_path / "fiction_review.yml").exists()
    assert not (tmp_path / "continuity_failure_report.yml").exists()


def test_invalid_heavy_audit_yaml_reports_problem_line(tmp_path: Path) -> None:
    content = """<!-- AGENTLAB_EDIT: state_transition_proposal.yml -->
schema_version: 1
status: candidate
candidate_only: true
production_modified: false
requires_user_promotion: true
events:
  - scope: candidate_only
    acceptance_criteria:
      - Add indicators (e.g., phase: recovery, vital_signs: unstable).
<!-- END AGENTLAB_EDIT -->"""

    assert not materialize_narrative_heavy_audit_content(
        content,
        tmp_path,
        "task_audit",
        "Scribe",
    )
    contract = yaml.safe_load(
        (tmp_path / "narrative_heavy_audit_scribe_output_contract.yml").read_text(
            encoding="utf-8"
        )
    )
    issue = contract["issues"][0]
    assert issue.startswith(
        "invalid_heavy_audit_yaml:state_transition_proposal.yml:line_"
    )
    assert "mapping_values_are_not_allowed_here" in issue


def test_blocking_continuity_requires_rewrite_proposal(tmp_path: Path) -> None:
    (tmp_path / "continuity_failure_report.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "blocked",
                "candidate_only": True,
                "production_modified": False,
                "blocking_issue_count": 1,
                "failures": [{"chapter": 4, "issue": "timeline contradiction"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    content = _block(
        "revision_or_rewrite_proposal.yml",
        {
            "schema_version": 1,
            "status": "not_required",
            "candidate_only": True,
            "production_modified": False,
            "rewrite_required": False,
            "direct_draft_edits": False,
            "proposals": [],
        },
    )

    assert not materialize_narrative_heavy_audit_content(
        content,
        tmp_path,
        "task_audit",
        "Verifier",
    )
    assert not (tmp_path / "revision_or_rewrite_proposal.yml").exists()
    contract = yaml.safe_load(
        (tmp_path / "narrative_heavy_audit_verifier_output_contract.yml").read_text(
            encoding="utf-8"
        )
    )
    assert "blocking_continuity_requires_rewrite_proposal" in contract["issues"]


def _write_candidate_run(root: Path, chapter: int, eval_id: str) -> None:
    run_dir = (
        root
        / "projects"
        / "Crown_of_Ash"
        / "runs"
        / f"task_narrative_eval_ch{chapter:02d}_{eval_id}"
    )
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text(
        f"写 Crown 第 {chapter} 章。",
        encoding="utf-8",
    )
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "route": {
                    "route_key": "narrative_light_chapter",
                    "agents": ["Supervisor", "Writer"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "chapter_packet.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "chapter": chapter,
                "baseline_mode": "reset" if chapter == 1 else "continuation",
                "previous_chapters": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "fiction_draft.md").write_text(
        f"# 第{chapter}章\n\n" + "正文。" * 1100,
        encoding="utf-8",
    )
    (run_dir / "continuity_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "chapter": chapter,
                "baseline_mode": "reset" if chapter == 1 else "continuation",
                "timeline": {"monotonic": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "state_transition_proposal.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "requires_user_promotion": True,
                "events": [{"scope": "candidate_only"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "narrative_delivery_receipt.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "candidate_only": True,
                "delivery_check": {"valid": True, "issues": []},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_prepares_fresh_provider_free_heavy_audit_bundle(tmp_path: Path) -> None:
    eval_id = "local_v1"
    manuscript = tmp_path / "projects" / "Crown_of_Ash" / "production" / "manuscript"
    manuscript.mkdir(parents=True)
    for chapter in [1, 2]:
        _write_candidate_run(tmp_path, chapter, eval_id)

    report = prepare_crown_narrative_heavy_audit(
        tmp_path,
        eval_id=eval_id,
        start_chapter=1,
        end_chapter=2,
    )

    assert report["status"] == "ready"
    run_dir = Path(report["run_dir"])
    assert (run_dir / "narrative_audit_manifest.yml").exists()
    context = (run_dir / "narrative_audit_context.md").read_text(encoding="utf-8")
    assert "Chapter 1 draft" in context
    assert "Chapter 2 continuity ledger" in context
    assert report["sources"][0]["files"]["fiction_draft.md"]["sha256"]
    assert report["context_bundle_id"].startswith("ctx-")
    bundle_path = Path(report["context_bundle_manifest"])
    bundle = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert bundle["chapter_window"] == [1, 2]
    assert bundle["role_specific_files"]["Reviewer"][0]["path"].endswith(
        "narrative_audit_context.md"
    )
    assert not (run_dir / "fiction_draft.md").exists()


def test_heavy_audit_bundle_rejects_oversized_range_without_creating_run(tmp_path: Path) -> None:
    report = prepare_crown_narrative_heavy_audit(
        tmp_path,
        eval_id="local_v1",
        start_chapter=1,
        end_chapter=21,
    )

    assert report["status"] == "blocked"
    assert "chapter_range_exceeds_limit:20" in report["issues"]
    assert not (
        tmp_path
        / "projects"
        / "Crown_of_Ash"
        / "runs"
        / "task_narrative_heavy_audit_ch001_ch021_local_v1"
    ).exists()
