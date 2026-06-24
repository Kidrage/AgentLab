from pathlib import Path
from typing import Dict, Any, List
from agent_runtime.control_panel.state import ControlState
from agent_runtime.workers.registry import WorkerRegistry

class WorkerControl:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.state = ControlState(project_root)
        self.registry = WorkerRegistry(project_root / ".agentlab" / "cache")

    def list_workers(self) -> List[Dict[str, Any]]:
        self.registry.scan_and_register()
        workers = []
        for w in self.registry.list_workers():
            c_state = self.state.get_entity_state("workers", w.worker_id)
            workers.append({
                "worker_id": w.worker_id,
                "display_name": w.display_name,
                "installed": w.installed,
                "version": w.version,
                "status": c_state.get("status", "enabled"),
                "force_role": c_state.get("force_role", None),
                "permissions": c_state.get("permissions", "default"),
                "risk_level": "high" if w.installed and c_state.get("status") == "disabled" else "normal"
            })
        return workers

    def enable_worker(self, worker_id: str):
        self.state.set_entity_state("workers", worker_id, {"status": "enabled"})

    def disable_worker(self, worker_id: str):
        self.state.set_entity_state("workers", worker_id, {"status": "disabled"})

    def force_assign_role(self, worker_id: str, role: str):
        self.state.set_entity_state("workers", worker_id, {"force_role": role})

    def reset_assignment(self, worker_id: str):
        current = self.state.get_entity_state("workers", worker_id)
        if "force_role" in current:
            del current["force_role"]
            self.state._state["workers"][worker_id] = current
            self.state._save()
            
    def get_overrides(self, worker_id: str) -> Dict[str, Any]:
        return self.state.get_entity_state("workers", worker_id)
