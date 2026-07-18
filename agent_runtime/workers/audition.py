"""High-level worker audition manager for AgentLab."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_runtime.workers.worker_card import WorkerCard
from agent_runtime.workers.registry import WorkerRegistry
from agent_runtime.workers.performance_ledger import (
    PerformanceLedger,
    default_performance_ledger_path,
)
from agent_runtime.workers.audition_runner import run_worker_audition
from agent_runtime.workers.audition_tasks import get_task_for_role


def get_default_ledger_path(project_root: Path) -> Path:
    return default_performance_ledger_path(project_root)


def run_all_auditions(
    level: str,
    real_execute: bool,
    project_root: Path
) -> list[dict[str, Any]]:
    """Run auditions for all discovered workers across all roles they are compatible with."""
    cache_dir = project_root / ".agentlab"
    registry = WorkerRegistry(cache_dir)
    registry.load_from_cache() or registry.scan_and_register()
    
    ledger_path = get_default_ledger_path(project_root)
    ledger = PerformanceLedger(ledger_path)
    
    workers = registry.list_workers()
    results = []

    # Map worker category to reasonable audition roles
    from agent_runtime.workers.worker_card import WorkerCategory
    category_role_map = {
        WorkerCategory.CODING_AGENT: ["Coder", "ArtifactProducer", "TesterAuditor"],
        WorkerCategory.PLANNING_AGENT: ["Supervisor"],
        WorkerCategory.FRONTDESK_AGENT: ["Archivist"],
        WorkerCategory.MULTIMODAL_CLOUD_TOOL: ["ArtifactProducer", "Researcher"],
        WorkerCategory.DETERMINISTIC_REPO_TOOL: ["RepoScout"],
        WorkerCategory.DETERMINISTIC_AST_TOOL: ["InterfaceMapper"],
        WorkerCategory.TEST_RUNNER: ["TesterAuditor"],
        WorkerCategory.LINTER: ["Verifier"],
        WorkerCategory.FORMATTER: ["Verifier"],
        WorkerCategory.SHELL_TOOL: ["Coder"],
        WorkerCategory.VCS_TOOL: ["Archivist"]
    }

    for worker in workers:
        roles_to_test = category_role_map.get(worker.category, ["Coder"])
        for role in roles_to_test:
            try:
                res = run_worker_audition(
                    worker_id=worker.worker_id,
                    role=role,
                    level=level,
                    real_execute=real_execute,
                    ledger=ledger,
                    worker_card=worker
                )
                results.append(res)
            except Exception:
                # "failed audition does not break registry"
                pass
                
    return results


def run_single_audition(
    worker_id: str,
    role: str,
    level: str,
    real_execute: bool,
    project_root: Path
) -> dict[str, Any]:
    """Run audition for a single worker on a specific role."""
    cache_dir = project_root / ".agentlab"
    registry = WorkerRegistry(cache_dir)
    registry.load_from_cache() or registry.scan_and_register()
    
    ledger_path = get_default_ledger_path(project_root)
    ledger = PerformanceLedger(ledger_path)
    
    worker = registry.get_worker(worker_id)
    # If not found in registry, we fabricate a basic card to avoid breaking
    if not worker:
        worker = WorkerCard(
            worker_id=worker_id,
            display_name=worker_id,
            command=worker_id,
            installed=False
        )
        
    return run_worker_audition(
        worker_id=worker_id,
        role=role,
        level=level,
        real_execute=real_execute,
        ledger=ledger,
        worker_card=worker
    )


def get_scorecard_report_data(project_root: Path) -> dict[str, Any]:
    ledger_path = get_default_ledger_path(project_root)
    ledger = PerformanceLedger(ledger_path)
    return ledger.performances
