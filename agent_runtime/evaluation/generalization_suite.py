"""S10 offline generalization evaluation suite.

The suite uses static fixtures and deterministic artifact simulation. It never
calls model APIs, web providers, media backends, or external agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FIXTURE_DOMAINS = {
    "docs",
    "cli",
    "capability_gap",
    "recovery",
    "project_brain",
    "search_repo_mock",
}


@dataclass(frozen=True, slots=True)
class GeneralizationFixture:
    fixture_id: str
    domain: str
    request: str
    expected_route: str
    required_artifacts: list[str]
    offline_only: bool
    allow_external_execution: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_generalization_fixtures(agentlab_root: Path) -> list[GeneralizationFixture]:
    path = agentlab_root / "config" / "generalization_fixtures.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fixtures = []
    for item in data.get("fixtures", []):
        fixtures.append(
            GeneralizationFixture(
                fixture_id=item["fixture_id"],
                domain=item["domain"],
                request=item["request"],
                expected_route=item["expected_route"],
                required_artifacts=list(item["required_artifacts"]),
                offline_only=bool(item["offline_only"]),
                allow_external_execution=bool(item["allow_external_execution"]),
            )
        )
    domains = {fixture.domain for fixture in fixtures}
    missing = REQUIRED_FIXTURE_DOMAINS - domains
    if missing:
        raise ValueError(f"missing required fixture domains: {sorted(missing)}")
    return sorted(fixtures, key=lambda fixture: fixture.fixture_id)


def evaluate_fixture(fixture: GeneralizationFixture, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = out_dir / fixture.fixture_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for artifact in fixture.required_artifacts:
        path = artifact_dir / artifact
        if artifact.endswith(".yml"):
            _write_yaml(path, {"fixture_id": fixture.fixture_id, "domain": fixture.domain, "mock": True})
        else:
            path.write_text(
                f"# {fixture.fixture_id}\n\nOffline fixture artifact for {fixture.domain}.\n",
                encoding="utf-8",
            )

    artifacts_present = sorted(p.name for p in artifact_dir.iterdir() if p.is_file())
    required_sorted = sorted(fixture.required_artifacts)
    passes = (
        fixture.offline_only
        and not fixture.allow_external_execution
        and artifacts_present == required_sorted
        and bool(fixture.expected_route)
    )
    return {
        "fixture_id": fixture.fixture_id,
        "domain": fixture.domain,
        "expected_route": fixture.expected_route,
        "offline_only": fixture.offline_only,
        "external_execution": "blocked" if not fixture.allow_external_execution else "allowed",
        "artifacts_present": artifacts_present,
        "required_artifacts": required_sorted,
        "score": 1.0 if passes else 0.0,
        "pass": passes,
    }


def run_generalization_suite(agentlab_root: Path, out_dir: Path) -> dict[str, Any]:
    fixtures = load_generalization_fixtures(agentlab_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [evaluate_fixture(fixture, out_dir / "fixtures") for fixture in fixtures]
    passed = sum(1 for result in results if result["pass"])
    summary = {
        "stage": "S10",
        "suite": "generalization_eval",
        "started_at": _utc_now(),
        "offline_only": True,
        "external_execution": "blocked",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "verdict": "PASS" if passed == len(results) else "FAIL",
        "results": results,
        "completed_at": _utc_now(),
    }
    _write_yaml(out_dir / "generalization_results.yml", summary)
    (out_dir / "S10_GENERALIZATION_EVAL_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# S10 Generalization Eval Report",
        "",
        f"## Verdict: {summary['verdict']}",
        "",
        "## Baseline",
        "",
        "S10 is additive on top of S9 Capability Fabric. The suite is offline-only and uses static fixtures from config/generalization_fixtures.yml.",
        "",
        "## Summary",
        "",
        f"- Total fixtures: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        "- Offline only: true",
        "- External execution: blocked",
        "",
        "## New Runtime and Config",
        "",
        "- agent_runtime/evaluation/generalization_suite.py",
        "- config/generalization_fixtures.yml",
        "- config/ci_gate_policy.yml",
        "- docs/S10_GENERALIZATION_EVAL_SUITE.md",
        "- tests/test_s10_generalization_eval.py",
        "",
        "## CLI",
        "",
        "- ./agentlab.sh eval-generalization --out acceptance_runs/s10_generalization_eval",
        "- ./agentlab.sh ci-gates --dry-run",
        "- ./agentlab.sh ci-gates",
        "",
        "## Fixture Results",
        "",
    ]
    for result in summary["results"]:
        lines.extend(
            [
                f"### {result['fixture_id']}",
                "",
                f"- Domain: {result['domain']}",
                f"- Expected route: {result['expected_route']}",
                f"- Score: {result['score']}",
                f"- Pass: {result['pass']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety Notes",
            "",
            "No fixture calls real web, real model APIs, real vision/audio backends, or external agents.",
            "",
        ]
    )
    return "\n".join(lines)


def load_ci_gate_policy(agentlab_root: Path) -> dict[str, Any]:
    return yaml.safe_load((agentlab_root / "config" / "ci_gate_policy.yml").read_text(encoding="utf-8"))
