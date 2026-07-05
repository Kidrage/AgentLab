from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agent_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from performance_evaluator import render_audit, score


def _metrics(artifact_pass_rate: float) -> dict:
    return {
        "routing": {"pass_rate": 1.0, "passed": 1, "total": 1},
        "configuration": {"pass": True},
        "lifecycle": {
            "node_count": 20,
            "expected_node_count": 20,
            "analysis_route_skips_coder": True,
        },
        "commands": {"passed": 2, "total": 2, "results": []},
        "artifacts": {"pass_rate": artifact_pass_rate},
    }


def test_performance_score_includes_artifact_completeness() -> None:
    full = score(_metrics(1.0))
    partial = score(_metrics(0.5))

    assert full["total"] == 100.0
    assert partial["total"] == 92.5
    assert partial["components"]["artifacts"] == 7.5


def test_performance_audit_reports_low_artifact_completeness() -> None:
    report = render_audit({**_metrics(0.77), "score": score(_metrics(0.77))})

    assert "Artifact completeness below threshold: 0.77." in report
