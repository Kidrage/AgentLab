from __future__ import annotations

from pathlib import Path
import yaml

from agent_runtime.atomic_io import atomic_write_yaml, atomic_write_text
from agent_runtime.executors.result_contract import load_executor_result_envelope
from agent_runtime.program_manager.acceptance_contract import build_acceptance_contract
from agent_runtime.program_manager.scope_checker import check_scope
from agent_runtime.program_manager.evidence_checker import check_evidence
from agent_runtime.program_manager.next_action_decider import decide_verdict
from agent_runtime.program_manager.acceptance_renderer import render_markdown_report
from agent_runtime.program_manager.project_fact_state import apply_state_transition_proposal, load_project_fact_snapshot, utc_now
from agent_runtime.program_manager.replanner import recommend_next_action
from agent_runtime.program_manager.state_transition_validator import load_state_transition_proposal, validate_state_transition_proposal


def accept_phase(phase_plan_path: Path, evidence_dir: Path, out_dir: Path) -> dict:
    # 1. Load phase plan
    phase_plan = yaml.safe_load(phase_plan_path.read_text(encoding="utf-8")) or {}
    contract = build_acceptance_contract(phase_plan)
    
    # 2. Extract changed_files and test_results from evidence_ledger or result files
    changed_files = []
    test_results = None
    executor_evidence_status = {
        "required": False,
        "has_supporting_evidence": True,
        "supporting_evidence_files": [],
    }

    ledger_path = evidence_dir / "evidence_ledger.yml"
    if ledger_path.exists():
        try:
            ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
            result_dir_str = ledger.get("result_dir")
            if result_dir_str:
                ledger_files = [str((item or {}).get("path") or "") for item in ledger.get("files") or []]
                supporting_files = [
                    item
                    for item in ledger_files
                    if item not in ("executor_result.yml", "execution_result_envelope.yml")
                ]
                executor_evidence_status = {
                    "required": True,
                    "has_supporting_evidence": bool(supporting_files),
                    "supporting_evidence_files": supporting_files,
                }
                result_dir = Path(result_dir_str)
                envelope = load_executor_result_envelope(result_dir)
                
                changed_files = [str(item) for item in envelope.get("changed_files") or []]
                test_val = envelope.get("test_results") or envelope.get("test_status")
                
                if isinstance(test_val, dict):
                    test_results = test_val
                elif isinstance(test_val, bool):
                    test_results = {"passed": test_val}
                elif isinstance(test_val, str):
                    test_results = {"passed": test_val.upper() == "PASS"}
        except Exception:
            pass

    # 3. Perform scope and evidence checks
    scope_status = check_scope(phase_plan, changed_files)
    evidence_status = check_evidence(phase_plan, evidence_dir)
    state_status = _check_project_fact_state(phase_plan, phase_plan_path, evidence_dir)
    if not state_status.get("valid", True):
        evidence_status = dict(evidence_status)
        evidence_status["has_missing"] = True
        evidence_status.setdefault("missing_evidence", [])
        evidence_status["missing_evidence"] = list(evidence_status["missing_evidence"]) + ["project_fact_state_validated"]
    if executor_evidence_status["required"] and not executor_evidence_status["has_supporting_evidence"]:
        evidence_status = dict(evidence_status)
        evidence_status["has_missing"] = True
        evidence_status.setdefault("missing_evidence", [])
        evidence_status["missing_evidence"] = list(evidence_status["missing_evidence"]) + ["executor_result_supporting_evidence"]

    # 4. Decide verdict
    decide_res = decide_verdict(
        scope_status=scope_status,
        evidence_status=evidence_status,
        test_results=test_results,
        human_approval_required=contract["human_approval_required"],
    )

    verdict = decide_res["verdict"]
    recommended_next_action = decide_res["recommended_next_action"]
    rationale = decide_res["rationale"]

    # Map verdict to explicit phase states. Human-review states must never close a phase.
    if verdict == "accept":
        compat_verdict = "PASS"
    elif verdict == "ask_user":
        compat_verdict = "NEEDS_HUMAN_REVIEW"
    elif verdict == "blocked":
        compat_verdict = "NEEDS_EVIDENCE"
    else:
        compat_verdict = verdict.upper()
    accepted = (compat_verdict == "PASS")

    result = {
        "phase_id": contract["phase_id"],
        "verdict": compat_verdict,
        "verdict_details": verdict,
        "accepted": accepted,
        "recommended_next_action": recommended_next_action,
        "rationale": rationale,
        "missing_evidence": evidence_status["missing_evidence"],
        "evidence_files": evidence_status["evidence_files"],
        "human_approval_required": contract["human_approval_required"],
        "scope_status": scope_status,
        "evidence_status": evidence_status,
        "executor_evidence_status": executor_evidence_status,
        "state_transition_status": state_status,
        "test_results": test_results,
        "policy": {
            "external_auto_execution_allowed": False,
            "phase_close_requires_evidence": True,
            "human_review_blocks_acceptance": True,
        },
    }

    # 5. Write acceptance artifacts (YAML and Markdown)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "phase_acceptance.yml", result)
    if result["accepted"] and state_status.get("proposal_supplied") and state_status.get("project_brain_dir"):
        apply_result = apply_state_transition_proposal(
            Path(state_status["project_brain_dir"]),
            state_status.get("proposal") or {},
            result,
        )
        state_status["applied"] = True
        state_status["applied_event_ids"] = apply_result.get("event_ids") or []
        result["state_transition_status"] = state_status
        atomic_write_yaml(out_dir / "phase_acceptance.yml", result)

    result["acceptance_history_status"] = _record_project_brain_acceptance(
        result,
        phase_plan,
        phase_plan_path,
        out_dir,
    )
    atomic_write_yaml(out_dir / "phase_acceptance.yml", result)

    report_md = render_markdown_report(result)
    atomic_write_text(out_dir / "phase_acceptance.md", report_md)

    return result


def _check_project_fact_state(phase_plan: dict, phase_plan_path: Path, evidence_dir: Path) -> dict:
    plan = phase_plan.get("task_packet") or phase_plan
    state_contract_ref = plan.get("state_contract") or {}
    project_brain_dir = _infer_project_brain_dir(plan, phase_plan_path)
    artifact_name = state_contract_ref.get("transition_artifact") or "state_transition_proposal.yml"
    proposal = load_state_transition_proposal(evidence_dir, artifact_name)
    required = bool(state_contract_ref.get("transition_proposal_required"))
    if project_brain_dir is None:
        return {
            "valid": proposal is None and not required,
            "proposal_supplied": proposal is not None,
            "errors": ["project brain directory is required for state transition validation"] if proposal is not None or required else [],
            "warnings": ["project fact state contract unavailable"],
        }
    contract_path = project_brain_dir / str(state_contract_ref.get("contract_ref") or "project_state_contract.yml")
    if not contract_path.exists():
        return {
            "valid": proposal is None and not required,
            "proposal_supplied": proposal is not None,
            "project_brain_dir": str(project_brain_dir),
            "errors": ["project_state_contract.yml is required for state transition validation"] if proposal is not None or required else [],
            "warnings": ["project fact state contract unavailable"],
        }
    state_contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    snapshot = load_project_fact_snapshot(project_brain_dir)
    verdict = validate_state_transition_proposal(state_contract, snapshot, proposal, required=required)
    verdict["proposal_supplied"] = proposal is not None
    verdict["proposal"] = proposal
    verdict["project_brain_dir"] = str(project_brain_dir)
    return verdict


def _infer_project_brain_dir(plan: dict, phase_plan_path: Path) -> Path | None:
    state_contract = plan.get("state_contract") or {}
    for raw in (state_contract.get("project_brain_dir"), plan.get("project_brain_dir")):
        if raw:
            path = Path(str(raw))
            if path.exists():
                return path
            if not path.is_absolute():
                relative_path = (phase_plan_path.parent / path).resolve()
                if relative_path.exists():
                    return relative_path
    if (phase_plan_path.parent / "project_state_contract.yml").exists():
        return phase_plan_path.parent
    return None


def _record_project_brain_acceptance(
    result: dict,
    phase_plan: dict,
    phase_plan_path: Path,
    out_dir: Path,
) -> dict:
    plan = phase_plan.get("task_packet") or phase_plan
    project_brain_dir = _infer_project_brain_dir(plan, phase_plan_path)
    if project_brain_dir is None:
        return {
            "recorded": False,
            "reason": "project_brain_unavailable",
        }

    history_path = project_brain_dir / "acceptance_history.yml"
    history = {}
    if history_path.exists():
        loaded = yaml.safe_load(history_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            history = loaded
    entries = list(history.get("entries") or [])
    state_status = result.get("state_transition_status") or {}
    entry = {
        "phase_id": result.get("phase_id"),
        "accepted": bool(result.get("accepted")),
        "verdict": result.get("verdict"),
        "verdict_details": result.get("verdict_details"),
        "recommended_next_action": result.get("recommended_next_action"),
        "rationale": result.get("rationale"),
        "missing_evidence": result.get("missing_evidence") or [],
        "evidence_files": result.get("evidence_files") or [],
        "human_approval_required": bool(result.get("human_approval_required")),
        "state_transition": {
            "proposal_supplied": bool(state_status.get("proposal_supplied")),
            "applied": bool(state_status.get("applied")),
            "applied_event_ids": state_status.get("applied_event_ids") or [],
        },
        "acceptance_artifact": str((out_dir / "phase_acceptance.yml").resolve()),
        "recorded_at": utc_now(),
    }
    entries.append(entry)
    atomic_write_yaml(history_path, {"entries": entries})

    status = {
        "recorded": True,
        "project_brain_dir": str(project_brain_dir),
        "history_path": str(history_path),
        "entry_count": len(entries),
        "next_actions_updated": False,
    }
    roadmap_path = project_brain_dir / "roadmap.yml"
    if roadmap_path.exists():
        roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8")) or {}
        next_actions = recommend_next_action({"entries": entries}, roadmap)
        atomic_write_yaml(project_brain_dir / "next_actions.yml", next_actions)
        status["next_actions_updated"] = True
        status["next_actions"] = next_actions
    return status
