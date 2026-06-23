"""Audition runner coordinating sandboxed or mock executions for worker auditioning."""

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from agent_runtime.workers.audition_tasks import get_task_for_role, AuditionTask
from agent_runtime.workers.audition_scorer import AuditionScorer
from agent_runtime.workers.sandbox import AuditionSandbox
from agent_runtime.workers.performance_ledger import PerformanceLedger


def run_worker_audition(
    worker_id: str,
    role: str,
    level: str,
    real_execute: bool,
    ledger: PerformanceLedger,
    worker_card: Any = None
) -> dict[str, Any]:
    """Execute audition suite for a worker and update the performance ledger."""
    task = get_task_for_role(role)
    timestamp = datetime.now().isoformat()
    
    # Defaults
    cost_usd = 0.0
    latency_s = 0.0
    stdout = ""
    is_success = False
    verdict = "fail"
    risk_level = "medium"
    
    if worker_card:
        risk_level = worker_card.risk_level

    # Check if worker is installed/available if real execution is requested
    is_installed = False
    if worker_card:
        is_installed = worker_card.installed

    if real_execute and is_installed:
        # Run inside sandbox
        try:
            with AuditionSandbox() as sandbox:
                # Find command template from worker contract or default
                cmd_arg = worker_card.command
                
                # Setup specific arguments depending on level and command
                # For safety during audition: we just do safe/dry-run checks
                if level == "quick":
                    cmd = [cmd_arg, "--help"]
                else:
                    # Basic echo/probe command to avoid real mutations
                    cmd = [cmd_arg, "--version"]
                
                start_time = time.time()
                result = subprocess.run(
                    cmd,
                    cwd=sandbox.path / "mock_repo" if sandbox.path else None,
                    capture_output=True,
                    text=True,
                    timeout=10.0
                )
                latency_s = time.time() - start_time
                stdout = result.stdout + "\n" + result.stderr
                is_success = (result.returncode == 0) and task.verify(stdout, sandbox.path)
                cost_usd = 0.0  # CLI commands have no token costs
        except Exception as e:
            stdout = f"Sandbox execution error: {str(e)}"
            is_success = False
            latency_s = 0.5
    else:
        # Mock mode
        stdout, cost_usd, latency_s = task.get_mock_output(worker_id)
        is_success = True  # Mock workers succeed in mock mode
        
    verdict = "pass" if is_success else "fail"
    
    # Scorer
    scores = AuditionScorer.calculate_scores(
        worker_id=worker_id,
        role=role,
        is_success=is_success,
        cost_usd=cost_usd,
        latency_s=latency_s,
        worker_risk=risk_level
    )
    
    # Update performance ledger
    ledger.update_performance(
        worker_id=worker_id,
        role=role,
        score=scores["role_fit_score"],
        cost_score=scores["cost_score"],
        safety_score=scores["safety_score"],
        suite=level,
        verdict=verdict,
        timestamp=timestamp,
        is_success=is_success
    )
    
    return {
        "worker_id": worker_id,
        "role": role,
        "level": level,
        "verdict": verdict,
        "stdout": stdout,
        "scores": scores,
        "timestamp": timestamp
    }
