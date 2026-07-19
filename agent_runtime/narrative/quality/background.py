"""Background adapter for the scene-level narrative revision closure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml


def run_background_revision(request: dict[str, Any]) -> dict[str, object]:
    """Validate an executable revision packet and fail closed until Gate 1 is live."""
    prior_results = request.get("prior_results") or {}
    heavy = prior_results.get("heavy_audit") or {}
    verifier = prior_results.get("revision_support_verifier") or {}
    proposal_path = Path(
        str(verifier.get("output_path") or heavy.get("rewrite_proposal") or "")
    )
    proposal = safe_read_yaml(proposal_path, default=None) if proposal_path.is_file() else None
    contracts = proposal.get("proposals") if isinstance(proposal, dict) else None
    attempt_dir = (
        Path(request["agentlab_root"])
        / "projects"
        / request["project"]
        / "background_jobs"
        / request["job_id"]
        / "attempts"
        / request["attempt_id"]
    )
    receipt = {
        "schema_version": 1,
        "status": "decision_required",
        "candidate_only": True,
        "production_modified": False,
        "chapter_range": [request["batch"]["start"], request["batch"]["end"]],
        "source_audit_task_id": heavy.get("task_id"),
        "revision_contract_count": len(contracts) if isinstance(contracts, list) else 0,
        "reason": (
            "missing_executable_scene_revision_contracts"
            if not isinstance(contracts, list) or not contracts
            else "provider_revision_gate_not_accepted"
        ),
    }
    path = attempt_dir / "revision_closure_receipt.yml"
    atomic_write_yaml(path, receipt)
    return {**receipt, "revision_closure_receipt": str(path)}
