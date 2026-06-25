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

from pathlib import Path
from agent_runtime.goals.models import GoalCommandResult
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.storage import get_project_brain_dir, read_yaml, append_to_yaml_list
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compile_goal_validate(action: GoalActionSchema, agentlab_root: Path) -> GoalCommandResult:
    brain_dir = get_project_brain_dir(agentlab_root, action.project)
    program_data = read_yaml(brain_dir / "mainline_program.yml")

    if not program_data:
        return GoalCommandResult("error", [], "No mainline program found.")

    stages = program_data.get("stages", [])
    blocked = False
    reasons = []

    # Load acceptance_contract for more detailed stage info
    acceptance_path = brain_dir / "mainline_acceptance_contract.yml"
    acceptance_data = read_yaml(acceptance_path)
    acceptance_stages = acceptance_data.get("stages", []) if acceptance_data else []

    # Build effective stages: prefer acceptance_contract for artifact/evidence/gate
    # specs, but merge in blocks_m2_closure and status from mainline stages
    mainline_by_id = {s.get("stage_id", ""): s for s in stages}
    effective_stages = []
    if acceptance_stages:
        for ac_stage in acceptance_stages:
            sid = ac_stage.get("stage_id", "")
            merged = dict(ac_stage)
            if sid in mainline_by_id:
                ml = mainline_by_id.get(sid, {})
                if "blocks_m2_closure" not in merged and "blocks_m2_closure" in ml:
                    merged["blocks_m2_closure"] = ml["blocks_m2_closure"]
                if "status" not in merged and "status" in ml:
                    merged["status"] = ml["status"]
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
        return GoalCommandResult(
            "blocked", [],
            "No stages defined in mainline program or acceptance contract."
        )

    # Build evidence set: files in brain_dir + evidence lists
    evidence_set: set = set()
    evidence_set.update(program_data.get("evidence", []))
    progress_data = read_yaml(brain_dir / "mainline_progress.yml")
    if progress_data:
        evidence_set.update(progress_data.get("evidence", []))

    # Build gates map
    gates = dict(program_data.get("gates", {}))
    if progress_data:
        gates.update(progress_data.get("gates", {}))

    for stage in effective_stages:
        stage_id = stage.get("stage_id", "unknown")

        # Skip future_reserved stages that don't block M2 closure
        if stage.get("status") == "future_reserved" and stage.get("blocks_m2_closure") is False:
            continue

        # Skip stages that explicitly have blocks_m2_closure=false
        if stage.get("blocks_m2_closure") is False:
            continue

        # Check required_artifacts
        for artifact in stage.get("required_artifacts", []):
            if not (brain_dir / artifact).is_file():
                blocked = True
                reasons.append(
                    f"stage '{stage_id}' requires artifact '{artifact}' which is missing"
                )

        # Check required_evidence
        for evidence in stage.get("required_evidence", []):
            found = (brain_dir / evidence).is_file() or evidence in evidence_set
            if not found:
                blocked = True
                reasons.append(
                    f"stage '{stage_id}' requires evidence '{evidence}' which is missing"
                )

        # Check acceptance_gates
        for gate in stage.get("acceptance_gates", []):
            if gate not in gates or gates.get(gate) is not True:
                blocked = True
                reasons.append(
                    f"stage '{stage_id}' requires gate '{gate}' which is not passed"
                )

    # Record result in acceptance_history
    if blocked:
        append_to_yaml_list(brain_dir / "acceptance_history.yml", {
            "timestamp": _now(),
            "status": "blocked",
            "action": "validate",
            "reasons": reasons,
        })
        return GoalCommandResult(
            status="blocked",
            artifacts=["acceptance_history.yml"],
            message=f"Validation blocked: {'; '.join(reasons)}"
        )

    append_to_yaml_list(brain_dir / "acceptance_history.yml", {
        "timestamp": _now(),
        "status": "pass",
        "action": "validate"
    })

    return GoalCommandResult(
        status="ok",
        artifacts=["mainline_progress.yml", "acceptance_history.yml"],
        message="Validation complete."
    )
