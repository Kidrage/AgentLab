from __future__ import annotations

from pathlib import Path

from agent_runtime.review import ReviewTarget, derive_review_verdict, examine_review_target, explore_review_target, load_review_policy
from agent_runtime.review.models import ExploreSummary


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "p2_review"


def _policy():
    return load_review_policy(ROOT / "config" / "review_policy.yml")


def _summary_with_text(text: str) -> ExploreSummary:
    return ExploreSummary(
        task_id="safety",
        target_dir=str(FIXTURES / "good_delivery"),
        required_artifacts_present=["external_handoff.md", "skill_usage_ledger.yml"],
        claimed_tests=["python -m pytest -q"],
        report_sections_present=["Summary", "Tests Run", "Safety Evidence", "Known Limitations", "Verdict"],
        text_evidence={"report.md": text},
    )


def _target() -> ReviewTarget:
    return ReviewTarget(task_id="safety", target_dir=FIXTURES / "good_delivery")


def test_examine_secret_pattern_blocks_or_fails() -> None:
    summary = _summary_with_text(
        "## Tests Run\n- python -m pytest -q\n## Safety Evidence\nOPENAI_API_KEY=sk-test-value\n"
    )
    findings = examine_review_target(_target(), summary, _policy())
    verdict = derive_review_verdict(findings, _policy())
    assert any(f.category == "secrets" for f in findings)
    assert verdict.status == "BLOCKED"


def test_examine_private_url_affirmative_no_is_not_false_positive() -> None:
    summary = _summary_with_text(
        "## Tests Run\n- python -m pytest -q\n## Safety Evidence\n- private URLs accessed: no localhost access\n"
    )
    findings = examine_review_target(_target(), summary, _policy())
    assert not any("private" in f.finding_id for f in findings)


def test_examine_private_url_yes_is_finding() -> None:
    summary = _summary_with_text(
        "## Tests Run\n- python -m pytest -q\n## Safety Evidence\n- private URLs accessed: yes localhost\n"
    )
    findings = examine_review_target(_target(), summary, _policy())
    assert any("private-url" in f.finding_id for f in findings)


def test_examine_remote_clone_no_is_not_false_positive() -> None:
    summary = _summary_with_text(
        "## Tests Run\n- python -m pytest -q\n## Safety Evidence\n- remote repos cloned: no\n"
    )
    findings = examine_review_target(_target(), summary, _policy())
    assert not any("remote-clone" in f.finding_id for f in findings)


def test_examine_remote_clone_yes_is_finding() -> None:
    summary = _summary_with_text(
        "## Tests Run\n- python -m pytest -q\n## Safety Evidence\n- remote repos cloned: yes\n"
    )
    findings = examine_review_target(_target(), summary, _policy())
    assert any("remote-clone" in f.finding_id for f in findings)


def test_unsafe_delivery_blocks_or_fails() -> None:
    target = ReviewTarget(task_id="unsafe", target_dir=FIXTURES / "unsafe_delivery")
    summary = explore_review_target(target, _policy())
    findings = examine_review_target(target, summary, _policy())
    verdict = derive_review_verdict(findings, _policy())
    assert verdict.status in {"BLOCKED", "FAIL"}
