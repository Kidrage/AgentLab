from pathlib import Path
from agent_runtime.control_panel.state import ControlState

class StatusSummary:
    def __init__(self, project_root: Path):
        self.state = ControlState(project_root)

    def get_summary(self):
        return {
            "workers": len(self.state._state.get("workers", {})),
            "skills": len(self.state._state.get("skills", {})),
            "capabilities": len(self.state._state.get("capabilities", {})),
            "executors": len(self.state._state.get("executors", {}))
        }
