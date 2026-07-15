from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from agent_runtime.model_capacity import ModelCapacity
from agent_runtime.quota_probes import QuotaProbeSpec, parse_quota_output


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _policy() -> dict:
    return {
        "quota_policy": {
            "hard_reserve_percent": 5,
            "stale_after_seconds": 600,
            "resume_jitter_seconds": [60, 180],
        },
        "pools": {
            "primary": {
                "quota_probe": {
                    "shell_id": "codex",
                    "argv": ["codex"],
                    "slash_command": "/usage",
                    "exit_command": "/exit",
                }
            },
            "fallback": {},
        },
        "routes": {
            "primary": {
                "role": "supervisor",
                "pool": "primary",
                "approved_fallbacks": ["fallback"],
                "fallback_on": ["quota_exhausted"],
            },
            "primary_direct": {
                "role": "supervisor",
                "pool": "primary",
                "approved_fallbacks": [],
                "fallback_on": [],
            },
            "fallback": {
                "role": "supervisor",
                "pool": "fallback",
                "approved_fallbacks": [],
                "fallback_on": [],
            },
        },
    }


def test_parser_normalizes_used_and_remaining_windows():
    snapshot = parse_quota_output(
        "codex",
        "5-hour limit: 83% left, resets in 2h 30m\nWeekly: 92% used, resets in 4d",
        observed_at=NOW,
    )

    assert snapshot.remaining_percent == 8.0
    assert snapshot.status == "available"
    assert {item.name for item in snapshot.windows} == {"five_hour", "weekly"}
    assert snapshot.reset_at == "2026-07-19T00:00:00Z"


def test_parser_enforces_five_percent_reserve_and_keeps_reset():
    snapshot = parse_quota_output(
        "agy",
        "Gemini 5h: 96% used; resets in 1h 15m",
        observed_at=NOW,
    )

    assert snapshot.status == "quota_reserve"
    assert snapshot.remaining_percent == 4.0
    assert snapshot.reset_at == "2026-07-15T01:15:00Z"
    assert snapshot.failure_class == "quota_exhausted"


def test_bare_percent_is_telemetry_degraded_not_assumed_remaining():
    snapshot = parse_quota_output("qwen", "Usage 42%", observed_at=NOW)

    assert snapshot.status == "unknown"
    assert snapshot.remaining_percent is None
    assert snapshot.failure_class == "telemetry_unparseable"


def test_quota_snapshot_opens_reserve_and_routes_at_checkpoint(tmp_path):
    ledger = tmp_path / "capacity.yml"
    capacity = ModelCapacity(_policy(), ledger, clock=lambda: NOW)
    snapshot = parse_quota_output(
        "primary", "5-hour: 4% remaining; resets in 1h", observed_at=NOW
    )

    result = capacity.record_quota_snapshot("primary", snapshot, attempt_id="quota-1")
    fallback = capacity.select_route("primary", role="Supervisor", attempt_id="route-1")
    direct = capacity.select_route("primary_direct", role="Supervisor", attempt_id="route-2")

    assert result["status"] == "waiting_for_quota"
    assert fallback["route_id"] == "fallback"
    assert direct["status"] == "waiting_for_quota"
    assert direct["resume_at"] > "2026-07-15T01:01:00Z"
    stored = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    assert "4%" not in str(stored)
    assert stored["pools"]["primary"]["remaining_percent"] == 4.0


def test_predicted_unit_usage_raises_admission_floor(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "capacity.yml", clock=lambda: NOW)
    snapshot = parse_quota_output(
        "primary", "Weekly: 8% remaining; resets in 1h", observed_at=NOW
    )
    capacity.record_quota_snapshot("primary", snapshot, attempt_id="quota-2")

    decision = capacity.select_route(
        "primary_direct",
        role="Supervisor",
        attempt_id="route-3",
        predicted_unit_usage_percent=6,
        risk_reserve_percent=3,
    )

    assert decision["status"] == "blocked"
    assert decision["admission_floor_percent"] == 9.0


def test_stale_telemetry_blocks_long_batch_only(tmp_path):
    current = [NOW]
    capacity = ModelCapacity(_policy(), tmp_path / "capacity.yml", clock=lambda: current[0])
    snapshot = parse_quota_output(
        "primary", "Weekly: 80% remaining; resets in 1h", observed_at=NOW
    )
    capacity.record_quota_snapshot("primary", snapshot, attempt_id="quota-3")
    current[0] += timedelta(minutes=11)

    short = capacity.select_route("primary_direct", role="Supervisor", attempt_id="short")
    long = capacity.select_route(
        "primary_direct", role="Supervisor", attempt_id="long", long_batch=True
    )

    assert short["status"] == "selected"
    assert long["status"] == "blocked"
    assert long["failure_class"] == "telemetry_degraded"


def test_probe_spec_rejects_bypass_flags():
    for argv in (
        ["hermes", "-z"],
        ["claude", "--permission-mode=bypassPermissions"],
        ["claude", "--allow-dangerously-skip-permissions"],
    ):
        try:
            QuotaProbeSpec.from_mapping({
                "shell_id": argv[0],
                "argv": argv,
                "slash_command": "/usage",
            })
        except ValueError as exc:
            assert "dangerous" in str(exc)
        else:
            raise AssertionError(f"unsafe probe should fail: {argv}")


def test_agy_quota_probes_bind_independent_model_pools():
    registry = yaml.safe_load(
        (ROOT / "config" / "runtime_registry.yml").read_text(encoding="utf-8")
    )
    pools = registry["credential_pools"]

    gemini = QuotaProbeSpec.from_mapping(pools["agy_gemini"]["quota_probe"])
    claude = QuotaProbeSpec.from_mapping(pools["agy_claude"]["quota_probe"])

    assert gemini.argv == ("agy", "--model", "Gemini 3.5 Flash (High)")
    assert claude.argv == ("agy", "--model", "Claude Sonnet 4.6 (Thinking)")
    assert gemini.argv != claude.argv


def test_runtime_probe_spec_overrides_legacy_capacity_probe(tmp_path):
    capacity = ModelCapacity(_policy(), tmp_path / "capacity.yml", clock=lambda: NOW)
    observed = []

    def runner(spec):
        observed.append(spec.argv)
        return {"returncode": 0, "output": "5-hour: 75% remaining; resets in 2h"}

    capacity.probe_quota(
        "primary",
        runner=runner,
        attempt_id="runtime-authority",
        probe_spec={
            "shell_id": "agy",
            "argv": ["agy", "--model", "Gemini 3.5 Flash (High)"],
            "slash_command": "/usage",
        },
    )

    assert observed == [("agy", "--model", "Gemini 3.5 Flash (High)")]
