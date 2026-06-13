from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.executors.models import ExecutionPlan, ExecutorDecision, ExecutionRouteReport, to_plain_data


def write_route_report(
    output_dir: Path,
    task_id: str,
    decision: ExecutorDecision,
    plan: ExecutionPlan | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = ExecutionRouteReport(
        task_id=task_id,
        decision=decision,
        plan=plan,
        rejected_providers=decision.rejected_providers,
    )
    path = output_dir / "route_report.yml"
    atomic_write_yaml(path, to_plain_data(report))
    return path
