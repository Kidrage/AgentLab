from pathlib import Path

import yaml

from agent_runtime.governance.cost import build_provider_cost_profiles
from agent_runtime.governance.models import GovernanceInputBundle, ProviderPerformanceProfile
from agent_runtime.governance.performance import derive_governance_decisions
from agent_runtime.governance.policy import load_provider_governance_policy


def _policy():
    return load_provider_governance_policy(Path("config/provider_governance.yml"))


def _router(tmp_path: Path, provider_id: str, cost_mode: str) -> Path:
    path = tmp_path / "executor_router.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "executor_router": {
                    "providers": [{"provider_id": provider_id, "provider_type": "mock_executor", "cost_mode": cost_mode}],
                    "provider_priority": {},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cost_profile_free_low_risk(tmp_path: Path):
    profile = ProviderPerformanceProfile("p", "mock_executor", attempts=2)
    costs = build_provider_cost_profiles(GovernanceInputBundle(Path(".")), [profile], _policy(), _router(tmp_path, "p", "none"))
    assert costs[0].cost_risk_level == "low"


def test_cost_profile_unknown_requires_manual_approval(tmp_path: Path):
    profile = ProviderPerformanceProfile("p", "codex_cli", attempts=2, accepted=2, acceptance_rate=1.0, average_quality_score=1.0)
    costs = build_provider_cost_profiles(GovernanceInputBundle(Path(".")), [profile], _policy(), _router(tmp_path, "p", "unknown"))
    decision = derive_governance_decisions([profile], costs, _policy())[0]
    assert costs[0].requires_manual_approval is True
    assert decision.status == "MANUAL_APPROVAL_REQUIRED"


def test_manual_approval_unknown_cost(tmp_path: Path):
    profile = ProviderPerformanceProfile("manual.codex", "codex_cli", attempts=2, accepted=2, acceptance_rate=1.0, average_quality_score=1.0)
    costs = build_provider_cost_profiles(GovernanceInputBundle(Path(".")), [profile], _policy(), _router(tmp_path, "manual.codex", "subscription_or_credit_external"))
    decision = derive_governance_decisions([profile], costs, _policy())[0]
    assert decision.recommended_action == "require_manual_approval"


def test_cost_profile_estimated_cost_rollup(tmp_path: Path):
    bundle = GovernanceInputBundle(
        Path("."),
        retry_attempt_ledgers=[
            {
                "attempts": [
                    {"provider_id": "p", "estimated_cost_usd": 0.05},
                    {"provider_id": "p", "estimated_cost_usd": 0.10},
                ]
            }
        ],
    )
    profile = ProviderPerformanceProfile("p", "api_model", attempts=2)
    costs = build_provider_cost_profiles(bundle, [profile], _policy(), _router(tmp_path, "p", "api_model"))
    assert costs[0].estimated_total_cost_usd == 0.15
    assert costs[0].estimated_average_cost_usd == 0.075


def test_cost_governance_does_not_read_api_keys(tmp_path: Path):
    secret = tmp_path / "OPENAI_API_KEY"
    secret.write_text("should-not-be-read", encoding="utf-8")
    profile = ProviderPerformanceProfile("p", "api_model", attempts=2)
    costs = build_provider_cost_profiles(GovernanceInputBundle(Path(".")), [profile], _policy(), _router(tmp_path, "p", "api_model"))
    assert costs[0].cost_risk_level == "medium"
