"""Audit the canonical Crown of Ash governance-scale evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


DEFAULT_SCALE_DIR = (
    Path("acceptance_runs")
    / "narrative_eval"
    / "Crown_of_Ash"
    / "crown_unique_blueprint_authority_audit_20260724"
    / "sealed_v5_user_policy_override_final"
)
CANONICAL_TARGET_CHAPTERS = 1980


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def build_crown_scale_governance_audit(root: Path, scale_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    run_dir = root / (scale_dir or DEFAULT_SCALE_DIR)
    simulation = _read_yaml(run_dir / "series_scale_simulation.yml")
    chapter_state = _read_yaml(run_dir / "chapter_state_plan.yml")
    ledgers = simulation.get("ledgers", {}) if isinstance(simulation.get("ledgers"), dict) else {}
    required_files = [
        run_dir / "series_scale_simulation.yml",
        run_dir / "chapter_state_plan.yml",
        run_dir / str(ledgers.get("series_arc", "series_arc_ledger.yml")),
        run_dir / str(ledgers.get("foreshadowing", "foreshadowing_ledger.yml")),
        run_dir / str(ledgers.get("character_arc", "character_arc_ledger.yml")),
        run_dir / str(ledgers.get("timeline_worldline", "timeline_worldline_ledger.yml")),
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    checks = [
        {
            "id": "target_chapter_count",
            "status": "pass"
            if simulation.get("target_total_chapters") == CANONICAL_TARGET_CHAPTERS
            and simulation.get("chapter_count") == CANONICAL_TARGET_CHAPTERS
            else "fail",
            "summary": f"target={simulation.get('target_total_chapters')}; simulated={simulation.get('chapter_count')}",
        },
        {
            "id": "governance_only_scope",
            "status": "pass"
            if simulation.get("simulation_scope") == "governance_ledger_only"
            and simulation.get("text_generation", {}).get("draft_text_generated") is False
            else "fail",
            "summary": "scale run validates governance only and does not claim generated prose",
        },
        {
            "id": "state_delta_every_chapter",
            "status": "pass" if chapter_state.get("state_delta_every_chapter") is True else "fail",
            "summary": "chapter-state plan requires state delta every chapter",
        },
        {
            "id": "continuity_cadence",
            "status": "pass"
            if simulation.get("governance_cadence", {}).get("continuity_batch_audit") == "every 3 chapters"
            and simulation.get("governance_cadence", {}).get("character_foreshadowing_timeline_audit") == "every 10 chapters"
            else "fail",
            "summary": "continuity and character/foreshadowing audit cadences are present",
        },
        {
            "id": "longform_invariants",
            "status": "pass"
            if simulation.get("timeline_monotonic") is True
            and simulation.get("foreshadowing_statuses_valid") is True
            and simulation.get("character_arcs_have_phase_changes") is True
            and simulation.get("worldline_has_phase_progression") is True
            else "fail",
            "summary": "timeline, foreshadowing, character arcs, and worldline invariants are marked valid",
        },
        {
            "id": "promotion_gates",
            "status": "pass"
            if "narrative-eval or narrative_heavy_audit pass" in (simulation.get("promotion_gates") or [])
            else "fail",
            "summary": "promotion requires narrative eval or heavy audit pass",
        },
        {
            "id": "ledger_files_present",
            "status": "pass" if not missing else "fail",
            "summary": f"required ledger files present={len(required_files) - len(missing)}/{len(required_files)}",
        },
    ]
    failures = [check for check in checks if check["status"] != "pass"]
    return {
        "schema_version": 1,
        "report_type": "crown_scale_governance_audit",
        "root": str(root),
        "scale_dir": str(run_dir),
        "status": "pass" if not failures else "fail",
        "chapter_count": simulation.get("chapter_count"),
        "target_total_chapters": simulation.get("target_total_chapters"),
        "scope": simulation.get("simulation_scope"),
        "text_generation_claimed": bool(simulation.get("text_generation", {}).get("draft_text_generated")),
        "checks": checks,
        "missing": missing,
        "evidence": [str(path) for path in required_files],
        "notes": [
            "This audit proves governance-scale capacity, not generated manuscript quality.",
            "1980-chapter prose acceptance still requires approved live generation and promotion gates.",
        ],
    }


def write_crown_scale_governance_audit(root: Path, out: Path) -> dict[str, Any]:
    report = build_crown_scale_governance_audit(root)
    write_report_yaml(out, report, root)
    return report
