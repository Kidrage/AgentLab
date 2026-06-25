"""CLI command safety policy module."""

from dataclasses import dataclass

DANGEROUS_FLAGS = {
    "--allow-dangerously-skip-permissions",
}

@dataclass
class ProfileSafetyFinding:
    severity: str
    profile: str
    tier: str | None
    role: str | None
    flag: str
    message: str

def validate_cli_agent_profiles(profile_config: dict) -> list[ProfileSafetyFinding]:
    """Validate that dangerous CLI flags are only used in trusted profiles with env gates."""
    findings = []
    
    if not profile_config or "modes" not in profile_config:
        return findings
        
    for mode_name, mode_data in profile_config.get("modes", {}).items():
        safety_config = mode_data.get("safety", {})
        is_trusted = safety_config.get("requires_env", {}).get("AGENTLAB_ALLOW_DANGEROUS_CCS") == "1" \
                     and safety_config.get("requires_human_approval", False) \
                     and safety_config.get("never_default", False)
                     
        tiers = mode_data.get("tiers", {})
        for tier_name, tier_data in tiers.items():
            for role_name, role_data in tier_data.items():
                if not isinstance(role_data, dict):
                    continue
                    
                if role_data.get("executor_type") == "cli_agent":
                    cmd = role_data.get("cli_command", "")
                    for dangerous_flag in DANGEROUS_FLAGS:
                        if dangerous_flag in cmd:
                            if not is_trusted:
                                findings.append(
                                    ProfileSafetyFinding(
                                        severity="error",
                                        profile=mode_name,
                                        tier=tier_name,
                                        role=role_name,
                                        flag=dangerous_flag,
                                        message=f"Dangerous flag {dangerous_flag} found in non-trusted profile."
                                    )
                                )
    return findings
