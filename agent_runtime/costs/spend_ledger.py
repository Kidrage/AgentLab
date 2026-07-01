import yaml
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

class SpendLedger:
    def __init__(self, project: str):
        self.project = project
        self.entries: List[Dict[str, Any]] = []

    def record_spend(self, entry: Dict[str, Any]):
        self.entries.append(entry)

    def get_total(self) -> float:
        return sum(e.get("cost_usd", 0.0) for e in self.entries)

    def get_total_by_project(self, project: str) -> float:
        if self.project != project:
            return 0.0
        return self.get_total()

    def get_total_by_task(self, task_id: str) -> float:
        return sum(e.get("cost_usd", 0.0) for e in self.entries if e.get("task_id") == task_id)

    def get_total_by_phase(self, phase_id: str) -> float:
        return sum(e.get("cost_usd", 0.0) for e in self.entries if e.get("phase_id") == phase_id)

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "entries": self.entries
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SpendLedger':
        ledger = cls(data.get("project", "default"))
        ledger.entries = data.get("entries", [])
        return ledger

def load_spend_ledger(path: Path) -> SpendLedger:
    if not path.exists():
        return SpendLedger("default")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SpendLedger.from_dict(data)

def write_spend_ledger(ledger: SpendLedger, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(yaml.safe_dump(ledger.to_dict(), sort_keys=False), encoding="utf-8")
    temp_path.replace(path)
