from pathlib import Path
from typing import Dict, Any, List
from agent_runtime.control_panel.state import ControlState

class SkillControl:
    def __init__(self, project_root: Path):
        self.state = ControlState(project_root)

    def list_skills(self) -> List[Dict[str, Any]]:
        # In a real impl, fetch from SkillVault. Here we mock from state.
        res = []
        for s_id, s_data in self.state._state.get("skills", {}).items():
            res.append({
                "skill_id": s_id,
                "status": s_data.get("status", "enabled"),
                "risk": "high" if s_data.get("status") == "disabled" else "normal"
            })
        return res

    def enable_skill(self, skill_id: str):
        self.state.set_entity_state("skills", skill_id, {"status": "enabled"})

    def disable_skill(self, skill_id: str):
        self.state.set_entity_state("skills", skill_id, {"status": "disabled"})
