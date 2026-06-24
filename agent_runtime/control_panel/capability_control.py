from pathlib import Path
from typing import Dict, Any, List
from agent_runtime.control_panel.state import ControlState

class CapabilityControl:
    def __init__(self, project_root: Path):
        self.state = ControlState(project_root)

    def list_capabilities(self) -> List[Dict[str, Any]]:
        res = []
        for c_id, c_data in self.state._state.get("capabilities", {}).items():
            res.append({
                "capability_id": c_id,
                "status": c_data.get("status", "enabled")
            })
        return res

    def enable_capability(self, capability_id: str):
        self.state.set_entity_state("capabilities", capability_id, {"status": "enabled"})

    def disable_capability(self, capability_id: str):
        self.state.set_entity_state("capabilities", capability_id, {"status": "disabled"})
