import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from agent_runtime.task_events import TaskEvents

class ExternalAgentLedger:
    """Tracks external agent interactions and verification status"""
    
    def __init__(self, task_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        self.ledger_data = self._load_ledger()
        
    def _load_ledger(self) -> Dict[str, Any]:
        """Load existing ledger or create new one"""
        if self.ledger_path.exists():
            with open(self.ledger_path, 'r') as f:
                return yaml.safe_load(f) or {"task_id": self.task_id, "handoffs": []}
                
        return {
            "task_id": self.task_id,
            "handoffs": [],
            "created_at": datetime.now().isoformat()
        }
        
    def add_handoff(self, handoff_data: Dict[str, Any]) -> None:
        """Add a new handoff to the ledger"""
        handoff_entry = {
            "handoff_id": handoff_data["handoff_id"],
            "agent_id": handoff_data["target"]["agent_id"],
            "status": handoff_data["target"]["status"],
            "billing_mode": handoff_data["budget"]["billing_mode"],
            "token_visibility": handoff_data["budget"]["external_token_visibility"],
            "api_cost_visible": handoff_data["budget"]["api_cost_visible"],
            "evidence_status": "missing",
            "artifact_gate_status": "pending",
            "created_at": datetime.now().isoformat(),
            "skill_usage_events": []
        }
        
        self.ledger_data["handoffs"].append(handoff_entry)
        self._save_ledger()
        self._record_event(handoff_entry, "handoff_created")
        
    def update_result_status(self, result_data: Dict[str, Any]) -> None:
        """Update ledger when a result is submitted"""
        handoff_id = result_data["handoff_id"]
        result_status = result_data["status"]
        evidence_status = result_data.get("evidence_status", "missing")
        
        for handoff in self.ledger_data["handoffs"]:
            if handoff["handoff_id"] == handoff_id:
                handoff["status"] = result_status
                handoff["evidence_status"] = evidence_status
                handoff["artifact_gate_status"] = "passed" if evidence_status == "complete" else "failed"
                handoff["updated_at"] = datetime.now().isoformat()
                
                # Record event
                event_data = {
                    "event_type": "result_submitted",
                    "handoff_id": handoff_id,
                    "status": result_status,
                    "evidence_status": evidence_status
                }
                self._record_event(event_data)
                break
                
        self._save_ledger()
        
    def add_skill_usage(self, handoff_id: str, skill_data: Dict[str, Any]) -> None:
        """Add skill usage event to the ledger"""
        for handoff in self.ledger_data["handoffs"]:
            if handoff["handoff_id"] == handoff_id:
                skill_event = {
                    "event": "planned" if "suggested_external_skills" in skill_data else "used",
                    "executor": skill_data.get("executor", "unknown"),
                    "cost_mode": skill_data.get("cost_mode", "unknown"),
                    "timestamp": datetime.now().isoformat()
                }
                
                handoff["skill_usage_events"].append(skill_event)
                self._save_ledger()
                self._record_event(skill_event)
                break
                
    def _save_ledger(self) -> None:
        """Save ledger data to disk"""
        with open(self.ledger_path, 'w') as f:
            yaml.safe_dump(self.ledger_data, f, sort_keys=False)
            
    def _record_event(self, event_data: Dict[str, Any]) -> None:
        """Record ledger events in task events"""
        TaskEvents(self.task_id).record_event({
            "event_type": f"external_ledger_{event_data.get('event_type', 'update')}",
            **event_data
        })
        
    def get_ledger(self) -> Dict[str, Any]:
        """Return current ledger data"""
        return self.ledger_data