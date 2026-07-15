from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
import pytest

from agent_runtime.model_capacity import (
    CapacityPolicyError,
    ModelCapacity,
    UnsafeCapacityProbeError,
)
from agent_runtime.config_loader import load_agentlab_configs


NOW = datetime(2026, 7, 13, 4, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _policy() -> dict:
    return {
        "schema_version": 1,
        "canary_lease_seconds": 300,
        "pools": {
            "shared_oauth": {
                "probe": ["hermes", "auth", "status", "openai-codex"],
            },
            "fallback_oauth": {"probe": ["agy", "models"]},
        },
        "routes": {
            "primary": {
                "role": "observer",
                "pool": "shared_oauth",
                "approved_fallbacks": ["fallback"],
                "fallback_on": [
                    "rate_limited",
                    "quota_exhausted",
                    "auth_missing",
                    "model_unavailable",
                ],
            },
            "same_pool": {
                "role": "observer",
                "pool": "shared_oauth",
                "approved_fallbacks": [],
            },
            "fallback": {
                "role": "observer",
                "pool": "fallback_oauth",
                "approved_fallbacks": [],
            },
        },
    }


def _multihop_policy() -> dict:
    policy = _policy()
    for pool_id in ("max_pool", "plus_pool", "low_pool"):
        policy["pools"][pool_id] = {
            "provider": "dashscope_cn",
            "probe": None,
        }
    policy["routes"] = {
        "ArtifactProducerQwenMax": {
            "role": "artifact_producer",
            "worker": "qwen",
            "invocation_contract": "qwen_artifact",
            "model_key": "qwen_max",
            "pool": "max_pool",
            "input_modalities": ["text", "spreadsheet", "presentation"],
            "approved_fallbacks": ["ArtifactProducerQwenPlus"],
            "fallback_on": ["model_unavailable"],
        },
        "ArtifactProducerQwenPlus": {
            "role": "artifact_producer",
            "worker": "qwen",
            "invocation_contract": "qwen_artifact",
            "model_key": "qwen_plus",
            "pool": "plus_pool",
            "input_modalities": ["text", "spreadsheet", "presentation"],
            "approved_fallbacks": ["ArtifactProducerQwenLow"],
            "fallback_on": ["model_unavailable"],
        },
        "ArtifactProducerQwenLow": {
            "role": "artifact_producer",
            "worker": "qwen",
            "invocation_contract": "qwen_artifact",
            "model_key": "qwen_low",
            "pool": "low_pool",
            "input_modalities": ["text", "spreadsheet", "presentation"],
            "approved_fallbacks": [],
            "fallback_on": [],
        },
    }
    return policy


def test_quarantined_capacity_route_fails_closed(tmp_path):
    policy = _policy()
    policy["routes"]["primary"]["status"] = "quarantined"
    policy["routes"]["primary"]["automatic_use"] = False
    policy["routes"]["primary"]["explicit_canary_allowed"] = True
    capacity = ModelCapacity(policy, tmp_path / "capacity.yml", clock=lambda: NOW)

    decision = capacity.select_route("primary", role="observer", attempt_id="quarantine")

    assert decision["status"] == "blocked"
    assert decision["route_id"] is None
    assert decision["failure_class"] == "route_quarantined"


def test_quarantined_capacity_route_requires_policy_opt_in_for_explicit_canary(tmp_path):
    policy = _policy()
    route = policy["routes"]["primary"]
    route["status"] = "quarantined"
    route["automatic_use"] = False
    capacity = ModelCapacity(policy, tmp_path / "capacity.yml", clock=lambda: NOW)

    blocked = capacity.select_route(
        "primary",
        role="observer",
        attempt_id="undeclared-canary",
        explicit_canary=True,
    )
    route["explicit_canary_allowed"] = True
    selected = ModelCapacity(
        policy, tmp_path / "declared.yml", clock=lambda: NOW
    ).select_route(
        "primary",
        role="observer",
        attempt_id="declared-canary",
        explicit_canary=True,
    )

    assert blocked["status"] == "blocked"
    assert blocked["failure_class"] == "route_quarantined"
    assert selected["status"] == "selected"
    assert selected["route_id"] == "primary"
    assert selected["selection_mode"] == "explicit_canary"


def test_retry_after_failure_is_classified_and_persisted_atomically(tmp_path):
    ledger_path = tmp_path / "run" / "model_capacity_ledger.yml"
    capacity = ModelCapacity(_policy(), ledger_path, clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="HTTP 429 Too Many Requests",
        headers={"Retry-After": "120", "X-RateLimit-Remaining": "0"},
        attempt_id="attempt-1",
    )

    assert observation == {
        "source_kind": "provider_header",
        "observed_at": "2026-07-13T04:00:00Z",
        "expires_at": "2026-07-13T04:02:00Z",
        "reset_at": "2026-07-13T04:02:00Z",
        "remaining": 0,
        "confidence": "high",
        "attempt_id": "attempt-1",
        "failure_class": "rate_limited",
    }
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert ledger["pools"]["shared_oauth"]["observations"][-1] == observation
    assert ledger["pools"]["shared_oauth"]["remaining"] == 0
    assert not ledger_path.with_suffix(".yml.tmp").exists()


def test_provider_reset_duration_is_parsed_without_inventing_remaining(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="Subscription quota exhausted. Resets in 1h2m3s",
        attempt_id="attempt-2",
    )

    assert observation["failure_class"] == "quota_exhausted"
    assert observation["source_kind"] == "provider_message"
    assert observation["reset_at"] == "2026-07-13T05:02:03Z"
    assert observation["expires_at"] == observation["reset_at"]
    assert observation["remaining"] is None
    assert observation["confidence"] == "high"


def test_auth_and_model_failures_are_distinct_and_keep_unknown_times_null(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    auth = capacity.record_failure(
        "primary",
        message="xAI OAuth missing access_token; login required",
        attempt_id="auth-attempt",
    )
    unavailable = capacity.record_failure(
        "fallback",
        message="Requested model is not available for this account",
        attempt_id="model-attempt",
    )

    assert auth["failure_class"] == "auth_missing"
    assert unavailable["failure_class"] == "model_unavailable"
    for observation in (auth, unavailable):
        assert observation["reset_at"] is None
        assert observation["expires_at"] is None
        assert observation["remaining"] is None
        assert observation["confidence"] == "unknown"


def test_pool_breaker_blocks_every_route_in_pool_and_uses_approved_fallback(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "primary",
        message="rate limit; Resets in 10m",
        attempt_id="failed-attempt",
    )

    direct = capacity.select_route("same_pool", role="observer", attempt_id="attempt-3")
    fallback = capacity.select_route("primary", role="observer", attempt_id="attempt-4")

    assert direct["status"] == "blocked"
    assert direct["route_id"] is None
    assert direct["reset_at"] == "2026-07-13T04:10:00Z"
    assert direct["remaining"] is None
    assert fallback == {
        "status": "selected",
        "route_id": "fallback",
        "route_chain": ["primary", "fallback"],
        "pool_id": "fallback_oauth",
        "capacity_status": "unknown",
        "selection_kind": "approved_fallback",
        "attempt_id": "attempt-4",
    }


def test_unknown_or_cross_role_fallback_is_rejected_instead_of_silently_used(tmp_path):
    unknown = _policy()
    unknown["routes"]["primary"]["approved_fallbacks"] = ["not-declared"]
    with pytest.raises(CapacityPolicyError, match="unknown fallback"):
        ModelCapacity(unknown, tmp_path / "unknown.yml", clock=lambda: NOW).select_route(
            "primary", role="observer", attempt_id="attempt-5"
        )

    cross_role = _policy()
    cross_role["routes"]["fallback"]["role"] = "writer"
    with pytest.raises(CapacityPolicyError, match="changes role"):
        ModelCapacity(cross_role, tmp_path / "role.yml", clock=lambda: NOW).select_route(
            "primary", role="observer", attempt_id="attempt-6"
        )


def test_expired_breaker_grants_one_canary_lease_until_success_closes_it(tmp_path):
    current = [NOW]
    ledger_path = tmp_path / "ledger.yml"
    capacity = ModelCapacity(_policy(), ledger_path, clock=lambda: current[0])
    capacity.record_failure(
        "primary",
        message="rate limited; Resets in 10m",
        attempt_id="failed-attempt",
    )
    current[0] += timedelta(minutes=10)

    canary = capacity.select_route("primary", role="observer", attempt_id="canary-attempt")
    competing = capacity.select_route("same_pool", role="observer", attempt_id="other-attempt")

    assert canary["route_id"] == "primary"
    assert canary["capacity_status"] == "canary"
    assert competing["status"] == "blocked"
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert ledger["pools"]["shared_oauth"]["canary_lease"]["attempt_id"] == "canary-attempt"
    lease_expires_at = ledger["pools"]["shared_oauth"]["canary_lease"]["expires_at"]
    current[0] += timedelta(minutes=1)
    capacity.select_route("primary", role="observer", attempt_id="canary-attempt")
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert ledger["pools"]["shared_oauth"]["canary_lease"]["expires_at"] == lease_expires_at

    success = capacity.record_success("primary", attempt_id="canary-attempt")
    assert success["failure_class"] is None
    selected = capacity.select_route("same_pool", role="observer", attempt_id="after-success")
    assert selected["capacity_status"] == "available"


def test_concurrent_expired_breaker_grants_exactly_one_canary(tmp_path):
    current = NOW + timedelta(minutes=10)
    ledger_path = tmp_path / "ledger.yml"
    initial = ModelCapacity(_policy(), ledger_path, clock=lambda: NOW)
    initial.record_failure(
        "primary",
        message="rate limited; Resets in 10m",
        attempt_id="failed-attempt",
    )

    def select(attempt_id: str) -> dict:
        return ModelCapacity(
            _policy(), ledger_path, clock=lambda: current
        ).select_route("same_pool", role="observer", attempt_id=attempt_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(select, [f"canary-{index}" for index in range(8)]))

    selected = [item for item in decisions if item["status"] == "selected"]
    blocked = [item for item in decisions if item["status"] == "blocked"]
    assert len(selected) == 1
    assert selected[0]["capacity_status"] == "canary"
    assert len(blocked) == 7
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert ledger["pools"]["shared_oauth"]["canary_lease"]["attempt_id"] == selected[0]["attempt_id"]


def test_model_unavailable_canary_releases_its_lease_for_same_pool_fallback(tmp_path):
    current = [NOW]
    policy = _multihop_policy()
    for route in policy["routes"].values():
        route["pool"] = "shared_qwen_pool"
    policy["pools"]["shared_qwen_pool"] = {}
    capacity = ModelCapacity(
        policy,
        tmp_path / "ledger.yml",
        clock=lambda: current[0],
    )
    capacity.record_failure(
        "ArtifactProducerQwenMax",
        message="rate limited; Resets in 10m",
        attempt_id="quota-failure",
    )
    current[0] += timedelta(minutes=10)
    canary = capacity.select_route(
        "ArtifactProducerQwenMax",
        role="ArtifactProducer",
        attempt_id="max-canary",
    )
    assert canary["route_id"] == "ArtifactProducerQwenMax"
    assert canary["capacity_status"] == "canary"

    capacity.record_failure(
        "ArtifactProducerQwenMax",
        message="requested model is unavailable",
        attempt_id="max-canary",
    )
    released = yaml.safe_load((tmp_path / "ledger.yml").read_text(encoding="utf-8"))
    assert released["pools"]["shared_qwen_pool"]["status"] == "open"
    assert released["pools"]["shared_qwen_pool"]["canary_lease"] is None
    fallback = capacity.select_route(
        "ArtifactProducerQwenMax",
        role="ArtifactProducer",
        attempt_id="plus-attempt",
    )

    assert fallback["route_id"] == "ArtifactProducerQwenPlus"
    assert fallback["route_chain"] == [
        "ArtifactProducerQwenMax",
        "ArtifactProducerQwenPlus",
    ]
    assert fallback["capacity_status"] == "canary"
    ledger = yaml.safe_load((tmp_path / "ledger.yml").read_text(encoding="utf-8"))
    assert ledger["pools"]["shared_qwen_pool"]["status"] == "canary"
    assert ledger["pools"]["shared_qwen_pool"]["canary_lease"]["attempt_id"] == "plus-attempt"


def test_safe_probe_allowlist_executes_only_models_and_provider_scoped_auth_status(tmp_path):
    calls = []

    def runner(command):
        calls.append(command)
        return {"returncode": 0, "stdout": "logged in", "stderr": ""}

    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)
    result = capacity.probe("shared_oauth", runner=runner, attempt_id="probe-1")
    assert calls == [("hermes", "auth", "status", "openai-codex")]
    assert result["status"] == "unknown"
    assert result["capacity_status"] == "unknown"
    assert result["observation"]["source_kind"] == "safe_probe"

    poisoned = _policy()
    poisoned["pools"]["shared_oauth"]["probe"] = ["hermes", "status", "--all"]
    unsafe = ModelCapacity(poisoned, tmp_path / "unsafe.yml", clock=lambda: NOW)
    with pytest.raises(UnsafeCapacityProbeError, match="forbidden"):
        unsafe.probe("shared_oauth", runner=runner, attempt_id="probe-2")
    assert len(calls) == 1


def test_model_unavailable_blocks_only_that_route_not_its_shared_pool(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "primary",
        message="model gemini-example is unavailable",
        attempt_id="model-failure",
    )

    sibling = capacity.select_route("same_pool", role="observer", attempt_id="sibling-attempt")
    replacement = capacity.select_route("primary", role="observer", attempt_id="fallback-attempt")

    assert sibling["route_id"] == "same_pool"
    assert sibling["capacity_status"] == "unknown"
    assert replacement["route_id"] == "fallback"
    ledger = yaml.safe_load((tmp_path / "ledger.yml").read_text(encoding="utf-8"))
    assert ledger["routes"]["primary"]["failure_class"] == "model_unavailable"
    assert "shared_oauth" not in ledger.get("pools", {})


def test_retry_after_http_date_is_supported(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="HTTP 429 Too Many Requests",
        headers={"retry-after": "Mon, 13 Jul 2026 04:03:00 GMT"},
        attempt_id="http-date",
    )

    assert observation["source_kind"] == "provider_header"
    assert observation["reset_at"] == "2026-07-13T04:03:00Z"


def test_declared_window_never_invents_reset_when_provider_reports_none(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="subscription quota exhausted",
        attempt_id="declared-window",
    )

    assert observation["source_kind"] == "runtime_failure"
    assert observation["reset_at"] is None
    assert observation["expires_at"] is None
    assert observation["remaining"] is None
    assert observation["confidence"] == "unknown"


def test_repository_policy_declares_safe_pools_routes_and_unknown_quota_values(tmp_path):
    policy = yaml.safe_load((ROOT / "config" / "model_capacity.yml").read_text(encoding="utf-8"))
    capacity = ModelCapacity(policy, tmp_path / "ledger.yml", clock=lambda: NOW)

    for pool_id in ("agy_gemini_observer", "agy_claude_observer"):
        pool = policy["pools"][pool_id]
        assert pool["declared_windows"]["rolling"]["period_seconds"] == 18_000
        assert pool["declared_windows"]["weekly"]["period_seconds"] == 604_800
        assert pool["declared_windows"]["weekly"]["limit"] is None
        assert pool["declared_windows"]["weekly"]["remaining"] is None
        assert pool["declared_windows"]["weekly"]["reset_at"] is None

    for pool_id, pool in policy["pools"].items():
        if pool.get("probe") is not None:
            capacity.safe_probe_command(pool_id)
    assert ["hermes", "status", "--all"] in policy["probe_policy"]["forbidden_commands"]

    for route in policy["routes"].values():
        for fallback_id in route["approved_fallbacks"]:
            assert policy["routes"][fallback_id]["role"] == route["role"]
    writer = policy["routes"]["Writer"]
    writer_fallback = policy["routes"][writer["approved_fallbacks"][0]]
    assert writer["fallback_on"] == ["model_unavailable"]
    assert writer_fallback["pool"] == writer["pool"]
    artifact = policy["routes"]["ArtifactProducer"]
    assert artifact["pool"] == "xai_subscription_shared"
    assert artifact["approved_fallbacks"] == []


def test_capacity_policy_is_available_through_the_canonical_config_loader():
    loaded = load_agentlab_configs(ROOT)

    assert loaded["model_capacity"]["routes"]["Writer"]["pool"] == "deepseek_metered_api"


def test_fallback_requires_both_an_approved_route_and_failure_class(tmp_path):
    policy = _policy()
    policy["routes"]["primary"]["fallback_on"] = ["quota_exhausted"]

    auth_capacity = ModelCapacity(policy, tmp_path / "auth.yml", clock=lambda: NOW)
    auth_capacity.record_failure(
        "primary", message="not logged in", attempt_id="auth-failure"
    )
    auth_decision = auth_capacity.select_route(
        "primary", role="observer", attempt_id="auth-selection"
    )
    assert auth_decision["status"] == "blocked"
    assert auth_decision["route_id"] is None

    quota_capacity = ModelCapacity(policy, tmp_path / "quota.yml", clock=lambda: NOW)
    quota_capacity.record_failure(
        "primary", message="quota exhausted; Resets in 1h", attempt_id="quota-failure"
    )
    quota_decision = quota_capacity.select_route(
        "primary", role="observer", attempt_id="quota-selection"
    )
    assert quota_decision["route_id"] == "fallback"


def test_logged_out_probe_is_auth_missing_even_when_command_exits_zero(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    result = capacity.probe(
        "shared_oauth",
        runner=lambda _command: {
            "returncode": 0,
            "stdout": "openai-codex: logged out",
            "stderr": "",
        },
        attempt_id="logged-out-probe",
    )

    assert result["status"] == "blocked"
    assert result["observation"]["failure_class"] == "auth_missing"
    assert result["observation"]["reset_at"] is None


def test_retry_after_in_provider_message_overrides_declared_cooldown(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="Codex provider quota exhausted; retry after 90s",
        attempt_id="message-retry-after",
    )

    assert observation["source_kind"] == "provider_message"
    assert observation["reset_at"] == "2026-07-13T04:01:30Z"
    assert observation["confidence"] == "high"


def test_unclassified_probe_failure_stays_unknown_and_does_not_open_breaker(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)
    result = capacity.probe(
        "shared_oauth",
        runner=lambda _command: {
            "returncode": 1,
            "stdout": "",
            "stderr": "temporary transport failure",
        },
        attempt_id="unknown-probe",
    )

    assert result["status"] == "unknown"
    assert result["observation"]["failure_class"] == "unknown"
    decision = capacity.select_route("primary", role="observer", attempt_id="after-unknown")
    assert decision["route_id"] == "primary"
    assert decision["capacity_status"] == "unknown"


def test_non_consuming_probe_does_not_clear_an_active_quota_breaker(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "primary", message="quota exhausted; Resets in 1h", attempt_id="quota"
    )

    result = capacity.probe(
        "shared_oauth",
        runner=lambda _command: {"returncode": 0, "stdout": "logged in", "stderr": ""},
        attempt_id="auth-probe",
    )

    assert result["status"] == "blocked"
    decision = capacity.select_route("same_pool", role="observer", attempt_id="still-blocked")
    assert decision["status"] == "blocked"
    assert decision["failure_class"] == "quota_exhausted"


def test_role_comparison_accepts_canonical_case_but_not_a_different_role(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    decision = capacity.select_route("primary", role="Observer", attempt_id="casefolded")

    assert decision["route_id"] == "primary"


def test_retry_after_header_is_a_rate_limit_signal_when_body_is_generic(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="request rejected",
        headers={"Retry-After": "60"},
        attempt_id="generic-429",
    )

    assert observation["failure_class"] == "rate_limited"
    decision = capacity.select_route("same_pool", role="observer", attempt_id="header-block")
    assert decision["status"] == "blocked"


def test_cli_auth_required_class_opens_pool_for_approved_same_role_fallback(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "ledger.yml", clock=lambda: NOW)

    observation = capacity.record_failure(
        "primary",
        message="CLI agent auth_required (exit 1)",
        attempt_id="auth-class",
    )
    decision = capacity.select_route("primary", role="Observer", attempt_id="fallback")

    assert observation["failure_class"] == "auth_missing"
    assert decision["route_id"] == "fallback"


def test_observer_fallback_cannot_drop_required_media_modalities(tmp_path):
    policy = _policy()
    policy["routes"]["primary"]["input_modalities"] = [
        "text", "image", "video", "audio", "pdf"
    ]
    policy["routes"]["fallback"]["input_modalities"] = ["text", "image", "pdf"]
    capacity = ModelCapacity(policy, tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "primary",
        message="quota exhausted; Resets in 1h",
        attempt_id="primary-quota",
    )

    decision = capacity.select_route(
        "primary",
        role="Observer",
        attempt_id="video-fallback",
        required_modalities=["text", "video"],
    )

    assert decision["status"] == "blocked"
    assert decision["route_id"] is None
    assert decision["incompatible_fallbacks"] == [
        {"route_id": "fallback", "missing_modalities": ["video"]}
    ]


def test_multihop_fallback_selects_the_first_eligible_declared_descendant(tmp_path):
    policy = _multihop_policy()
    capacity = ModelCapacity(policy, tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "ArtifactProducerQwenMax",
        message="requested model is unavailable",
        attempt_id="max-failure",
    )
    capacity.record_failure(
        "ArtifactProducerQwenPlus",
        message="requested model is unavailable",
        attempt_id="plus-failure",
    )

    decision = capacity.select_route(
        "ArtifactProducerQwenMax",
        role="ArtifactProducer",
        attempt_id="low-attempt",
        required_modalities=["spreadsheet"],
    )

    assert decision == {
        "status": "selected",
        "route_id": "ArtifactProducerQwenLow",
        "route_chain": [
            "ArtifactProducerQwenMax",
            "ArtifactProducerQwenPlus",
            "ArtifactProducerQwenLow",
        ],
        "pool_id": "low_pool",
        "capacity_status": "unknown",
        "selection_kind": "approved_fallback",
        "attempt_id": "low-attempt",
    }


def test_fallback_cycle_fails_closed_with_the_declared_cycle_path(tmp_path):
    policy = _policy()
    policy["routes"]["fallback"]["approved_fallbacks"] = ["primary"]
    policy["routes"]["fallback"]["fallback_on"] = ["model_unavailable"]
    ledger_path = tmp_path / "ledger.yml"

    decision = ModelCapacity(policy, ledger_path, clock=lambda: NOW).select_route(
        "primary",
        role="Observer",
        attempt_id="cycle-attempt",
    )

    assert decision == {
        "status": "blocked",
        "route_id": None,
        "route_chain": ["primary", "fallback", "primary"],
        "pool_id": "fallback_oauth",
        "capacity_status": "blocked",
        "failure_class": "invalid_fallback_cycle",
        "reset_at": None,
        "attempt_id": "cycle-attempt",
    }
    assert not ledger_path.exists()


def test_each_fallback_edge_requires_its_predecessors_current_failure_class(tmp_path):
    policy = _multihop_policy()
    capacity = ModelCapacity(policy, tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "ArtifactProducerQwenMax",
        message="requested model is unavailable",
        attempt_id="max-failure",
    )
    capacity.record_failure(
        "ArtifactProducerQwenPlus",
        message="HTTP 429 rate limited; Resets in 10m",
        attempt_id="plus-failure",
    )

    decision = capacity.select_route(
        "ArtifactProducerQwenMax",
        role="ArtifactProducer",
        attempt_id="blocked-attempt",
        required_modalities=["spreadsheet"],
    )

    assert decision["status"] == "blocked"
    assert decision["route_id"] is None
    assert decision["route_chain"] == [
        "ArtifactProducerQwenMax",
        "ArtifactProducerQwenPlus",
    ]
    assert decision["pool_id"] == "plus_pool"
    assert decision["failure_class"] == "rate_limited"
    assert "ArtifactProducerQwenLow" not in decision["route_chain"]
    assert decision["attempt_id"] == "blocked-attempt"


def test_multihop_fallback_does_not_traverse_through_an_incompatible_route(tmp_path):
    policy = _multihop_policy()
    policy["routes"]["ArtifactProducerQwenMax"]["input_modalities"].append("video")
    policy["routes"]["ArtifactProducerQwenLow"]["input_modalities"].append("video")
    policy["routes"]["ArtifactProducerQwenPlus"]["fallback_on"].append(
        "unsupported_modality"
    )
    capacity = ModelCapacity(policy, tmp_path / "ledger.yml", clock=lambda: NOW)
    capacity.record_failure(
        "ArtifactProducerQwenMax",
        message="requested model is unavailable",
        attempt_id="max-failure",
    )

    decision = capacity.select_route(
        "ArtifactProducerQwenMax",
        role="ArtifactProducer",
        attempt_id="video-attempt",
        required_modalities=["video"],
    )

    assert decision["status"] == "blocked"
    assert decision["route_chain"] == ["ArtifactProducerQwenMax"]
    assert decision["failure_class"] == "model_unavailable"
    assert decision["incompatible_fallbacks"] == [
        {
            "route_id": "ArtifactProducerQwenPlus",
            "missing_modalities": ["video"],
        }
    ]


def test_duplicate_fallback_declaration_fails_closed_before_capacity_selection(tmp_path):
    policy = _policy()
    policy["routes"]["primary"]["approved_fallbacks"] = ["fallback", "fallback"]
    ledger_path = tmp_path / "ledger.yml"

    decision = ModelCapacity(policy, ledger_path, clock=lambda: NOW).select_route(
        "primary",
        role="Observer",
        attempt_id="duplicate-attempt",
    )

    assert decision["status"] == "blocked"
    assert decision["route_chain"] == ["primary", "fallback"]
    assert decision["failure_class"] == "invalid_fallback_duplicate"
    assert decision["attempt_id"] == "duplicate-attempt"
    assert not ledger_path.exists()
