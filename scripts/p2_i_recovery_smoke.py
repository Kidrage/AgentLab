#!/usr/bin/env python3
"""P2-I Recovery smoke test script.

Run recovery smoke test: capture failure, diagnose, generate plan and verdict.
This script can also be used as a standalone verification of the recovery system.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.recovery import (
    FailureEvent,
    FailureClassifier,
    FailureCategory,
    diagnose_failure,
    build_recovery_plan,
    load_retry_policy,
    decide_retry_action,
    create_failure_event,
)


def main() -> int:
    """Run recovery smoke test."""
    parser = argparse.ArgumentParser(
        description="P2-I Recovery smoke test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        default="AgentLab",
        help="Project name (default: AgentLab)",
    )
    parser.add_argument(
        "--task-id",
        default="recovery_smoke_test",
        help="Test task ID (default: recovery_smoke_test)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: acceptance_runs/p2_i_failure_recovery)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON",
    )

    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else ROOT / "acceptance_runs" / "p2_i_failure_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create a test failure event (simulating a test failure)
    failure_event = create_failure_event(
        task_id=args.task_id,
        project=args.project,
        stage="pytest",
        command="python -m pytest tests/ -q",
        exit_code=1,
        stderr="tests/test_example.py FAILED\nAssertionError: assert False\n1 failed in 0.1s",
        stdout="running 5 tests...",
        artifact_paths=[],
    )

    # Write failure event
    event_path = out_dir / "failure_event.json"
    event_path.write_text(json.dumps(failure_event.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps({"failure_event": str(event_path)}, indent=2))
    else:
        print(f"[OK] Failure event: {event_path}")

    # Classify the failure
    classifier = FailureClassifier()
    classification = classifier.classify(stderr=failure_event.stderr_tail)
    if args.json:
        print(json.dumps({"classification": classification.to_dict()}, indent=2))
    else:
        print(f"\n[OK] Classification:")
        print(f"  Primary: {classification.primary_category.value}")
        print(f"  Confidence: {classification.confidence}")
        print(f"  Is Retriable: {classification.is_retriable}")
        print(f"  Requires Human Review: {classification.requires_human_review}")

    # Diagnose
    diagnosis = diagnose_failure(failure_event)
    diagnosis_path = out_dir / "failure_diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps({"diagnosis": str(diagnosis_path)}, indent=2))
    else:
        print(f"\n[OK] Diagnosis: {diagnosis_path}")

    # Build plan
    policy = load_retry_policy(out_dir)
    plan = build_recovery_plan(failure_event, diagnosis, policy)
    plan_path = out_dir / "recovery_plan.md"
    plan_path.write_text(plan.to_markdown(), encoding="utf-8")
    if args.json:
        print(json.dumps({"recovery_plan": str(plan_path)}, indent=2))
    else:
        print(f"[OK] Recovery plan: {plan_path}")

    # Decide verdict
    verdict = decide_retry_action(diagnosis, policy)
    verdict_path = out_dir / "recovery_verdict.json"
    verdict_path.write_text(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps({"verdict": str(verdict_path)}, indent=2))
    else:
        print(f"[OK] Verdict: {verdict_path}")

    # Output summary
    if not args.json:
        print(f"\n{'=' * 60}")
        print("Recovery Smoke Test Summary")
        print(f"{'=' * 60}")
        print(f"  Task ID: {args.task_id}")
        print(f"  Project: {args.project}")
        print(f"  Primary Category: {diagnosis.primary_category.value}")
        print(f"  Confidence: {diagnosis.confidence}")
        print(f"  Verdict: {verdict.verdict.value}")
        print(f"  Safe to Auto-Retry: {verdict.safe_to_auto_retry}")
        print(f"  Requires Human Review: {verdict.requires_human_review}")

    # Check results
    errors = []

    # Check that all artifacts were created
    expected_files = [
        "failure_event.json",
        "failure_diagnosis.json",
        "recovery_plan.md",
        "recovery_verdict.json",
    ]
    for fname in expected_files:
        fpath = out_dir / fname
        if not fpath.exists():
            errors.append(f"Missing artifact: {fname}")

    # Check that diagnosis has required fields
    if not diagnosis.primary_category:
        errors.append("Diagnosis missing primary_category")
    if not diagnosis.root_cause_hypothesis:
        errors.append("Diagnosis missing root_cause_hypothesis")

    # Check that verdict has required fields
    if not verdict.verdict:
        errors.append("Verdict missing verdict field")

    # Check classification
    if classification.primary_category != FailureCategory.TEST_FAILURE:
        errors.append(f"Expected TEST_FAILURE, got {classification.primary_category.value}")

    # Check that stdout/stderr were truncated and redacted
    if failure_event.stdout_tail and len(failure_event.stdout_tail) > 8000:
        errors.append("stdout_tail not truncated")
    if failure_event.stderr_tail and len(failure_event.stderr_tail) > 8000:
        errors.append("stderr_tail not truncated")

    # Check that no secrets were leaked (no .env content or API keys in output)
    combined_output = event_path.read_text(encoding="utf-8")
    if "sk-" in combined_output and "sk-" not in str(failure_event.stderr_tail):
        errors.append("Potential secret leak in output")

    if errors:
        if args.json:
            print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        else:
            print(f"\n[FAIL] Smoke test failed:")
            for err in errors:
                print(f"  - {err}")
        return 1

    if not args.json:
        print(f"\n[SUCCESS] Recovery smoke test completed.")
        print(f"Artifacts: {out_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
