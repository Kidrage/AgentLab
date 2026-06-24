from pathlib import Path
from typing import Dict, Any, List
from agent_runtime.control_panel.state import ControlState

class ExecutorControl:
    def __init__(self, project_root: Path):
        self.state = ControlState(project_root)

    def list_executors(self) -> List[Dict[str, Any]]:
        res = []
        for e_id, e_data in self.state._state.get("executors", {}).items():
            res.append({
                "executor_id": e_id,
                "status": e_data.get("status", "enabled"),
                "trust_level": e_data.get("trust_level", "sandbox")
            })
        return res

    def enable_executor(self, executor_id: str):
        self.state.set_entity_state("executors", executor_id, {"status": "enabled"})

    def disable_executor(self, executor_id: str):
        self.state.set_entity_state("executors", executor_id, {"status": "disabled"})
