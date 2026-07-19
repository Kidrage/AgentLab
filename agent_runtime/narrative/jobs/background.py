"""Creation of durable audit-only narrative jobs."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.jobs.identity import NarrativeJobIdentity


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _create_narrative_audit_state(
    root: Path,
    *,
    project: str,
    job_id: str,
    start_chapter: int,
    end_chapter: int,
    adapter_config: Mapping[str, Any],
    batch_size: int = 10,
    candidate_set_id: str | None = None,
    source_job_id: str | None = None,
    source_run_id: str | None = None,
    triggered_by_audit_id: str | None = None,
    now: str,
) -> dict[str, Any]:
    """Persist an adapter-validated audit job whose first action is heavy audit."""
    if not _SAFE_ID.fullmatch(project) or not _SAFE_ID.fullmatch(job_id):
        raise ValueError("invalid project or job id")
    if start_chapter < 1 or end_chapter < start_chapter or batch_size < 1:
        raise ValueError("invalid audit chapter range or batch size")
    project_root = Path(root) / "projects" / project
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)
    directory = project_root / "background_jobs" / job_id
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir(parents=True)
    identity = NarrativeJobIdentity(
        "narrative_audit",
        "audit_only",
        candidate_set_id=candidate_set_id,
        source_job_id=source_job_id,
        source_run_id=source_run_id,
        triggered_by_audit_id=triggered_by_audit_id,
    )
    config = dict(adapter_config)
    config.update(
        {
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "batch_size": batch_size,
            "max_retries_per_action": int(config.get("max_retries_per_action", 3)),
            "transient_retry_seconds": int(config.get("transient_retry_seconds", 900)),
            "attempt_lease_seconds": int(config.get("attempt_lease_seconds", 3600)),
            "required_audits": list(
                config.get(
                    "required_audits",
                    [
                        "fiction_review",
                        "continuity_failure_report",
                        "narrative_quality_scorecard",
                    ],
                )
            ),
        }
    )
    state: dict[str, Any] = {
        "schema_version": 2,
        "job_id": job_id,
        "job_type": "narrative_audit",
        **identity.to_dict(),
        "project": project,
        "status": "awaiting_heavy_audit",
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "candidate_only": True,
        "production_allowed": False,
        "preflight_passed": True,
        "config": config,
        "current_batch": {
            "number": 1,
            "start": start_chapter,
            "end": min(end_chapter, start_chapter + batch_size - 1),
        },
        "audited_batches": [],
        "audit_has_findings": False,
        "findings": [],
        "sealed_batches": [],
        "active_attempt": None,
        "attempt_sequence": 0,
        "processed_receipt_keys": [],
        "retry_counts": {},
        "retry_action": None,
        "last_action_results": {},
        "automatic_rewrite_count": 0,
        "automatic_rewrite_exhausted": False,
        "decision_reason": None,
        "independent_reaudit_required": False,
        "capacity_reset_at": None,
        "capacity_resume_count": 0,
        "retry_at": None,
        "retry_resume_count": 0,
        "pause_requested": False,
        "paused_from_status": None,
        "paused_at": None,
        "last_error": None,
    }
    atomic_write_yaml(directory / "job_state.yml", state)
    event = {
        "schema_version": 2,
        "event_id": f"evt-{now}-JOB_CREATED",
        "event_type": "JOB_CREATED",
        "recorded_at": now,
        "job_id": job_id,
        "project": project,
        "status": state["status"],
        "payload": {"current_batch": state["current_batch"]},
    }
    atomic_write_text(
        directory / "job_events.jsonl",
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return state
