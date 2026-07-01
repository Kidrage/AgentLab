"""M3-7 Content Project Operator Surface — Crown/NovelGen governance visibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def build_content_project_state(project_root: Path) -> dict[str, Any]:
    """Build an operator-facing view of a content project's governance state.

    Reads:
    - project_artifact_index.yml → current artifacts, candidates, archives
    - project_brain/project_fact_snapshot.yml → fact state
    - runs/*/state_transition_proposal.yml → pending state transitions
    - runs/*/artifact_lineage.yml → artifact lineage chains
    - Content project config for canonical layout

    Returns a dict with all operator-visible content governance fields.
    """
    brain_dir = project_root / "project_brain"
    artifact_index = _load_yaml(project_root / "project_artifact_index.yml", {})
    fact_snapshot = _load_yaml(brain_dir / "project_fact_snapshot.yml", {})

    # parse artifact index
    artifacts = artifact_index.get("artifacts") if isinstance(artifact_index, dict) else []
    artifacts = artifacts if isinstance(artifacts, list) else []

    current_artifacts = [a for a in artifacts if isinstance(a, dict) and a.get("status") == "current"]
    candidate_artifacts = [a for a in artifacts if isinstance(a, dict) and a.get("status") == "candidate"]
    archived_artifacts = [a for a in artifacts if isinstance(a, dict) and a.get("status") == "archived"]

    # detect blocking hygiene errors
    blocking_errors: list[dict[str, Any]] = []
    # multiple-current check
    if len(current_artifacts) > 1:
        blocking_errors.append({
            "type": "multiple_current_artifacts",
            "reason": f"{len(current_artifacts)} artifacts marked current (expected 1)",
            "artifact_ids": [a.get("artifact_id") for a in current_artifacts],
            "severity": "blocking",
        })

    # scan runs/ for state transitions and lineages
    runs_dir = project_root / "runs"
    state_transition_proposals: list[dict[str, Any]] = []
    artifact_lineages: list[dict[str, Any]] = []
    continuity_warnings: list[dict[str, Any]] = []
    chapter_batches: list[dict[str, Any]] = []

    if runs_dir.exists():
        for task_dir in sorted(runs_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            task_id = task_dir.name

            # state transition proposals
            stp_path = task_dir / "state_transition_proposal.yml"
            if stp_path.exists():
                stp = _load_yaml(stp_path, {})
                if isinstance(stp, dict):
                    state_transition_proposals.append({
                        "task_id": task_id,
                        "proposal": stp,
                        "status": stp.get("status") or "pending",
                    })

            # artifact lineage
            al_path = task_dir / "artifact_lineage.yml"
            if al_path.exists():
                al = _load_yaml(al_path, {})
                if isinstance(al, dict):
                    artifact_lineages.append({
                        "task_id": task_id,
                        "lineage": al,
                    })

            # continuity reports
            cr_path = task_dir / "continuity_report.yml"
            if cr_path.exists():
                cr = _load_yaml(cr_path, {})
                if isinstance(cr, dict) and cr.get("warnings"):
                    continuity_warnings.append({
                        "task_id": task_id,
                        "warnings": cr["warnings"],
                    })

            # phase acceptance (chapter batch status)
            pa_path = task_dir / "phase_acceptance.yml"
            if pa_path.exists():
                pa = _load_yaml(pa_path, {})
                if isinstance(pa, dict):
                    chapter_batches.append({
                        "task_id": task_id,
                        "phase_id": pa.get("phase_id"),
                        "verdict": pa.get("verdict"),
                        "state_transition_applied": bool(
                            (pa.get("state_transition") or {}).get("applied")
                        ),
                    })

    # derive promotion readiness
    promotion_readiness = _derive_promotion_readiness(
        current_artifacts, candidate_artifacts, state_transition_proposals,
        blocking_errors, continuity_warnings,
    )

    # derive blocking reasons for each candidate
    blocking_reasons = _derive_blocking_reasons(
        candidate_artifacts, state_transition_proposals,
        blocking_errors, continuity_warnings,
    )

    # content project config
    governance_config = _load_yaml(project_root.parent.parent / "config" / "content_project_governance.yml", {})

    return {
        "schema_version": 1,
        "project": project_root.name,
        "production_root": _resolve_path(project_root, governance_config.get("production_root", "production")),
        "candidate_roots": _resolve_paths(project_root, governance_config.get("candidate_roots", ["candidates"])),
        "archive_root": _resolve_path(project_root, governance_config.get("archive_root", "archive")),
        "artifact_index": {
            "current_count": len(current_artifacts),
            "candidate_count": len(candidate_artifacts),
            "archived_count": len(archived_artifacts),
            "current": [a.get("artifact_id") for a in current_artifacts],
            "candidates": [a.get("artifact_id") for a in candidate_artifacts],
        },
        "fact_snapshot": {
            "event_count": fact_snapshot.get("event_count") if isinstance(fact_snapshot, dict) else None,
            "project": fact_snapshot.get("project") if isinstance(fact_snapshot, dict) else None,
        },
        "state_transition_proposals": state_transition_proposals,
        "artifact_lineages": artifact_lineages,
        "continuity_warnings": continuity_warnings,
        "chapter_batch_status": chapter_batches,
        "promotion_readiness": promotion_readiness,
        "blocking_hygiene_errors": blocking_errors,
        "blocking_reasons": blocking_reasons,
    }


def _derive_promotion_readiness(
    current: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
    continuity_warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Determine if candidates are ready for promotion."""
    ready = True
    reasons: list[str] = []

    if not candidates:
        return {"ready": False, "reason": "no candidates to promote"}

    if len(current) != 1:
        ready = False
        reasons.append(f"expected exactly 1 current artifact, got {len(current)}")

    if blocking_errors:
        ready = False
        reasons.append(f"{len(blocking_errors)} blocking hygiene errors")

    pending_proposals = [p for p in proposals if p.get("status") == "pending"]
    if not pending_proposals:
        ready = False
        reasons.append("no pending state transition proposals for candidates")

    if continuity_warnings:
        ready = False
        reasons.append(f"{len(continuity_warnings)} continuity warnings unresolved")

    return {"ready": ready, "reasons": reasons if reasons else ["all checks passed"]}


def _derive_blocking_reasons(
    candidates: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    blocking_errors: list[dict[str, Any]],
    continuity_warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """For each candidate, explain why it's not yet canon."""
    reasons: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = candidate.get("artifact_id", "unknown")
        c_reasons: list[str] = []

        # check proposal
        has_proposal = any(
            p.get("proposal", {}).get("artifact_id") == cid
            for p in proposals
        )
        if not has_proposal:
            c_reasons.append("no state transition proposal found")

        # check for blocking hygiene errors affecting this candidate
        for be in blocking_errors:
            if cid in be.get("artifact_ids", []):
                c_reasons.append(be["reason"])

        reasons.append({
            "artifact_id": cid,
            "reasons": c_reasons or ["pending review"],
            "canon_blocked": len(c_reasons) > 0,
        })
    return reasons


def _resolve_path(project_root: Path, rel: str | None) -> str | None:
    if not rel:
        return None
    p = (project_root / rel)
    return str(p) if p.exists() else f"{rel} (not found)"


def _resolve_paths(project_root: Path, rels: list[str] | None) -> list[str]:
    if not rels:
        return []
    return [_resolve_path(project_root, r) or r for r in rels]


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else default
