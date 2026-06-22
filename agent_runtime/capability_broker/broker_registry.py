"""Registry for storing and querying capability providers and their passports."""

from pathlib import Path
import yaml
from typing import Dict, Any, List, Optional
from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.capability_provider import CapabilityProvider

# Standard AgentLab owned tools defaults
DEFAULT_PROVIDERS = {
    "agentlab_repo_scout_rg": {
        "provider_id": "agentlab_repo_scout_rg",
        "provider_type": "agentlab_owned_tool",
        "source": "agentlab_owned",
        "canonical_capabilities": ["read_only_repo_search", "grep_pattern"],
        "transparency": "transparent",
        "invocation_mode": "direct",
        "permissions": {
            "filesystem_read": "scoped",
            "filesystem_write": "none",
            "shell": "limited",
            "network": "no",
            "cloud_upload": "no"
        },
        "risk_level": "low",
        "cost_model": {
            "known": True,
            "attribution": "provider_level",
            "estimated_usd": 0.0,
            "estimated_tokens": 0
        },
        "verification": {
            "probe_available": True,
            "audition_required": False
        },
        "trust_level": "trusted"
    },
    "agentlab_test_runner_pytest": {
        "provider_id": "agentlab_test_runner_pytest",
        "provider_type": "agentlab_owned_tool",
        "source": "agentlab_owned",
        "canonical_capabilities": ["run_tests", "parse_test_failures"],
        "transparency": "transparent",
        "invocation_mode": "direct",
        "permissions": {
            "filesystem_read": "scoped",
            "filesystem_write": "none",
            "shell": "limited",
            "network": "no",
            "cloud_upload": "no"
        },
        "risk_level": "low",
        "cost_model": {
            "known": True,
            "attribution": "provider_level",
            "estimated_usd": 0.0,
            "estimated_tokens": 0
        },
        "verification": {
            "probe_available": True,
            "audition_required": False
        },
        "trust_level": "trusted"
    }
}

class BrokerRegistry:
    def __init__(self, config_path: Optional[Path] = None):
        self.providers: Dict[str, CapabilityProvider] = {}
        self._load_defaults()
        if config_path and config_path.exists():
            self.load_from_yaml(config_path)

    def _load_defaults(self):
        for pid, data in DEFAULT_PROVIDERS.items():
            self.register_passport(CapabilityProviderPassport.from_dict(data))

    def load_from_yaml(self, path: Path) -> None:
        """Load provider registry entries from a YAML file."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            providers_data = data.get("providers", {})
            for pid, pdata in providers_data.items():
                self.register_passport(CapabilityProviderPassport.from_dict(pdata))
        except Exception:
            pass

    def register_passport(self, passport: CapabilityProviderPassport) -> None:
        """Register a new capability provider passport in the registry."""
        self.providers[passport.provider_id] = CapabilityProvider(passport)

    def get_provider(self, provider_id: str) -> Optional[CapabilityProvider]:
        """Get a registered capability provider by its ID."""
        return self.providers.get(provider_id)

    def list_providers(self) -> List[CapabilityProvider]:
        """List all registered capability providers."""
        return list(self.providers.values())

    def get_providers_for_capability(self, capability: str) -> List[CapabilityProvider]:
        """Filter registered providers that support the specified capability."""
        return [p for p in self.providers.values() if p.has_capability(capability)]
