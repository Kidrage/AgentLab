import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from agent_runtime.external_agents.registry import registry as agent_registry

class ExternalHandoff:
    """Manages creation and validation of external handoff artifacts"""
    
    def __init__(self, task_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.handoff_id = f"handoff_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}"
        
    def create_handoff(self, agent_id: str, title: str, summary: str) -> Dict[str, Any]:
        """Create a new handoff artifact with validation"""
        agent = agent_registry.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found in registry")
            
        status = "proposed"
            
        handoff_data = {
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "project": "AgentLab",
            "target": {
                "agent_id": agent_id,
                "agent_type": agent['type'],
                "integration_mode": agent['integration_mode'],
                "enabled": agent['enabled'],
                "status": status
            },
            "objective": {
                "title": title,
                "summary": summary
            },
            "constraints": [],
            "required_outputs": [],
            "budget": {
                "billing_mode": agent['billing']['mode'],
                "api_cost_visible": agent['billing']['api_cost_visible'],
                "external_token_visibility": "unknown"
            },
            "evidence_requirements": []
        }
        
        self._save_artifacts(handoff_data)
        return handoff_data
        
    def _save_artifacts(self, handoff_data: Dict[str, Any]) -> None:
        """Save YAML and markdown artifacts"""
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save YAML
        with open(output_path / "external_handoff.yml", 'w') as f:
            yaml.safe_dump(handoff_data, f, sort_keys=False)
            
        # Generate and save markdown
        md_content = self._generate_markdown(handoff_data)
        with open(output_path / "external_handoff.md", 'w') as f:
            f.write(md_content)
            
    def _generate_markdown(self, handoff_data: Dict[str, Any]) -> str:
        """Generate markdown template for external agents"""
        md = f"# External Agent Handoff - {handoff_data['handoff_id']}\n\n"
        md += f"**Task ID:** {handoff_data['task_id']}\n"
        md += f"**Project:** {handoff_data['project']}\n\n"
        
        md += "## Target Agent\n"
        target = handoff_data['target']
        md += f"- Agent ID: {target['agent_id']}\n"
        md += f"- Type: {target['agent_type']}\n"
        md += f"- Enabled: {target['enabled']}\n"
        md += f"- Status: {target['status']}\n\n"
        
        md += "## Objective\n"
        obj = handoff_data['objective']
        md += f"### {obj['title']}\n{obj['summary']}\n\n"
        
        md += "## Constraints\n"
        for constraint in handoff_data['constraints']:
            md += f"- {constraint}\n"
            
        md += "\n## Required Outputs\n"
        for output in handoff_data['required_outputs']:
            md += f"- {output}\n"
            
        md += "\n## Budget Information\n"
        budget = handoff_data['budget']
        md += f"- Billing Mode: {budget['billing_mode']}\n"
        md += f"- API Cost Visible: {budget['api_cost_visible']}\n"
        md += f"- Token Visibility: {budget['external_token_visibility']}\n"
        
        return md