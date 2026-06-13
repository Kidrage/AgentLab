from pathlib import Path

from agent_runtime.router_update.ledger import load_router_update_ledger, record_router_update_event


def test_router_update_ledger_records_stage_and_approval(tmp_path: Path):
    ledger = tmp_path / "router_update_ledger.yml"
    record_router_update_event(ledger, "patch_staged", "p", "STAGED", ["staged"], [tmp_path / "router_policy_patch.yml"])
    record_router_update_event(ledger, "approval_requested", "p", "APPROVAL_REQUIRED", ["approval requested"], [tmp_path / "approval_request.yml"])
    events = load_router_update_ledger(ledger)
    assert [event.event for event in events] == ["patch_staged", "approval_requested"]


def test_router_update_ledger_round_trip_yaml(tmp_path: Path):
    ledger = tmp_path / "router_update_ledger.yml"
    record_router_update_event(ledger, "approval_granted", "p", "APPROVED", ["ok"], [])
    assert load_router_update_ledger(ledger)[0].status == "APPROVED"


def test_router_update_ledger_redacts_paths_and_secrets(tmp_path: Path):
    ledger = tmp_path / "router_update_ledger.yml"
    record_router_update_event(ledger, "patch_blocked", "p", "BLOCKED", ["secret token leaked"], [Path("/private/tmp/very/long/path/result.yml")])
    event = load_router_update_ledger(ledger)[0]
    assert event.reason == ["[REDACTED]"]
    assert event.artifacts == ["very/long/path/result.yml"] or event.artifacts == ["long/path/result.yml"]
