from __future__ import annotations

"""S5 evidence and recovery planning helpers.

This module connects the existing native web intelligence and local search
layers to the S1-S4 planning chain. It is deliberately mock-first: no network
request, skill execution, or provider call happens here.
"""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
from agent_runtime.local_search.query import query_index
from agent_runtime.local_search.storage import load_index

from .research_planner import plan_research


def _read_yaml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = safe_read_yaml(path, default={}) or {}
    return data if isinstance(data, dict) else {}


def _mission_topic(mission: dict[str, Any], fallback: str = "") -> str:
    for key in ("user_goal", "intent_summary", "mission_id"):
        value = str(mission.get(key) or "").strip()
        if value:
            return value
    return fallback or "AgentLab research task"


def _capability_names(mission: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in mission.get("required_capabilities", []) or []:
        if isinstance(item, dict):
            value = str(item.get("capability") or "").strip()
        else:
            value = str(item).strip()
        if value and value not in names:
            names.append(value)
    return names


def _collect_s4_summaries(s4_report_dir: Path | None) -> list[dict[str, Any]]:
    if s4_report_dir is None or not s4_report_dir.exists():
        return []

    summaries: list[dict[str, Any]] = []
    for path in sorted(s4_report_dir.glob("*.yml")):
        if path.name not in {
            "s4_validation_summary.yml",
            "promotion_eligibility.yml",
            "trust_report.yml",
            "permission_report.yml",
            "sandbox_report.yml",
        }:
            continue
        data = _read_yaml(path)
        eligible = data.get("eligible")
        if eligible is None:
            eligible = data.get("promotion_eligible")
        if eligible is None:
            eligible = data.get("dispatch_eligible")
        summaries.append(
            {
                "path": str(path),
                "report": path.stem,
                "eligible": eligible,
                "status": data.get("status") or data.get("verdict"),
                "blocked_reasons": data.get("blocked_reasons") or data.get("blockers") or data.get("errors") or [],
            }
        )
    return summaries


def _local_evidence(index_path: Path | None, query: str, max_results: int) -> list[dict[str, Any]]:
    if index_path is None or not index_path.exists():
        return []
    docs = load_index(index_path)
    results = query_index(docs, query, max_results=max_results)
    return [item.to_dict() for item in results]


def build_s5_research_packet(
    *,
    mission_contract_path: Path | None = None,
    workflow_plan_path: Path | None = None,
    s4_report_dir: Path | None = None,
    local_index_path: Path | None = None,
    topic: str = "",
    out_dir: Path,
    max_local_results: int = 5,
) -> dict[str, Any]:
    """Write deterministic S5 artifacts and return their paths.

    Outputs:
    - ``research_plan.yml``
    - ``source_plan.yml``
    - ``evidence_ledger.yml``
    - ``recovery_packet.yml``
    - ``phase_acceptance_evidence.yml``
    """

    mission = _read_yaml(mission_contract_path)
    workflow = _read_yaml(workflow_plan_path)
    effective_topic = _mission_topic(mission, fallback=topic)
    capabilities = _capability_names(mission)
    plan = plan_research(
        effective_topic,
        context={
            "focus": " ".join(capabilities[:4]),
            "max_queries": 5,
        },
    )

    s4_summaries = _collect_s4_summaries(s4_report_dir)
    local_evidence = _local_evidence(local_index_path, effective_topic, max_local_results)
    trust_gate_present = bool(s4_summaries)
    trust_gate_passed = trust_gate_present and all(
        item.get("eligible") is not False and not item.get("blocked_reasons")
        for item in s4_summaries
        if item.get("report") in {"promotion_eligibility", "s4_validation_summary"}
    )

    research_plan = {
        "schema_version": 1,
        "stage": "S5",
        "mode": "mock_first",
        "network_enabled": False,
        "topic": plan.topic,
        "queries": plan.queries,
        "planned_sources": [asdict(item) for item in plan.planned_sources],
        "inputs": {
            "mission_contract": str(mission_contract_path) if mission_contract_path else None,
            "workflow_plan": str(workflow_plan_path) if workflow_plan_path else None,
            "s4_report_dir": str(s4_report_dir) if s4_report_dir else None,
            "local_index": str(local_index_path) if local_index_path else None,
        },
        "route_controls": {
            "mock_first": True,
            "approval_first": True,
            "no_real_web_fetch": True,
            "no_skill_dispatch": True,
        },
    }

    source_plan = {
        "schema_version": 1,
        "required_capabilities": capabilities,
        "candidate_source_types": [
            "official_docs",
            "project_docs",
            "acceptance_reports",
            "recovery_history",
            "web_snapshots",
        ],
        "blocked_source_types": [
            "localhost",
            "private_ip",
            "file_url",
            "login_wall",
            "paywall_bypass",
            "unbounded_crawl",
        ],
        "s4_gate": {
            "present": trust_gate_present,
            "passed": trust_gate_passed,
            "reports": s4_summaries,
        },
    }

    evidence_ledger = {
        "schema_version": 1,
        "stage": "S5",
        "facts_allowed": bool(local_evidence),
        "minimum_evidence_sources": 1,
        "sources": local_evidence,
        "citation_policy": {
            "no_sources_no_factual_claims": True,
            "record_content_hash": True,
            "record_line_refs": True,
        },
    }

    blocked_reasons: list[str] = []
    if not local_evidence:
        blocked_reasons.append("no_local_evidence")
    if trust_gate_present and not trust_gate_passed:
        blocked_reasons.append("s4_trust_gate_not_passed")

    recovery_packet = {
        "schema_version": 1,
        "stage": "S5",
        "status": "blocked" if blocked_reasons else "ready_for_review",
        "blocked_reasons": blocked_reasons,
        "recovery_actions": [
            "build_or_refresh_local_search_index",
            "collect_mock_or_approved_sources",
            "rerun_s4_trust_validation_before_active_dispatch",
        ],
        "replanning_decision": "collect_evidence" if blocked_reasons else "review_evidence",
    }

    phase_acceptance = {
        "schema_version": 1,
        "stage": "S5",
        "acceptance": {
            "research_plan_generated": True,
            "source_plan_generated": True,
            "evidence_ledger_generated": True,
            "private_sources_blocked_by_policy": True,
            "local_search_evidence_count": len(local_evidence),
            "s4_gate_checked": trust_gate_present,
            "no_network_used": True,
        },
        "verdict": "pass" if local_evidence or not local_index_path else "needs_evidence",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "research_plan": out_dir / "research_plan.yml",
        "source_plan": out_dir / "source_plan.yml",
        "evidence_ledger": out_dir / "evidence_ledger.yml",
        "recovery_packet": out_dir / "recovery_packet.yml",
        "phase_acceptance_evidence": out_dir / "phase_acceptance_evidence.yml",
    }
    atomic_write_yaml(paths["research_plan"], research_plan)
    atomic_write_yaml(paths["source_plan"], source_plan)
    atomic_write_yaml(paths["evidence_ledger"], evidence_ledger)
    atomic_write_yaml(paths["recovery_packet"], recovery_packet)
    atomic_write_yaml(paths["phase_acceptance_evidence"], phase_acceptance)

    return {
        "ok": True,
        "topic": effective_topic,
        "local_evidence_count": len(local_evidence),
        "s4_gate_checked": trust_gate_present,
        "artifacts": {key: str(path) for key, path in paths.items()},
    }
