import unittest
from pathlib import Path
from agent_runtime.external_agents.registry import ExternalAgentRegistry
import yaml

class TestExternalAgentRegistry(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        self.config_path = "config/test_external_agents.yml"
        Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
        
        config_data = {
            "external_agents": [
                {
                    "agent_id": "cline_codex",
                    "display_name": "Cline with Codex Subscription",
                    "type": "ide_agent",
                    "enabled": False,
                    "integration_mode": "handoff_only",
                    "capabilities": ["repo_edit", "code_review", "terminal_assisted_validation", "large_context_reasoning"],
                    "billing": {"mode": "subscription_quota", "api_cost_visible": False, "token_visibility": "unknown"},
                    "risk": {"level": "medium", "requires_user_trigger": True, "requires_result_evidence": True},
                    "allowed_task_types": ["repo_patch", "repo_build_test", "architecture_review"]
                },
                {
                    "agent_id": "ecc_pack",
                    "display_name": "Everything Claude Code / ECC Skill Pack",
                    "type": "external_agent_pack",
                    "enabled": False,
                    "integration_mode": "handoff_only",
                    "capabilities": ["planning", "code_review", "security_review", "harness_optimization"],
                    "billing": {"mode": "external_harness", "api_cost_visible": False, "token_visibility": "unknown"},
                    "risk": {"level": "high", "requires_user_trigger": True, "requires_skill_approval": True, "requires_result_evidence": True},
                    "allowed_task_types": ["repo_patch", "security_review", "implementation_plan"]
                }
            ]
        }
        
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(config_data, f)
            
        self.registry = ExternalAgentRegistry(self.config_path)
    
    def test_agents_default_disabled(self):
        agents = self.registry.list_agents()
        for agent in agents:
            self.assertFalse(agent['enabled'])
    
    def test_agent_validation_token_visibility(self):
        agents = self.registry.list_agents()
        for agent in agents:
            self.assertEqual(agent['billing']['token_visibility'], 'unknown')
            self.assertEqual(agent['integration_mode'], 'handoff_only')
    
    def test_agent_list_count(self):
        self.assertEqual(len(self.registry.list_agents()), 2)
    
    def test_get_agent_by_id(self):
        cline = self.registry.get_agent("cline_codex")
        self.assertIsNotNone(cline)
        self.assertEqual(cline["type"], "ide_agent")
        ecc = self.registry.get_agent("ecc_pack")
        self.assertIsNotNone(ecc)
        self.assertEqual(ecc["type"], "external_agent_pack")
    
    def test_agent_not_found(self):
        self.assertIsNone(self.registry.get_agent("non_existent"))
    
    def test_is_agent_enabled(self):
        self.assertFalse(self.registry.is_agent_enabled("cline_codex"))
        self.assertFalse(self.registry.is_agent_enabled("ecc_pack"))
        self.assertFalse(self.registry.is_agent_enabled("non_existent"))

if __name__ == '__main__':
    unittest.main()