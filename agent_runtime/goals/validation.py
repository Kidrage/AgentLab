"""Goal validation — deterministic, local-only blocking checks.

Validates goal acceptance by checking required_artifacts, required_evidence,
and acceptance_gates against the Project Brain filesystem.

Key behavior:
- Missing required artifacts → blocked
- Missing required evidence → blocked
- Missing acceptance gates → blocked
- Future-reserved M3 stages with blocks_m2_closure=false → non-blocking
- All present → pass
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.goals.templates import get_template


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _file_exists(brain_dir: Path, filename: str) -> bool:
    return (brain_dir / filename).is_file()


def validate_goal_acceptance(
    brain_dir: Path,
    project_root: Path | None = None,
    project: str = "",
) -> dict[str, Any]:
    """Validate goal acceptance against Project Brain artifacts.

    Returns dict with:
    - status: "pass" or "blocked"
    - blocking_reasons: list of reasons if blocked
    - artifacts: list of artifact filenames checked
    - message: human-readable summary
    """
    brain_dir = Path(brain_dir)
    blocking_reasons: list[str] = []
    artifacts_checked: list[str] = []

    # Load mainline_program.yml (required)
    mainline_path = brain_dir / "mainline_program.yml"
    if not mainline_path.is_file():
        return {
            "status": "blocked",
            "blocking_reasons": ["mainline_program.yml is missing"],
            "artifacts": [],
            "message": "Validation blocked: mainline_program.yml not found",
        }
    artifacts_checked.append("mainline_program.yml")

    mainline = _read_yaml(mainline_path)
    stages: list[dict[str, Any]] = list(mainline.get("stages") or [])

    # Also try acceptance_contract for more detailed stage info
    acceptance_path = brain_dir / "mainline_acceptance_contract.yml"
    acceptance_contract: dict[str, Any] = {}
    if acceptance_path.is_file():
        acceptance_contract = _read_yaml(acceptance_path)
        artifacts_checked.append("mainline_acceptance_contract.yml")
    else:
        blocking_reasons.append("mainline_acceptance_contract.yml is missing")

    acceptance_stages: list[dict[str, Any]] = list(acceptance_contract.get("stages") or [])

    # Build index of mainline stages by stage_id for merging
    mainline_by_id: dict[str, dict[str, Any]] = {}
    for s in stages:
        sid = s.get("stage_id", "")
        if sid:
            mainline_by_id[sid] = s

    # Merge: use acceptance_contract for artifact/evidence/gate specs,
    # but merge in blocks_m2_closure and status from mainline stages
    if acceptance_stages:
        effective_stages = []
        for ac_stage in acceptance_stages:
            sid = ac_stage.get("stage_id", "")
            merged = dict(ac_stage)
            if sid in mainline_by_id:
                ml = mainline_by_id[sid]
                if "blocks_m2_closure" not in merged and "blocks_m2_closure" in ml:
                    merged["blocks_m2_closure"] = ml["blocks_m2_closure"]
                if "status" not in merged and "status" in ml:
                    merged["status"] = ml["status"]
            # Also set defaults
            if "blocks_m2_closure" not in merged:
                merged["blocks_m2_closure"] = True
            if "status" not in merged:
                merged["status"] = "pending"
            effective_stages.append(merged)
        # Add mainline stages not in acceptance contract
        ac_ids = {s.get("stage_id", "") for s in acceptance_stages}
        for ml_stage in stages:
            if ml_stage.get("stage_id", "") not in ac_ids:
                effective_stages.append(ml_stage)
    else:
        effective_stages = stages

    if not effective_stages:
        # If no stages at all, try to load from template
        goal_contract = _read_yaml(brain_dir / "goal_contract.yml")
        template_id = goal_contract.get("template_id", "")
        if template_id:
            template = get_template(template_id)
            if template:
                effective_stages = list(template.get("stages") or [])

        if not effective_stages:
            blocking_reasons.append("no stages defined in mainline_program.yml or acceptance_contract")

    # Check each stage
    for stage in effective_stages:
        stage_id = str(stage.get("stage_id", "unknown"))

        # Skip future_reserved stages that don't block M2 closure
        if stage.get("status") == "future_reserved" and stage.get("blocks_m2_closure") is False:
            continue

        # Skip stages that explicitly have blocks_m2_closure=false
        if stage.get("blocks_m2_closure") is False:
            continue

        # Check required_artifacts
        required_artifacts: list[str] = list(stage.get("required_artifacts") or [])
        for artifact in required_artifacts:
            if not _file_exists(brain_dir, artifact):
                # Check if artifact exists at project brain level
                blocking_reasons.append(
                    f"stage '{stage_id}' requires artifact '{artifact}' which is missing"
                )

        # Check required_evidence
        required_evidence: list[str] = list(stage.get("required_evidence") or [])
        for evidence in required_evidence:
            # Evidence can be a file in brain_dir, or an entry in mainline_progress.yml evidence list
            if not _file_exists(brain_dir, evidence):
                mainline_evidence = mainline.get("evidence") or []
                progress_path = brain_dir / "mainline_progress.yml"
                progress_evidence: list[str] = []
                if progress_path.is_file():
                    progress = _read_yaml(progress_path)
                    progress_evidence = list(progress.get("evidence") or [])
                all_evidence = list(mainline_evidence) + list(progress_evidence)

                if evidence not in all_evidence and evidence not in artifacts_checked:
                    blocking_reasons.append(
                        f"stage '{stage_id}' requires evidence '{evidence}' which is missing"
                    )

        # Check acceptance_gates
        acceptance_gates: list[str] = list(stage.get("acceptance_gates") or [])
        for gate in acceptance_gates:
            gates = mainline.get("gates") or {}
            progress = {}
            if (brain_dir / "mainline_progress.yml").is_file():
                progress = _read_yaml(brain_dir / "mainline_progress.yml")
                if progress and isinstance(progress, dict):
                    gates = {**gates, **(progress.get("gates") or {})}

            if gate not in gates or gates.get(gate) is not True:
                blocking_reasons.append(
                    f"stage '{stage_id}' requires gate '{gate}' which is not passed"
                )

    # Check scenario validations
    scenario_path = brain_dir / "scenario_validation_plan.yml"
    if scenario_path.is_file():
        artifacts_checked.append("scenario_validation_plan.yml")
        scenario = _read_yaml(scenario_path)
        scenarios: list[dict[str, Any]] = list(scenario.get("scenarios") or [])
        for sc in scenarios:
            if sc.get("blocking_if_missing") is True:
                scenario_id = sc.get("scenario_id", "unknown")
                required_artifacts: list[str] = list(sc.get("required_artifacts") or [])
                for artifact in required_artifacts:
                    if not _file_exists(brain_dir, artifact):
                        blocking_reasons.append(
                            f"scenario '{scenario_id}' requires artifact '{artifact}' which is missing"
                        )
                required_evidence: list[str] = list(sc.get("required_evidence") or [])
                for evidence in required_evidence:
                    if not _file_exists(brain_dir, evidence):
                        blocking_reasons.append(
                            f"scenario '{scenario_id}' requires evidence '{evidence}' which is missing"
                        )
    else:
        # Scenario validation plan is not required to exist unless a stage requires it
        pass

    # Check that goal_contract.yml exists (foundational)
    if not _file_exists(brain_dir, "goal_contract.yml"):
        blocking_reasons.append("goal_contract.yml is missing")

    # Record result in acceptance_history
    hist_path = brain_dir / "acceptance_history.yml"
    hist = _read_yaml(hist_path)
    entries: list[dict[str, Any]] = list(hist.get("entries") or [])

    if blocking_reasons:
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        entries.append({
            "action": "goal_validate",
            "status": "blocked",
            "timestamp": now_str,
            "reasons": blocking_reasons,
        })
        hist["entries"] = entries
        atomic_write_yaml(hist_path, hist)
        return {
            "status": "blocked",
            "blocking_reasons": blocking_reasons,
            "artifacts": artifacts_checked,
            "message": f"Validation blocked: {'; '.join(blocking_reasons)}",
        }

    # All checks passed
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()
    entries.append({
        "action": "goal_validate",
        "status": "pass",
        "timestamp": now_str,
    })
    hist["entries"] = entries
    atomic_write_yaml(hist_path, hist)

    return {
        "status": "pass",
        "blocking_reasons": [],
        "artifacts": artifacts_checked,
        "message": "Validation complete. All artifacts, evidence, and gates present.",
    }
