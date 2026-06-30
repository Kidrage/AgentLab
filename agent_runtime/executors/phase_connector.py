from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.executors.diff_inspector import inspect_changed_files
from agent_runtime.executors.evidence_collector import collect_phase_evidence
from agent_runtime.executors.executor_ledger import append_executor_event
from agent_runtime.executors.result_contract import (
    load_executor_result_envelope,
    validate_executor_result_envelope,
)
from agent_runtime.program_manager.phase_acceptance import accept_phase


def ingest_phase_executor_result(result_dir: Path, task_packet_path: Path, out_dir: Path) -> dict:
    packet_data = yaml.safe_load(task_packet_path.read_text(encoding="utf-8")) or {}
    packet = packet_data.get("task_packet") or packet_data
    
    # 1. Load and validate result from executor_result.yml or execution_result_envelope.yml
    envelope = load_executor_result_envelope(result_dir)
    contract_validation = validate_executor_result_envelope(envelope)
        
    changed_files = [str(item) for item in envelope.get("changed_files") or []]
    artifacts = [
        str(item)
        for item in (
            envelope.get("artifacts")
            or envelope.get("output_artifacts")
            or envelope.get("evidence_artifacts")
            or []
        )
    ]
    
    diff_report = inspect_changed_files(
        changed_files,
        [str(item) for item in packet.get("allowed_files") or []],
        [str(item) for item in packet.get("forbidden_files") or []],
    )
    evidence = collect_phase_evidence(result_dir, out_dir)
    
    # 2. Invoke phase acceptance without auto-closing
    phase_evidence = out_dir / "phase_evidence"
    acceptance = accept_phase(task_packet_path, phase_evidence, out_dir)
    
    status_val = envelope.get("status") or envelope.get("test_results") or "UNKNOWN"
    if isinstance(status_val, dict):
        status_str = "PASS" if status_val.get("passed", True) else "FAIL"
    else:
        status_str = str(status_val)
        
    ledger = append_executor_event(
        out_dir / "executor_result_ledger.yml",
        {
            "event": "phase_result_ingested",
            "phase_id": packet.get("phase_id"),
            "executor_type": packet.get("executor_type"),
            "status": status_str,
            "diff_verdict": diff_report["verdict"],
            "evidence_count": evidence["evidence_count"],
        },
    )
    
    report = {
        "phase_id": packet.get("phase_id"),
        "result_status": status_str,
        "diff_report": diff_report,
        "changed_files": changed_files,
        "artifacts": artifacts,
        "contract_validation": contract_validation,
        "evidence_ledger": "phase_evidence/evidence_ledger.yml",
        "phase_acceptance": acceptance,
        "accepted_without_review": False,
        "ledger_entries": len(ledger.get("entries") or []),
    }
    atomic_write_yaml(out_dir / "ingested_result.yml", report)
    atomic_write_text(out_dir / "executor_review.md", _render_executor_review(report))
    return report



def review_phase_executor_result(ingested_result_path: Path, phase_plan_path: Path, out_dir: Path) -> dict:
    result = yaml.safe_load(ingested_result_path.read_text(encoding="utf-8")) or {}
    phase_evidence = ingested_result_path.parent / "phase_evidence"
    acceptance = accept_phase(phase_plan_path, phase_evidence, out_dir)
    final = {
        "phase_id": result.get("phase_id"),
        "executor_result_status": result.get("result_status"),
        "diff_verdict": (result.get("diff_report") or {}).get("verdict"),
        "phase_acceptance": acceptance,
        "accepted": acceptance.get("accepted") and (result.get("diff_report") or {}).get("verdict") == "PASS",
        "external_auto_execution_allowed": False,
    }
    atomic_write_yaml(out_dir / "executor_phase_review.yml", final)
    return final


def _render_executor_review(report: dict) -> str:
    return "\n".join(
        [
            "# Executor Review",
            "",
            f"- phase_id: {report.get('phase_id')}",
            f"- result_status: {report.get('result_status')}",
            f"- diff_verdict: {(report.get('diff_report') or {}).get('verdict')}",
            f"- accepted_without_review: {str(report.get('accepted_without_review')).lower()}",
            "",
            "Executor results are evidence only until phase acceptance passes.",
        ]
    ) + "\n"
