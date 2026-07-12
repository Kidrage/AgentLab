from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.capability_broker.broker_registry import BrokerRegistry
from agent_runtime.capability_broker.brokered_invocation import invoke_brokered_provider
from agent_runtime.capability_broker.capability_provider import CapabilityProvider
from agent_runtime.capability_broker.delegated_capability import (
    invoke_delegated_capability,
)
from agent_runtime.capability_broker.mcp_discovery import discover_worker_mcps
from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.provider_routing import route_capability
from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy
from agent_runtime.capability_broker.skill_discovery import discover_worker_skills
from agent_runtime.run_task import app


ROOT = Path(__file__).resolve().parents[1]


def test_safe_local_capability_discovery() -> None:
    mcp = discover_worker_mcps("claude_code", safe=True)
    skills = discover_worker_skills("claude_code", safe=True)

    assert len(mcp) == 1
    assert mcp[0].provider_id == "claude_local_mcp_fs"
    assert "filesystem_read" in mcp[0].canonical_capabilities
    assert mcp[0].trust_level == "provisional"
    assert len(skills) == 1
    assert skills[0].provider_id == "claude_local_skill_code_review"
    assert "code_review" in skills[0].canonical_capabilities
    assert skills[0].trust_level == "provisional"
    assert discover_worker_skills("claude_code", safe=False)[0].trust_level == "untrusted"


def test_capability_schema_and_cli() -> None:
    schema = CapabilitySchema.load_from_file(ROOT / "config" / "capability_schema.yml")
    planning = schema.get_capability("planning")
    cloud_upload = schema.get_capability("cloud_upload")

    assert planning is not None
    assert planning.display_name == "Planning"
    assert planning.risk_level == "medium"
    assert cloud_upload is not None
    assert cloud_upload.risk_level == "high"
    assert len(schema.list_capabilities()) >= 25

    result = CliRunner().invoke(app, ["capabilities"])
    assert result.exit_code == 0
    assert "Planning" in result.stdout
    assert "Cloud Upload" in result.stdout


def test_provider_passport_round_trip() -> None:
    passport = CapabilityProviderPassport.from_dict(
        {
            "provider_id": "test_provider",
            "provider_type": "agentlab_owned_tool",
            "source": "agentlab_owned",
            "canonical_capabilities": ["read_only_repo_search"],
            "transparency": "transparent",
            "invocation_mode": "direct",
            "permissions": {
                "filesystem_read": "scoped",
                "filesystem_write": "none",
                "shell": "limited",
                "network": "no",
                "cloud_upload": "no",
            },
            "risk_level": "low",
            "cost_model": {
                "known": True,
                "attribution": "provider_level",
                "estimated_usd": 0.0,
                "estimated_tokens": 0,
            },
            "verification": {"probe_available": True, "audition_required": False},
            "trust_level": "trusted",
        }
    )

    assert passport.provider_id == "test_provider"
    assert passport.permissions.filesystem_read == "scoped"
    assert passport.cost_model.known is True
    assert passport.verification.probe_available is True
    assert passport.trust_level == "trusted"
    serialized = passport.to_dict()
    assert serialized["provider_id"] == "test_provider"
    assert serialized["permissions"]["filesystem_read"] == "scoped"


def test_capability_routing_success_and_failure() -> None:
    registry = BrokerRegistry()
    registry.register_passport(
        CapabilityProviderPassport(
            provider_id="claude_local_skill_code_review",
            provider_type="worker_local_skill",
            source="discovered",
            canonical_capabilities=["code_review"],
            risk_level="low",
            trust_level="provisional",
        )
    )

    provider, decision = route_capability(
        "code_review",
        registry,
        ProviderTrustPolicy(),
    )
    assert provider is not None
    assert provider.provider_id == "claude_local_skill_code_review"
    assert decision["status"] == "success"

    missing, failed = route_capability("unknown_cap", registry, ProviderTrustPolicy())
    assert missing is None
    assert failed["status"] == "failed"


def test_provider_trust_policy_and_report() -> None:
    policy = ProviderTrustPolicy()
    providers = [
        CapabilityProvider(
            CapabilityProviderPassport(
                provider_id="rs",
                provider_type="agentlab_owned_tool",
                source="agentlab_owned",
                risk_level="low",
            )
        ),
        CapabilityProvider(
            CapabilityProviderPassport(
                provider_id="bad",
                provider_type="worker_local_skill",
                source="discovered",
                risk_level="critical",
            )
        ),
        CapabilityProvider(
            CapabilityProviderPassport(
                provider_id="ok",
                provider_type="worker_local_skill",
                source="discovered",
                risk_level="low",
            )
        ),
        CapabilityProvider(
            CapabilityProviderPassport(
                provider_id="unsafe",
                provider_type="worker_local_skill",
                source="discovered",
                risk_level="high",
            )
        ),
    ]

    assert [policy.evaluate_trust(provider) for provider in providers] == [
        "trusted",
        "disabled",
        "provisional",
        "provisional",
    ]
    report = policy.generate_trust_report(providers)
    assert "Provider Trust Report" in report
    assert "rs" in report
    assert "bad" in report


def test_delegated_worker_capability_returns_owner_evidence() -> None:
    provider = CapabilityProvider(
        CapabilityProviderPassport(
            provider_id="claude_local_skill_code_review",
            provider_type="worker_local_skill",
            owner_worker="claude_code",
            source="discovered",
            invocation_mode="delegated_worker",
            risk_level="low",
            trust_level="provisional",
        )
    )

    result = invoke_delegated_capability(provider, "code_review", {"repo": "agentlab"})

    assert result["success"] is True
    assert result["evidence"]["owner_worker"] == "claude_code"


def test_brokered_provider_allows_medium_and_blocks_critical_risk() -> None:
    provider = CapabilityProvider(
        CapabilityProviderPassport(
            provider_id="test_mcp",
            provider_type="agentlab_brokered_mcp",
            source="discovered",
            invocation_mode="brokered_mcp",
            risk_level="medium",
        )
    )
    result = invoke_brokered_provider(provider, "filesystem_read", {"path": "/tmp"})
    assert result["success"] is True
    assert result["evidence"]["provider_id"] == "test_mcp"

    critical = CapabilityProvider(
        CapabilityProviderPassport(
            provider_id="test_mcp_crit",
            provider_type="agentlab_brokered_mcp",
            source="discovered",
            invocation_mode="brokered_mcp",
            risk_level="critical",
        )
    )
    with pytest.raises(PermissionError):
        invoke_brokered_provider(critical, "filesystem_write", {"path": "/tmp"})
