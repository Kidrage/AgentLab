"""Capability provider class representing a functional tool, skill, or MCP server."""

from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport

class CapabilityProvider:
    def __init__(self, passport: CapabilityProviderPassport):
        self.passport = passport

    @property
    def provider_id(self) -> str:
        return self.passport.provider_id

    @property
    def risk_level(self) -> str:
        return self.passport.risk_level

    @property
    def trust_level(self) -> str:
        return self.passport.trust_level

    def is_eligible_for_project(self, project_id: str) -> bool:
        """Check if this provider is allowed to run on the project."""
        if self.passport.trust_level == "disabled":
            return False
        if self.passport.disabled_by_default and self.passport.trust_level != "trusted":
            return False
        if self.passport.allowed_projects and project_id not in self.passport.allowed_projects:
            return False
        return True

    def has_capability(self, capability: str) -> bool:
        """Check if this provider supplies the specified capability."""
        return capability in self.passport.canonical_capabilities

    def has_high_risk_permissions(self) -> bool:
        """Check if the provider requests high-risk capabilities (e.g. shell, filesystem write)."""
        perms = self.passport.permissions
        if perms.shell in ("possible", "full"):
            return True
        if perms.filesystem_write in ("possible", "full"):
            return True
        if perms.network == "yes":
            return True
        if perms.cloud_upload == "yes":
            return True
        if self.passport.risk_level in ("high", "critical"):
            return True
        return False
