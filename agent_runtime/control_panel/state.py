import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

class ControlState:
    def __init__(self, project_root: Path):
        self.state_file = project_root / ".agentlab" / "control_state.yml"
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"workers": {}, "skills": {}, "capabilities": {}, "executors": {}}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {"workers": {}, "skills": {}, "capabilities": {}, "executors": {}}
        except yaml.YAMLError:
            return {"workers": {}, "skills": {}, "capabilities": {}, "executors": {}}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._state, f, sort_keys=False)

    def get_entity_state(self, entity_type: str, entity_id: str) -> Dict[str, Any]:
        return self._state.get(entity_type, {}).get(entity_id, {})

    def set_entity_state(self, entity_type: str, entity_id: str, updates: Dict[str, Any]):
        if entity_type not in self._state:
            self._state[entity_type] = {}
        if entity_id not in self._state[entity_type]:
            self._state[entity_type][entity_id] = {}
        self._state[entity_type][entity_id].update(updates)
        self._save()
        
    def is_disabled(self, entity_type: str, entity_id: str) -> bool:
        return self.get_entity_state(entity_type, entity_id).get("status") == "disabled"
