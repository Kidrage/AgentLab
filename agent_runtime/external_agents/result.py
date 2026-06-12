import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from agent_runtime.external_agents.registry import registry as agent_registry
from agent_runtime.task_events import TaskEvents

class ExternalResult:
    """Handles submission and validation of external agent results"""
    
    def __init__(self, task_id: str, handoff_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.handoff_id = handoff_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.result_id = f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    def submit_result(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit and validate an external agent result"""
        # Validate required fields
        self._validate_result_data(result_data)
        
        # Set submitted timestamp
        result_data["submitted_at"] = datetime.now().isoformat()
        
        # Set default status if not provided
        result_data.setdefault("status", "completed")
        
        # Validate evidence requirements
        self._validate_evidence_requirements(result_data)
        
        # Save result artifact
        self._save_result_artifact(result_data)
        
        # Record in ledger
        self._record_ledger_event(result_data)
        
        return result_data
        
    def _validate_result_data(self, result_data: Dict[str, Any]) -> None:
        """Validate required fields in result data"""
        required_fields = [
            "handoff_id", "task_id", "executor", "status", "summary"
        ]
        
        for field in required_fields:
            if field not in result_data:
                raise ValueError(f"Missing required field '{field}' in result data")
                
        # Validate executor fields
        executor = result_data["executor"]
        executor_fields = ["agent_id", "reported_by", "billing_mode", "token_visibility"]
        for field in executor_fields:
            if field not in executor:
                raise ValueError(f"Missing required executor field '{field}'")
                
        # Validate token visibility
        if executor["token_visibility"] != "unknown":
            raise ValueError("token_visibility must be 'unknown'")
            
        # Validate billing mode
        agent = agent_registry.get_agent(executor["agent_id"])
        if agent and executor["billing_mode"] != agent["billing"]["mode"]:
            raise ValueError("Billing mode mismatch with agent configuration")
    
    def _validate_evidence_requirements(self, result_data: Dict[str, Any]) -> None:
        """Validate evidence requirements for the result"""
        # Check if required evidence is missing
        if result_data.get("status") in ["completed", "partial"]:
            changed_files = result_data.get("changed_files", [])
            commands_run = result_data.get("commands_run", [])
            artifacts = result_data.get("artifacts", [])
            
            # Check for changed files evidence
            if changed_files and not (artifacts or commands_run):
                raise ValueError("Changed files require evidence of commands run or artifacts")
                
            # Check for build/test claims
            summary = result_data.get("summary", "").lower()
            if any(claim in summary for claim in ["ran tests", "ran build", "executed commands"]):
                if not (commands_run or artifacts):
                    raise ValueError("Build/test claims require evidence of commands run or artifacts")
    
    def _save_result_artifact(self, result_data: Dict[str, Any]) -> None:
        """Save the result artifact to disk"""
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Add metadata
        result_data["result_id"] = self.result_id
        result_data["submitted_at"] = result_data.get("submitted_at", datetime.now().isoformat())
        
        # Save YAML
        with open(output_path / "external_result.yml", 'w') as f:
            yaml.safe_dump(result_data, f, sort_keys=False)
            
    def _record_ledger_event(self, result_data: Dict[str, Any]) -> None:
        """Record result submission in task events"""
        event_data = {
            "event_type": "external_result_submitted",
            "result_id": self.result_id,
            "handoff_id": result_data["handoff_id"],
            "agent_id": result_data["executor"]["agent_id"],
            "status": result_data["status"],
            "billing_mode": result_data["executor"]["billing_mode"],
            "token_visibility": result_data["executor"]["token_visibility"],
            "evidence_status": self._determine_evidence_status(result_data)
        }
        
        TaskEvents(self.task_id).record_event(event_data)
        
    def _determine_evidence_status(self, result_data: Dict[str, Any]) -> str:
        """Determine evidence status based on result data"""
        if result_data.get("status") in ["rejected", "failed"]:
            return "missing"
            
        # Check for key evidence fields
        has_files = bool(result_data.get("changed_files"))
        has_commands = bool(result_data.get("commands_run"))
        has_artifacts = bool(result_data.get("artifacts"))
        
        if has_files or has_commands or has_artifacts:
            return "complete" if (has_commands or has_artifacts) else "partial"
            
        return "missing"