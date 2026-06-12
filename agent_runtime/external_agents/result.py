import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from agent_runtime.external_agents.registry import registry as agent_registry

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
        evidence_status = self._validate_evidence_requirements(result_data)
        result_data["evidence_status"] = evidence_status
        
        # Save result artifact
        self._save_result_artifact(result_data)
        
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
    
    def _validate_evidence_requirements(self, result_data: Dict[str, Any]) -> str:
        """Validate evidence requirements for the result. Returns evidence_status."""
        status = result_data.get("status", "completed")
        
        changed_files = result_data.get("changed_files", [])
        commands_run = result_data.get("commands_run", [])
        artifacts = result_data.get("artifacts", [])
        
        # Failed/rejected = missing evidence
        if status in ["failed", "rejected"]:
            return "missing"
        
        # Check for changed files without evidence
        if changed_files and not (artifacts or commands_run):
            raise ValueError("Changed files require evidence of commands run or artifacts")
            
        # Check for build/test claims without evidence
        summary = result_data.get("summary", "").lower()
        if any(claim in summary for claim in ["ran tests", "ran build", "executed commands"]):
            if not (commands_run or artifacts):
                raise ValueError("Build/test claims require evidence of commands run or artifacts")
                
        # Determine evidence level
        if commands_run or artifacts:
            return "complete"
        elif changed_files:
            return "partial"
        else:
            return "missing"
    
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