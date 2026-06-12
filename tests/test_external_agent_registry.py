import unittest
import yaml
from pathlib import Path
from agent_runtime.external_agents.registry import ExternalAgentRegistry

class TestExternalAgentRegistry(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        # Create a test config file
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
                    "billing": {
                        "mode": "subscription_quota",
                        "api_cost_visible": False,
                        "token_visibility": "unknown"
                    },
                    "risk": {
                        "level": "medium",
                        "requires_user_trigger": True,
                        "requires_result_evidence": True
                    },
                    "allowed_task_types": ["repo_patch", "repo_build_test", "architecture_review"]
                },
                {
                    "agent_id": "ecc_pack",
                    "display_name": "Everything Claude Code / ECC Skill Pack",
                    "type": "external_agent_pack",
                    "enabled": False,
                    "integration_mode": "handoff_only",
                    "capabilities": ["planning", "code_review", "security_review", "harness_optimization"],
                    "billing": {
                        "mode": "external_harness",
                        "api_cost_visible": False,
                        "token_visibility": "unknown"
                    },
                    "risk": {
                        "level": "high",
                        "requires_user_trigger": True,
                        "requires_skill_approval": True,
                        "requires_result_evidence": True
                    },
                    "allowed_task_types": ["repo_patch", "security_review", "implementation_plan"]
                }
            ]
        }
        
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(config_data, f)
            
        self.registry = ExternalAgentRegistry(self.config_path)
    
    def test_agents_default_disabled(self):
        """Test that all external agents are disabled by default"""
        agents = self.registry.list_agents()
        for agent in agents:
            self.assertFalse(agent['enabled'], f"Agent {agent['agent_id']} should be disabled by default")
    
    def test_agent_validation(self):
        """Test agent validation constraints"""
        # Test token visibility
        agents = self.registry.list_agents()
        for agent in agents:
            self.assertEqual(agent['billing']['token_visibility'], 'unknown', 
                           f"Agent {agent['agent_id']} token_visibility should be 'unknown'")
            
        # Test integration mode
        for agent in agents:
            self.assertEqual(agent['integration_mode'], 'handoff_only',
                           f"Agent {agent['agent_id']} integration_mode should be 'handoff_only'")
    
    def test_agent_capabilities(self):
        """Test agent capabilities are properly loaded"""
        cline_agent = self.registry.get_agent("cline_codex")
        self.assertIsNotNone(cline_agent)
        self.assertIn("repo_edit", cline_agent["capabilities"])
        self.assertIn("code_review", cline_agent["capabilities"])
        
        ecc_agent = self.registry.get_agent("ecc_pack")
        self.assertIsNotNone(ecc_agent)
        self.assertIn("planning", ecc_agent["capabilities"])
        self.assertIn("security_review", ecc_agent["capabilities"])
    
    def test_agent_risk_constraints(self):
        """Test agent risk constraints are properly loaded"""
        ecc_agent = self.registry.get_agent("ecc_pack")
        self.assertIsNotNone(ecc_agent)
        self.assertTrue(ecc_agent["risk"]["requires_user_trigger"])
        self.assertTrue(ecc_agent["risk"]["requires_skill_approval"])
        self.assertTrue(ecc_agent["risk"]["requires_result_evidence"])
    
    def test_agent_not_found(self):
        """Test getting non-existent agent returns None"""
        self.assertIsNone(self.registry.get_agent("non_existent_agent"))

if __name__ == '__main__':
    unittest.main()