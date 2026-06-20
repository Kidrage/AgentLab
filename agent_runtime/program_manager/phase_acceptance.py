from __future__ import annotations

from pathlib import Path
import yaml

from agent_runtime.atomic_io import atomic_write_yaml, atomic_write_text
from agent_runtime.program_manager.acceptance_contract import build_acceptance_contract
from agent_runtime.program_manager.scope_checker import check_scope
from agent_runtime.program_manager.evidence_checker import check_evidence
from agent_runtime.program_manager.next_action_decider import decide_verdict
from agent_runtime.program_manager.acceptance_renderer import render_markdown_report


def accept_phase(phase_plan_path: Path, evidence_dir: Path, out_dir: Path) -> dict:
    # 1. Load phase plan
    phase_plan = yaml.safe_load(phase_plan_path.read_text(encoding="utf-8")) or {}
    contract = build_acceptance_contract(phase_plan)
    
    # 2. Extract changed_files and test_results from evidence_ledger or result files
    changed_files = []
    test_results = None

    ledger_path = evidence_dir / "evidence_ledger.yml"
    if ledger_path.exists():
        try:
            ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
            result_dir_str = ledger.get("result_dir")
            if result_dir_str:
                result_dir = Path(result_dir_str)
                envelope_path = result_dir / "execution_result_envelope.yml"
                result_path = result_dir / "executor_result.yml"
                envelope = {}
                if result_path.exists():
                    raw = yaml.safe_load(result_path.read_text(encoding="utf-8")) or {}
                    envelope = raw.get("executor_result") or raw
                elif envelope_path.exists():
                    raw = yaml.safe_load(envelope_path.read_text(encoding="utf-8")) or {}
                    envelope = raw.get("executor_result") or raw
                
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

    # Map verdict to compat upper-case structure
    # 'ask_user' (due to human gate or drift) is technically PASS for automated checks,
    # but prompts for user decision.
    compat_verdict = "PASS" if verdict in ("accept", "ask_user") else "NEEDS_EVIDENCE" if verdict == "blocked" else verdict.upper()
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
        "test_results": test_results,
        "policy": {
            "external_auto_execution_allowed": False,
            "phase_close_requires_evidence": True,
        },
    }

    # 5. Write acceptance artifacts (YAML and Markdown)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "phase_acceptance.yml", result)
    
    report_md = render_markdown_report(result)
    atomic_write_text(out_dir / "phase_acceptance.md", report_md)

    return result
