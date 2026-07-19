"""Crown-specific adapter from compiled mission contracts to background jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from agent_runtime.narrative.jobs.background import _create_narrative_audit_state
from agent_runtime.narrative.jobs.identity import NarrativeJobIdentity
from agent_runtime.narrative.jobs.identity import lease_expiry


def create_crown_audit_job_from_contract(
    root: Path,
    *,
    mission_contract: Mapping[str, Any],
    job_id: str,
    eval_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 10,
    now: str | None = None,
) -> dict[str, Any]:
    """Create a Crown audit job only from a compiled audit-only identity."""
    project = str(mission_contract.get("project_id") or "")
    if project != "Crown_of_Ash":
        raise ValueError("crown audit adapter requires project_id Crown_of_Ash")
    raw_identity = mission_contract.get("narrative_job_identity")
    if not isinstance(raw_identity, Mapping):
        raise ValueError("mission contract is missing narrative_job_identity")
    identity = NarrativeJobIdentity.from_mapping(raw_identity)
    if identity.job_kind != "narrative_audit" or identity.run_mode != "audit_only":
        raise ValueError("mission contract is not an audit-only narrative job")
    return _create_narrative_audit_state(
        root,
        project=project,
        job_id=job_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        batch_size=batch_size,
        adapter_config={
            "narrative_adapter": "crown",
            "eval_id": eval_id,
        },
        candidate_set_id=identity.candidate_set_id,
        source_job_id=identity.source_job_id,
        source_run_id=identity.source_run_id,
        triggered_by_audit_id=identity.triggered_by_audit_id,
        now=now or datetime.now(timezone.utc).isoformat(),
    )


def upgrade_crown_job_state(value: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate Crown's pre-identity state without classifying stored prose."""
    state = dict(value)
    job_type = str(state.get("job_type") or "")
    if job_type not in {"crown_narrative_delivery", "narrative_audit"}:
        return state
    if not state.get("job_kind"):
        identity = (
            NarrativeJobIdentity("narrative_generation", "generate_candidate")
            if job_type == "crown_narrative_delivery"
            else NarrativeJobIdentity("narrative_audit", "audit_only")
        )
        state.update(identity.to_dict())
    state["schema_version"] = max(2, int(state.get("schema_version") or 1))
    for key, default in (
        ("automatic_rewrite_count", 0),
        ("automatic_rewrite_exhausted", False),
        ("decision_reason", None),
        ("independent_reaudit_required", False),
    ):
        state.setdefault(key, default)
    config = dict(state.get("config") or {})
    config.setdefault("attempt_lease_seconds", 3600)
    config.setdefault("required_audits", ["fiction_review", "continuity_failure_report"])
    config.setdefault("narrative_adapter", "crown")
    state["config"] = config
    active = state.get("active_attempt")
    if isinstance(active, Mapping):
        migrated = dict(active)
        token = str(
            migrated.get("lease_token")
            or f"legacy:{migrated.get('idempotency_key') or migrated.get('attempt_id')}"
        )
        migrated["lease_token"] = token
        if not migrated.get("lease_expires_at"):
            scheduled = str(migrated.get("scheduled_at") or state.get("updated_at") or "")
            migrated["lease_expires_at"] = lease_expiry(
                scheduled,
                int(config["attempt_lease_seconds"]),
            )
        state["active_attempt"] = migrated
        state["attempt_id"] = migrated.get("attempt_id")
        state["lease_token"] = token
    return state
