from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.recovery.fake_evidence_detector import detect_fake_evidence, summarize_evidence_issues


def test_fake_evidence_detector_success():
    evidence_ledger = {
        "sources": [
            {
                "content_hash": "abc123hash",
                "line_refs": [10, 20],
                "path": "src/main.py",
            }
        ]
    }
    
    res = detect_fake_evidence(evidence_ledger)
    assert res["verdict"] == "pass"
    assert res["hard_fail"] is False
    assert len(res["issues"]) == 0
    assert res["source_count"] == 1


def test_fake_evidence_detector_missing_sources():
    evidence_ledger = {
        "sources": []
    }
    
    res = detect_fake_evidence(evidence_ledger)
    assert res["verdict"] == "fail"
    assert res["hard_fail"] is True
    assert "evidence_missing" in res["issues"]


def test_fake_evidence_detector_missing_metadata():
    evidence_ledger = {
        "sources": [
            {
                "path": "src/main.py",
                # missing content_hash and line_refs
            }
        ]
    }
    
    res = detect_fake_evidence(evidence_ledger)
    assert res["verdict"] == "fail"
    assert res["hard_fail"] is True
    assert "source_0_missing_content_hash" in res["issues"]
    assert "source_0_missing_line_refs" in res["issues"]


def test_summarize_evidence_issues():
    report = {
        "hard_fail": True,
        "issues": [
            "source_0_missing_content_hash",
            "source_0_missing_line_refs",
            "facts_allowed_without_sources",
        ]
    }
    
    summary = summarize_evidence_issues(report)
    assert summary["issue_count"] == 3
    assert summary["source_issue_count"] == 2
    assert summary["policy_issue_count"] == 1
    assert summary["hard_fail"] is True
