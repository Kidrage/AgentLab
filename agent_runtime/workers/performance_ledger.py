"""Worker performance ledger loader and manager for AgentLab."""

from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class PerformanceLedger:
    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path
        self.performances: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.ledger_path.exists():
            self.performances = {}
            return
        try:
            content = self.ledger_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            self.performances = data.get("worker_performance", {})
        except Exception:
            self.performances = {}

    def save(self) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"worker_performance": self.performances}
            content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
            self.ledger_path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    def get_worker_performance(self, worker_id: str) -> Optional[dict[str, Any]]:
        return self.performances.get(worker_id)

    def update_performance(
        self,
        worker_id: str,
        role: str,
        score: float,
        cost_score: float,
        safety_score: float,
        suite: str,
        verdict: str,
        timestamp: str,
        is_success: bool
    ) -> None:
        perf = self.performances.setdefault(worker_id, {
            "role_scores": {},
            "cost_score": 0.5,
            "safety_score": 0.5,
            "last_audition": {},
            "historical_runs": {"total": 0, "success": 0, "failed": 0}
        })
        
        # Update role score
        perf["role_scores"][role.lower()] = round(score, 2)
        perf["cost_score"] = round(cost_score, 2)
        perf["safety_score"] = round(safety_score, 2)
        
        # Update last audition
        perf["last_audition"] = {
            "timestamp": timestamp,
            "suite": suite,
            "verdict": verdict
        }
        
        # Update history
        history = perf.setdefault("historical_runs", {"total": 0, "success": 0, "failed": 0})
        history["total"] += 1
        if is_success:
            history["success"] += 1
        else:
            history["failed"] += 1
            
        self.save()

    def get_best_worker_for_role(self, role: str, compatible_workers: list[str]) -> Optional[str]:
        """Return the compatible worker with the highest score for a role.
        
        Falls back to the first compatible worker if no scores exist.
        """
        if not compatible_workers:
            return None
            
        best_worker = None
        best_score = -1.0
        
        for w_id in compatible_workers:
            score = 0.5  # default baseline score
            perf = self.get_worker_performance(w_id)
            if perf and "role_scores" in perf:
                score = perf["role_scores"].get(role.lower(), 0.5)
            if score > best_score:
                best_score = score
                best_worker = w_id
                
        return best_worker
