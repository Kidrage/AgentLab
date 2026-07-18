"""Local audit for Crown of Ash live narrative candidate runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
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

try:
    from narrative_repetition import (
        repetition_evidence_from_paragraphs,
        substantive_paragraphs,
    )
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.narrative_repetition import (
        repetition_evidence_from_paragraphs,
        substantive_paragraphs,
    )


DEFAULT_CROWN_LIVE_RUN = "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback"
BATCH_REQUIRED_FILES = (
    "chapter_packet.yml",
    "fiction_draft.md",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "narrative_delivery_receipt.yml",
    "writer_output_contract.yml",
)
BATCH_LEDGER_LISTS = (
    "plot_state_changes",
    "character_changes",
    "relationship_or_worldline_changes",
    "foreshadowing",
)
BATCH_RECEIPT_CHECKS = (
    "chapter_and_title",
    "required_beats",
    "continuity_outputs",
    "production_untouched",
    "deprecated_sources_excluded",
)
AGY_HIGH_MODEL_LABEL = "Gemini 3.5 Flash (High)"


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


def production_manuscript_files(project_root: Path) -> list[str]:
    """Public candidate-boundary check shared by background delivery workers."""
    return _production_manuscript_files(project_root)


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


def _completion_task_id(chapter: int, eval_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", eval_id).strip("_-") or "eval"
    return f"task_narrative_eval_ch{chapter:02d}_{cleaned}"[:85]


def _candidate_sources(task_id: str) -> list[str]:
    return [
        f"runs/{task_id}/fiction_draft.md",
        f"runs/{task_id}/continuity_ledger.yml",
        f"runs/{task_id}/state_transition_proposal.yml",
    ]


def _model_label(log_path: Path) -> str | None:
    if not log_path.is_file():
        return None
    labels = re.findall(
        r'Propagating selected model override to backend: label="([^"]+)"',
        log_path.read_text(encoding="utf-8", errors="replace"),
    )
    return labels[-1] if labels else None


def validate_writer_execution_contract(run_dir: Path, task_id: str) -> dict[str, Any]:
    """Validate Writer provenance against the execution contract recorded by the run."""
    workflow = _read_yaml(run_dir / "workflow_plan.yml")
    guard = _read_yaml(run_dir / "live_writer_role_session_guard.yml")
    chain_path = run_dir / "model_execution_chain_writer.yml"
    chain = _read_yaml(chain_path)

    included_agents = workflow.get("included_agents")
    writer_agent = (
        included_agents.get("Writer")
        if isinstance(included_agents, dict)
        and isinstance(included_agents.get("Writer"), dict)
        else {}
    )
    model_profiles = workflow.get("model_profiles")
    writer_model = (
        model_profiles.get("Writer")
        if isinstance(model_profiles, dict)
        and isinstance(model_profiles.get("Writer"), dict)
        else {}
    )
    expected_provider = writer_model.get("provider")
    expected_model = writer_model.get("model")
    expected_worker = writer_agent.get("execution_owner")
    legacy_agy = (
        expected_provider == "agy-gemini-oauth"
        and expected_model == "gemini-3.5-flash-high"
    )
    if not expected_worker and legacy_agy:
        expected_worker = "agy"

    issues: list[str] = []
    if workflow.get("task_id") != task_id:
        issues.append("workflow_task_id")
    if not expected_provider or not expected_model:
        issues.append("workflow_writer_model")
    if not expected_worker:
        issues.append("workflow_execution_owner")
    if guard.get("status") != "pass":
        issues.append("role_session_guard_status")
    if guard.get("role") != "Writer":
        issues.append("role_session_guard_role")
    if guard.get("task_id") != task_id:
        issues.append("role_session_guard_task_id")
    if guard.get("project") != "Crown_of_Ash":
        issues.append("role_session_guard_project")
    if expected_worker and guard.get("worker") != expected_worker:
        issues.append("role_session_guard_worker")

    mode = "model_execution_chain"
    observed_provider = None
    observed_model = None
    if chain_path.is_file():
        final = chain.get("final") if isinstance(chain.get("final"), dict) else {}
        attempts = chain.get("attempts") if isinstance(chain.get("attempts"), list) else []
        observed_provider = final.get("provider")
        observed_model = final.get("model")
        if chain.get("role") != "Writer":
            issues.append("model_chain_role")
        if chain.get("status") != "pass":
            issues.append("model_chain_status")
        if chain.get("fallback_used") is not False:
            issues.append("model_chain_fallback")
        if any(
            isinstance(attempt, dict) and attempt.get("fallback_detected") is True
            for attempt in attempts
        ):
            issues.append("model_chain_attempt_fallback")
        if final.get("status") != "pass":
            issues.append("model_chain_final_status")
        if observed_provider != expected_provider:
            issues.append("model_chain_provider")
        if observed_model != expected_model:
            issues.append("model_chain_model")
    else:
        mode = "legacy_agy_log"
        observed_provider = "agy-gemini-oauth" if legacy_agy else None
        observed_model = "gemini-3.5-flash-high" if legacy_agy else None
        if not legacy_agy:
            issues.append("model_chain_missing")
        if _model_label(run_dir / "command_logs" / "agy_cli_agent.log") != AGY_HIGH_MODEL_LABEL:
            issues.append("legacy_agy_model_label")

    return {
        "status": "pass" if not issues else "fail",
        "mode": mode,
        "expected": {
            "worker": expected_worker,
            "provider": expected_provider,
            "model": expected_model,
        },
        "observed": {
            "worker": guard.get("worker"),
            "provider": observed_provider,
            "model": observed_model,
        },
        "fallback_used": chain.get("fallback_used") if chain_path.is_file() else False,
        "issues": issues,
    }


def build_crown_completion_batch_audit(
    root: Path,
    *,
    eval_id: str,
    through_chapter: int,
) -> dict[str, Any]:
    """Audit one resumable Crown candidate chain without calling a provider."""
    if through_chapter < 1:
        raise ValueError("through_chapter must be at least 1")

    root = root.resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    runs_root = project_root / "runs"
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    normalizations: list[dict[str, Any]] = []
    retry_ledgers: list[dict[str, Any]] = []
    local_recoveries: list[dict[str, Any]] = []
    rejected_attempts: list[str] = []
    repetition_findings: list[dict[str, Any]] = []
    prior_drafts: list[tuple[int, set[str]]] = []
    seen_drafts: dict[str, int] = {}
    cumulative_events = 0
    fact_ledger_started = False

    for chapter in range(1, through_chapter + 1):
        task_id = _completion_task_id(chapter, eval_id)
        run_dir = runs_root / task_id
        missing = [name for name in BATCH_REQUIRED_FILES if not (run_dir / name).is_file()]
        chapter_issues: list[str] = [f"missing:{name}" for name in missing]
        if missing:
            issues.extend(
                {"chapter": chapter, "check": "required_file", "message": item}
                for item in chapter_issues
            )
            chapters.append({"chapter": chapter, "task_id": task_id, "status": "fail", "issues": chapter_issues})
            continue

        packet = _read_yaml(run_dir / "chapter_packet.yml")
        ledger = _read_yaml(run_dir / "continuity_ledger.yml")
        proposal = _read_yaml(run_dir / "state_transition_proposal.yml")
        receipt = _read_yaml(run_dir / "narrative_delivery_receipt.yml")
        contract = _read_yaml(run_dir / "writer_output_contract.yml")
        writer_execution = validate_writer_execution_contract(run_dir, task_id)
        delivery = validate_narrative_delivery(run_dir)
        draft = (run_dir / "fiction_draft.md").read_text(encoding="utf-8", errors="replace")
        intent = packet.get("chapter_intent") if isinstance(packet.get("chapter_intent"), dict) else {}
        hard_range = intent.get("hard_character_range") or [3000, 8000]
        expected_baseline = "reset" if chapter == 1 else "continuation"
        previous = packet.get("previous_candidate_sources")
        if previous is None:
            previous = packet.get("previous_chapters") or []
        expected_previous = [] if chapter == 1 else _candidate_sources(
            _completion_task_id(chapter - 1, eval_id)
        )
        events = proposal.get("events") if isinstance(proposal.get("events"), list) else []
        checks = {
            "delivery_valid": delivery.get("valid") is True,
            "packet_chapter": packet.get("chapter") == chapter,
            "baseline": packet.get("baseline_mode") == expected_baseline
            and ledger.get("baseline_mode") == expected_baseline,
            "previous_chain": previous == expected_previous,
            "ledger_chapter": ledger.get("chapter") == chapter,
            "ledger_lists": all(isinstance(ledger.get(name), list) and ledger.get(name) for name in BATCH_LEDGER_LISTS),
            "contract": contract.get("status") == "pass",
            "draft_range": isinstance(hard_range, list)
            and len(hard_range) == 2
            and all(isinstance(value, int) for value in hard_range)
            and hard_range[0] <= len(draft) <= hard_range[1],
            "draft_heading": next((line for line in draft.splitlines() if line.strip()), "").startswith("#"),
            "proposal": proposal.get("chapter") == chapter
            and proposal.get("status") == "candidate"
            and proposal.get("requires_user_promotion") is True
            and bool(events)
            and all(isinstance(event, dict) and event.get("scope") == "candidate_only" for event in events),
            "receipt": receipt.get("status") == "pass"
            and receipt.get("candidate_only") is True
            and all((receipt.get("checks") or {}).get(name) == "pass" for name in BATCH_RECEIPT_CHECKS),
            "writer_execution_contract": writer_execution.get("status") == "pass",
        }
        draft_hash = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        checks["unique_draft"] = draft_hash not in seen_drafts
        seen_drafts[draft_hash] = chapter

        draft_paragraphs = substantive_paragraphs(draft)
        for source_chapter, previous_paragraphs in prior_drafts:
            evidence = repetition_evidence_from_paragraphs(
                draft_paragraphs,
                previous_paragraphs,
            )
            if not evidence["blocking"]:
                continue
            finding = {
                "chapter": chapter,
                "source_chapter": source_chapter,
                **evidence,
            }
            repetition_findings.append(finding)
            if "cross_chapter_repetition" not in chapter_issues:
                chapter_issues.append("cross_chapter_repetition")
            issues.append(
                {
                    "chapter": chapter,
                    "check": "cross_chapter_repetition",
                    "message": (
                        f"substantive prose repeats chapter {source_chapter}: "
                        f"passages={evidence['passage_count']}, "
                        f"characters={evidence['repeated_characters']}, "
                        f"longest={evidence['longest_passage_characters']}"
                    ),
                }
            )
        prior_drafts.append((chapter, draft_paragraphs))

        fact_path = run_dir / "candidate_fact_ledger.yml"
        if fact_path.is_file():
            fact_ledger_started = True
            facts = _read_yaml(fact_path)
            checks["candidate_fact_ledger"] = (
                facts.get("through_chapter") == chapter - 1
                and facts.get("event_count") == cumulative_events
                and facts.get("promoted") is False
            )
        elif fact_ledger_started:
            checks["candidate_fact_ledger"] = False
        elif chapter > 1:
            warnings.append(
                {
                    "chapter": chapter,
                    "check": "candidate_fact_ledger",
                    "message": "candidate fact ledger predates rolling-ledger activation",
                }
            )

        for check, passed in checks.items():
            if not passed:
                chapter_issues.append(check)
                issues.append({"chapter": chapter, "check": check, "message": "check failed"})

        normalizations.extend(
            {"chapter": chapter, **item}
            for item in (contract.get("normalizations") or [])
            if isinstance(item, dict)
        )
        retry_path = run_dir / "writer_retry_ledger.yml"
        if retry_path.is_file():
            retry = _read_yaml(retry_path)
            retry_ledgers.append(
                {
                    "chapter": chapter,
                    "status": retry.get("status"),
                    "attempt_count": len(retry.get("attempts") or []),
                }
            )
        recovery_path = run_dir / "local_materialization_recovery.yml"
        if recovery_path.is_file():
            recovery = _read_yaml(recovery_path)
            local_recoveries.append(
                {"chapter": chapter, "status": recovery.get("status"), "path": str(recovery_path.relative_to(project_root))}
            )
        rejected_attempts.extend(
            str(path.relative_to(project_root))
            for path in sorted((run_dir / "rejected_attempts").glob("*/rejection.yml"))
        )
        chapters.append(
            {
                "chapter": chapter,
                "task_id": task_id,
                "status": "pass" if not chapter_issues else "fail",
                "draft_characters": len(draft),
                "candidate_event_count": len(events),
                "writer_execution": writer_execution,
                "issues": chapter_issues,
            }
        )
        cumulative_events += len(events)

    production_files = _production_manuscript_files(project_root)
    if production_files:
        issues.append(
            {
                "chapter": None,
                "check": "production_manuscript_not_modified",
                "message": "candidate generation wrote production manuscript files",
            }
        )
    lengths = [item["draft_characters"] for item in chapters if "draft_characters" in item]
    return {
        "schema_version": 1,
        "report_type": "agentlab_crown_completion_batch_audit",
        "project": "Crown_of_Ash",
        "eval_id": eval_id,
        "chapter_range": [1, through_chapter],
        "status": "pass" if not issues else "fail",
        "summary": {
            "selected_chapter_count": through_chapter,
            "valid_chapter_count": sum(item.get("status") == "pass" for item in chapters),
            "total_candidate_events": cumulative_events,
            "draft_character_range": [min(lengths), max(lengths)] if lengths else None,
            "normalization_count": sum(int(item.get("count") or 0) for item in normalizations),
            "retry_ledger_count": len(retry_ledgers),
            "local_recovery_count": len(local_recoveries),
            "rejected_attempt_count": len(rejected_attempts),
            "repetition_failure_count": len(repetition_findings),
            "repetition_chapter_count": len(
                {item["chapter"] for item in repetition_findings}
            ),
            "production_manuscript_files": production_files,
        },
        "chapters": chapters,
        "normalizations": normalizations,
        "retry_ledgers": retry_ledgers,
        "local_recoveries": local_recoveries,
        "rejected_attempts": rejected_attempts,
        "repetition_findings": repetition_findings,
        "warnings": warnings,
        "issues": issues,
    }


def write_crown_completion_batch_audit(
    root: Path,
    out: Path,
    *,
    eval_id: str,
    through_chapter: int,
) -> dict[str, Any]:
    report = build_crown_completion_batch_audit(
        root,
        eval_id=eval_id,
        through_chapter=through_chapter,
    )
    write_report_yaml(out, report, root)
    return report
