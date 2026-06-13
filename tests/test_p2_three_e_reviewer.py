from __future__ import annotations

from pathlib import Path

from agent_runtime.review import (
    ReviewFinding,
    ReviewTarget,
    ReviewVerdict,
    derive_review_verdict,
    enhance_review_result,
    examine_review_target,
    explore_review_target,
    load_review_policy,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "p2_review"


def _policy():
    return load_review_policy(ROOT / "config" / "review_policy.yml")


def _target(name: str, changed_files: list[str] | None = None) -> ReviewTarget:
    target_dir = FIXTURES / name
    return ReviewTarget(
        task_id=name,
        target_dir=target_dir,
        handoff_path=target_dir / "external_handoff.md",
        report_path=target_dir / "p1_acceptance_report.md",
        changed_files=changed_files or [],
    )


def test_explore_collects_required_artifacts(tmp_path: Path) -> None:
    summary = explore_review_target(_target("good_delivery"), _policy(), output_dir=tmp_path)
    assert summary.required_artifacts_missing == []
    assert set(summary.required_artifacts_present) == {"external_handoff.md", "skill_usage_ledger.yml"}
    assert "python -m pytest -q tests/test_external_handoff_artifacts.py" in summary.claimed_tests
    assert (tmp_path / "explore_summary.yml").exists()


def test_examine_missing_required_artifact_fails() -> None:
    target = _target("missing_artifact_delivery")
    summary = explore_review_target(target, _policy())
    findings = examine_review_target(target, summary, _policy())
    verdict = derive_review_verdict(findings, _policy())
    assert any(f.category == "evidence" and f.severity == "high" for f in findings)
    assert verdict.status == "FAIL"


def test_high_risk_path_change_warns() -> None:
    target = _target("good_delivery", changed_files=["agent_runtime/review/three_e_reviewer.py"])
    summary = explore_review_target(target, _policy())
    summary.changed_files = target.changed_files
    findings = examine_review_target(target, summary, _policy())
    assert any(f.finding_id.startswith("high-risk-path") and f.status == "warn" for f in findings)
    assert derive_review_verdict(findings, _policy()).status == "PASS_WITH_WARNINGS"


def test_forbidden_path_change_fails() -> None:
    target = _target("good_delivery", changed_files=[".env"])
    summary = explore_review_target(target, _policy())
    summary.changed_files = target.changed_files
    findings = examine_review_target(target, summary, _policy())
    assert any(f.finding_id.startswith("forbidden-path") for f in findings)
    assert derive_review_verdict(findings, _policy()).status == "FAIL"


def test_derive_verdict_pass() -> None:
    assert derive_review_verdict([], _policy()).status == "PASS"


def test_derive_verdict_pass_with_warnings() -> None:
    findings = [ReviewFinding("low-1", "low", "scope", "warning", status="warn")]
    assert derive_review_verdict(findings, _policy()).status == "PASS_WITH_WARNINGS"


def test_derive_verdict_needs_revision() -> None:
    findings = [ReviewFinding("medium-1", "medium", "tests", "needs work")]
    assert derive_review_verdict(findings, _policy()).status == "NEEDS_REVISION"


def test_derive_verdict_fail() -> None:
    findings = [ReviewFinding("high-1", "high", "evidence", "missing artifact")]
    assert derive_review_verdict(findings, _policy()).status == "FAIL"


def test_derive_verdict_blocked() -> None:
    findings = [ReviewFinding("critical-1", "critical", "secrets", "secret found")]
    assert derive_review_verdict(findings, _policy()).status == "BLOCKED"


def test_enhance_generates_retry_handoff_on_failure(tmp_path: Path) -> None:
    target = _target("needs_revision_delivery")
    summary = explore_review_target(target, _policy())
    findings = examine_review_target(target, summary, _policy())
    verdict = derive_review_verdict(findings, _policy())
    retry = enhance_review_result(target, summary, findings, verdict, _policy(), output_dir=tmp_path)
    assert verdict.status == "NEEDS_REVISION"
    assert retry is not None
    assert retry.path.exists()
    assert "## Required Fixes" in retry.path.read_text(encoding="utf-8")


def test_enhance_does_not_generate_retry_handoff_on_pass(tmp_path: Path) -> None:
    target = _target("good_delivery")
    summary = explore_review_target(target, _policy())
    retry = enhance_review_result(target, summary, [], ReviewVerdict("PASS"), _policy(), output_dir=tmp_path)
    assert retry is None
    assert not (tmp_path / "retry_handoff.md").exists()
