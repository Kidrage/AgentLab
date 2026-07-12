"""Local audit for Crown of Ash live narrative candidate runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml

try:
    from narrative_delivery import validate_narrative_delivery
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.narrative_delivery import validate_narrative_delivery


DEFAULT_CROWN_LIVE_RUN = "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _draft_metrics(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    words = text.split()
    return {
        "exists": path.exists(),
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "nonempty_lines": len(nonempty_lines),
        "word_like_tokens": len(words),
        "has_heading": text.lstrip().startswith("#"),
    }


def _production_manuscript_files(project_root: Path) -> list[str]:
    manuscript_root = project_root / "production" / "manuscript"
    if not manuscript_root.exists():
        return []
    return [
        str(path.relative_to(project_root))
        for path in sorted(manuscript_root.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]


def build_crown_live_candidate_audit(
    root: Path,
    *,
    task_id: str = DEFAULT_CROWN_LIVE_RUN,
) -> dict[str, Any]:
    """Build an evidence-only audit for the known Crown live candidate run."""
    root = root.resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    run_dir = project_root / "runs" / task_id
    required = [
        "chapter_packet.yml",
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    ]
    missing = [name for name in required if not (run_dir / name).exists()]
    delivery = validate_narrative_delivery(run_dir)
    packet = _read_yaml(run_dir / "chapter_packet.yml")
    ledger = _read_yaml(run_dir / "continuity_ledger.yml")
    proposal = _read_yaml(run_dir / "state_transition_proposal.yml")
    receipt = _read_yaml(run_dir / "narrative_delivery_receipt.yml")
    draft = _draft_metrics(run_dir / "fiction_draft.md")
    production_files = _production_manuscript_files(project_root)

    checks = [
        {
            "id": "required_files_present",
            "status": "pass" if not missing else "fail",
            "missing": missing,
        },
        {
            "id": "delivery_protocol_valid",
            "status": "pass" if delivery.get("valid") is True else "fail",
            "delivery": delivery,
        },
        {
            "id": "draft_substantial",
            "status": "pass" if draft["lines"] >= 100 and draft["bytes"] >= 5000 else "fail",
            "metrics": draft,
        },
        {
            "id": "chapter_packet_reset_baseline",
            "status": "pass"
            if packet.get("chapter") == 1
            and packet.get("baseline_mode") == "reset"
            and packet.get("previous_chapters") == []
            else "fail",
            "chapter": packet.get("chapter"),
            "baseline_mode": packet.get("baseline_mode"),
            "previous_chapters": packet.get("previous_chapters"),
        },
        {
            "id": "continuity_ledger_candidate_scope",
            "status": "pass"
            if ledger.get("schema_version") == 1
            and ledger.get("chapter") == 1
            and ledger.get("baseline_mode") == "reset"
            and isinstance(ledger.get("timeline"), dict)
            else "fail",
            "chapter": ledger.get("chapter"),
            "baseline_mode": ledger.get("baseline_mode"),
            "timeline": ledger.get("timeline"),
        },
        {
            "id": "state_transition_candidate_only",
            "status": "pass"
            if proposal.get("status") == "candidate"
            and proposal.get("requires_user_promotion") is True
            and all(event.get("scope") == "candidate_only" for event in proposal.get("events", []) if isinstance(event, dict))
            else "fail",
            "proposal_status": proposal.get("status"),
            "requires_user_promotion": proposal.get("requires_user_promotion"),
            "events": proposal.get("events", []),
        },
        {
            "id": "receipt_passes",
            "status": "pass" if receipt.get("status") == "pass" and receipt.get("delivery_check", {}).get("valid") is True else "fail",
            "receipt_status": receipt.get("status"),
            "delivery_check": receipt.get("delivery_check"),
        },
        {
            "id": "production_manuscript_not_modified",
            "status": "pass" if not production_files else "fail",
            "production_manuscript_files": list(production_files),
        },
    ]
    issues = [check for check in checks if check.get("status") != "pass"]
    return {
        "schema_version": 1,
        "report_type": "agentlab_crown_live_candidate_audit",
        "root": str(root),
        "project": "Crown_of_Ash",
        "task_id": task_id,
        "run_dir": str(run_dir),
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "evidence": [str(run_dir / name) for name in required],
        "summary": {
            "draft_lines": draft["lines"],
            "draft_bytes": draft["bytes"],
            "candidate_chapter": packet.get("chapter"),
            "candidate_only": proposal.get("status") == "candidate",
            "production_manuscript_files": list(production_files),
        },
        "issues": issues,
    }


def write_crown_live_candidate_audit(root: Path, out: Path, *, task_id: str = DEFAULT_CROWN_LIVE_RUN) -> dict[str, Any]:
    report = build_crown_live_candidate_audit(root, task_id=task_id)
    write_report_yaml(out, report, root)
    return report
