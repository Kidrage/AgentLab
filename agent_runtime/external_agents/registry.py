import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from agent_runtime.config_loader import ConfigLoader

class ExternalAgentRegistry:
    """Registry for external agent configurations with validation"""
    
    def __init__(self, config_path: str = "config/external_agents.yml"):
        self.config_path = config_path
        self.agents = {}  # type: Dict[str, Dict[str, Any]]
        self._load_and_validate()
    
    def _load_and_validate(self) -> None:
        """Load and validate external agent configurations"""
        if not Path(self.config_path).exists():
            return
            
        with open(self.config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
            
        if not raw_config or 'external_agents' not in raw_config:
            return
            
        for agent in raw_config['external_agents']:
            self._validate_agent(agent)
            self.agents[agent['agent_id']] = agent
    
    def _validate_agent(self, agent: Dict[str, Any]) -> None:
        """Validate required fields and constraints for an agent"""
        required_fields = [
            'agent_id', 'display_name', 'type', 'enabled',
            'integration_mode', 'capabilities', 'billing',
            'risk', 'allowed_task_types'
        ]
        
        for field in required_fields:
            if field not in agent:
                raise ValueError(f"Missing required field '{field}' in agent config")
        
        # Validate billing constraints
        if agent['billing']['token_visibility'] != 'unknown':
            raise ValueError("token_visibility must be 'unknown'")
            
        # Validate risk constraints
        if not agent['risk'].get('requires_user_trigger', False):
            raise ValueError("All agents require user trigger")
            
        # Validate integration mode
        if agent['integration_mode'] != 'handoff_only':
            raise ValueError("Only handoff_only integration mode is supported")
    
    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent configuration by ID"""
        return self.agents.get(agent_id)
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all configured agents"""
        return list(self.agents.values())
    
    def is_agent_enabled(self, agent_id: str) -> bool:
        """Check if agent is enabled"""
        agent = self.get_agent(agent_id)
        return agent['enabled'] if agent else False

# Singleton instance
registry = ExternalAgentRegistry()