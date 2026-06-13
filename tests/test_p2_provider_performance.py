from pathlib import Path

from agent_runtime.governance.models import GovernanceInputBundle
from agent_runtime.governance.performance import build_provider_performance_profiles, derive_governance_decisions
from agent_runtime.governance.policy import load_provider_governance_policy


def _policy():
    return load_provider_governance_policy(Path("config/provider_governance.yml"))


def _bundle(provider: dict, attempts: list[dict] | None = None) -> GovernanceInputBundle:
    return GovernanceInputBundle(
        root=Path("."),
        provider_scorecards={"providers": [provider]} if False else [{"providers": [provider]}],
        retry_attempt_ledgers=[{"attempts": attempts or []}],
    )


def _profile(provider: dict, attempts: list[dict] | None = None):
    return build_provider_performance_profiles(_bundle(provider, attempts), _policy())[0]


def test_build_provider_profile_acceptance_rate():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 4, "passes": 3, "total_quality_score": 3.0})
    assert profile.acceptance_rate == 0.75


def test_build_provider_profile_retry_rate():
    profile = _profile(
        {"provider_id": "p", "provider_type": "mock_executor", "attempts": 2, "passes": 1, "needs_revision": 1, "total_quality_score": 1.35},
        [{"provider_id": "p", "provider_type": "mock_executor", "retry_decision": "RETRY"}],
    )
    assert profile.retry_rate == 0.5


def test_build_provider_profile_blocked_rate():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 4, "blocked": 1, "passes": 3, "total_quality_score": 3.0})
    assert profile.blocked_rate == 0.25


def test_build_provider_profile_average_quality_score():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 2, "passes": 1, "needs_revision": 1})
    assert profile.average_quality_score == 0.675


def test_insufficient_data_profile():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 1, "passes": 1})
    decision = derive_governance_decisions([profile], [], _policy())[0]
    assert profile.trend == "insufficient_data"
    assert decision.status == "INSUFFICIENT_DATA"


def test_healthy_provider_decision():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 4, "passes": 4})
    assert derive_governance_decisions([profile], [], _policy())[0].status == "HEALTHY"


def test_watchlist_low_acceptance_rate():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 2, "passes": 0, "needs_revision": 1, "fails": 1})
    assert derive_governance_decisions([profile], [], _policy())[0].status == "WATCHLIST"


def test_watchlist_high_retry_rate():
    profile = _profile(
        {"provider_id": "p", "provider_type": "mock_executor", "attempts": 3, "passes": 3},
        [{"provider_id": "p", "retry_decision": "RETRY"}, {"provider_id": "p", "retry_decision": "RETRY"}],
    )
    assert derive_governance_decisions([profile], [], _policy())[0].status == "WATCHLIST"


def test_quarantine_repeated_blocked():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 3, "blocked": 1, "passes": 2})
    assert derive_governance_decisions([profile], [], _policy())[0].status == "QUARANTINE_RECOMMENDED"


def test_downgrade_low_quality_score():
    profile = _profile({"provider_id": "p", "provider_type": "mock_executor", "attempts": 2, "passes": 1, "fails": 1})
    assert derive_governance_decisions([profile], [], _policy())[0].status == "DOWNGRADED"
