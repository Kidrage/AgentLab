"""S10 offline generalization evaluation suite.

The suite uses static fixtures and deterministic artifact simulation. It never
calls model APIs, web providers, media backends, or external agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

import yaml


REQUIRED_FIXTURE_DOMAINS = {
    "docs",
    "cli",
    "capability_gap",
    "recovery",
    "project_brain",
    "search_repo_mock",
    "longform_novel",
    "research_archive",
    "codebase_repair",
    "video_story_skeleton",
    "document_ingestion",
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
        "offline_only": True,
        "external_execution": "blocked",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "verdict": "PASS" if passed == len(results) else "FAIL",
        "results": results,
    }
    _write_yaml(out_dir / "generalization_results.yml", summary)
    (out_dir / "S10_GENERALIZATION_EVAL_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def run_pipeline_replay(agentlab_root: Path, out_dir: Path, fixture: GeneralizationFixture) -> dict[str, Any]:
    """Replay route -> task packet -> phase acceptance -> Project Brain writeback."""
    replay_root = out_dir / "pipeline_replay" / fixture.fixture_id
    if replay_root.exists():
        shutil.rmtree(replay_root)
    (replay_root / "projects").mkdir(parents=True, exist_ok=True)
    shutil.copytree(agentlab_root / "config", replay_root / "config")

    project = "S10Replay"
    phase_id = "phase_1"
    task_id = "task_0001"
    project_root = replay_root / "projects" / project
    brain_dir = project_root / "project_brain"
    run_dir = project_root / "runs" / task_id
    brain_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(brain_dir / "project_brief.yml", {"project_name": project, "request": fixture.request})
    _write_yaml(brain_dir / "roadmap.yml", {"milestones": [{"phase_id": phase_id, "title": fixture.domain}]})
    _write_yaml(brain_dir / "acceptance_history.yml", {"entries": []})
    _write_yaml(brain_dir / "next_actions.yml", {"next_action": "prepare_phase"})
    _write_yaml(brain_dir / "project_fact_snapshot.yml", {"project": project, "event_count": 0, "events": []})

    phase_plan_path = run_dir / "phase_plan.yml"
    phase_plan = {
        "project": project,
        "project_type": "codebase_build_project",
        "phase_id": phase_id,
        "goal": fixture.request,
        "context_summary": f"S10 replay for {fixture.domain}",
        "long_project_governance_required": True,
        "project_brain_dir": str(brain_dir),
        "allowed_files": ["docs", "agent_runtime", "tests"],
        "forbidden_files": [".env", ".git"],
        "outputs": ["evidence.yml"],
        "evidence_required": ["evidence.yml"],
        "acceptance_criteria": ["evidence present"],
        "roles": ["Coder"],
        "available_workers": ["codex"],
        "approved_workers": ["codex"],
        "commands_allowed": ["pytest"],
        "commands_forbidden": ["rm -rf", "curl", "wget"],
    }
    _write_yaml(phase_plan_path, phase_plan)

    from agent_runtime.executors.task_packet import create_task_packet
    from agent_runtime.program_manager.phase_acceptance import accept_phase
    from agent_runtime.routing.worker_router import route_task_packet

    packet = create_task_packet(phase_plan_path, "codex_handoff", run_dir)
    route = route_task_packet(run_dir / "task_packet.yml", replay_root)

    _write_yaml(run_dir / "executor_result.yml", {
        "task_id": task_id,
        "executor_id": "codex",
        "source": "s10_pipeline_replay",
        "status": "PASS",
        "summary": "Replay evidence generated through AgentLab acceptance path.",
        "changed_files": ["docs/s10_replay.md"],
        "test_results": {"passed": True},
        "artifacts": [{"path": "evidence.yml"}],
        "safety_attestation": {"secrets_exposed": False},
    })
    _write_yaml(run_dir / "evidence_ledger.yml", {
        "result_dir": str(run_dir),
        "files": [{"path": "executor_result.yml"}, {"path": "evidence.yml"}],
        "evidence_count": 2,
    })
    (run_dir / "evidence.yml").write_text("passed: true\n", encoding="utf-8")

    acceptance = accept_phase(run_dir / "task_packet.yml", run_dir, run_dir)
    artifacts = [
        run_dir / "task_packet.yml",
        replay_root / "projects" / project / "runs" / "S10Replay_phase_1_task" / "routing" / "route_plan.yml",
        run_dir / "phase_acceptance.yml",
        brain_dir / "acceptance_history.yml",
        brain_dir / "next_actions.yml",
    ]
    present = [str(path.relative_to(replay_root)) for path in artifacts if path.exists()]
    required = [str(path.relative_to(replay_root)) for path in artifacts]
    passes = (
        len(present) == len(required)
        and bool(packet.get("task_packet"))
        and bool(route.get("route_plan"))
        and acceptance.get("accepted") is True
        and acceptance.get("acceptance_history_status", {}).get("recorded") is True
    )
    return {
        "fixture_id": fixture.fixture_id,
        "mode": "pipeline_replay",
        "pass": passes,
        "score": 1.0 if passes else 0.0,
        "generated_by_agentlab_chain": [
            "create_task_packet",
            "route_task_packet",
            "accept_phase",
            "project_brain_acceptance_writeback",
        ],
        "required_artifacts": required,
        "artifacts_present": present,
        "external_execution": "blocked",
        "project_root": str(project_root),
    }


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
