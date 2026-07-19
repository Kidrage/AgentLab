"""Acceptance harness for longform narrative generation projects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import re
import shutil
import subprocess

import yaml

from agent_runtime.narrative_delivery import (
    REQUIRED_REVIEW_GATES,
    narrative_delivery_integrity_issues,
    validate_chapter_state_plan,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
)
from agent_runtime.crown_candidate_audit import validate_writer_execution_contract
from agent_runtime.policies import ensure_safe_task_id
from agent_runtime.report_sanitizer import write_report_yaml
from agent_runtime.writer_output_materializer import (
    REQUIRED_WRITER_OUTPUTS,
    materialize_writer_candidate_content,
    materialize_writer_candidate_result,
)


DEFAULT_SUITE = "crown_reset_acceptance_v1"
DEFAULT_CHAPTERS = [1, 2, 3]
DEFAULT_SCALE_CHAPTERS = 1500
ALLOWED_FORESHADOWING_STATUSES = ["introduced", "touched", "escalated", "resolved", "deferred"]
VALID_MODES = {"audit-only", "mock", "live"}
CHAPTER_ATTEMPT_OUTPUTS = (
    *REQUIRED_WRITER_OUTPUTS,
    "artifact_lineage.yml",
    "continuity_failure_report.yml",
    "fiction_review.yml",
    "live_generation_error.yml",
    "live_generation_request.yml",
    "live_writer_cli_fallback.yml",
    "revision_or_rewrite_proposal.yml",
    "writer_contract_retry_feedback.yml",
    "writer_retry_ledger.yml",
    "writer_transport_retry.yml",
    "writer_cli_fallback_capture.md",
    "writer_output_contract.yml",
    "writer_role_session_capture.md",
    "model_execution_chain_writer.yml",
    "outbound_context_manifest_writer.yml",
)
CHAPTER_REGENERATION_INPUTS = (
    "chapter_packet.yml",
    "candidate_fact_ledger.yml",
    "workflow_plan.yml",
    "live_writer_role_session_guard.yml",
)


def _project_root(root: Path, project: str) -> Path:
    return Path(root) / "projects" / project


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _clear_chapter_attempt_outputs(
    run_dir: Path,
    *,
    replacement_reason: str | None = None,
    clear_generation_inputs: bool = False,
) -> None:
    """Remove stale candidate-derived files before a non-resumed attempt."""
    contract_path = run_dir / "writer_output_contract.yml"
    error_path = run_dir / "live_generation_error.yml"
    contract: dict[str, Any] = {}
    error: dict[str, Any] = {}
    for path, target in ((contract_path, contract), (error_path, error)):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            data = {}
        if isinstance(data, dict):
            target.update(data)

    should_archive = (
        contract.get("status") == "blocked"
        or error.get("status") == "blocked"
        or bool(replacement_reason)
    )
    if should_archive and any(
        (run_dir / name).is_file()
        for name in (*CHAPTER_ATTEMPT_OUTPUTS, *CHAPTER_REGENERATION_INPUTS)
    ):
        archive_root = run_dir / "rejected_attempts"
        index = 1
        while (archive_root / f"resume_{index:03d}").exists():
            index += 1
        archive_dir = archive_root / f"resume_{index:03d}"
        archive_dir.mkdir(parents=True, exist_ok=False)
        archived: list[str] = []
        candidates = [
            *(run_dir / filename for filename in CHAPTER_ATTEMPT_OUTPUTS),
            *(run_dir / filename for filename in CHAPTER_REGENERATION_INPUTS),
            *sorted(run_dir.glob("writer_retry_attempt_*")),
            *sorted(run_dir.glob("model_execution_receipt_writer_*.yml")),
        ]
        for path in candidates:
            if not path.is_file() or path.name in archived:
                continue
            shutil.copy2(path, archive_dir / path.name)
            archived.append(path.name)
        _write_yaml(
            archive_dir / "rejection.yml",
            {
                "schema_version": 1,
                "status": "rejected",
                "candidate_only": True,
                "production_modified": False,
                "reason": replacement_reason or "blocked_chapter_attempt_replaced_on_resume",
                "contract_issues": contract.get("issues") or [],
                "live_generation_error": error.get("error") or error.get("message"),
                "archived_files": archived,
            },
        )
    for filename in CHAPTER_ATTEMPT_OUTPUTS:
        (run_dir / filename).unlink(missing_ok=True)
    if clear_generation_inputs:
        for filename in CHAPTER_REGENERATION_INPUTS:
            (run_dir / filename).unlink(missing_ok=True)
    for path in run_dir.glob("writer_retry_attempt_*"):
        path.unlink(missing_ok=True)
    for path in run_dir.glob("model_execution_receipt_writer_*.yml"):
        path.unlink(missing_ok=True)


WRITER_MAX_CONTRACT_REDOS = 1


def _writer_contract_issues(run_dir: Path) -> list[str]:
    path = run_dir / "writer_output_contract.yml"
    if not path.is_file():
        return []
    try:
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ["invalid_writer_output_contract_yaml"]
    issues = contract.get("issues") if isinstance(contract, dict) else []
    return [str(issue) for issue in issues] if isinstance(issues, list) else []


def _snapshot_writer_contract_attempt(run_dir: Path, attempt: int) -> dict[str, str]:
    snapshots: dict[str, str] = {}
    for source_name, suffix in (
        ("writer_role_session_capture.md", "capture.md"),
        ("writer_output_contract.yml", "contract.yml"),
    ):
        source = run_dir / source_name
        if not source.is_file():
            continue
        target = run_dir / f"writer_retry_attempt_{attempt:02d}_{suffix}"
        target.write_bytes(source.read_bytes())
        snapshots[source_name] = target.name
    return snapshots


def _write_writer_contract_retry_feedback(
    run_dir: Path,
    *,
    attempt: int,
    chapter: int,
    issues: list[str],
) -> None:
    """Persist exact schema corrections for the single full Writer redo."""
    character_ranges: dict[str, list[int]] = {}
    try:
        packet = yaml.safe_load(
            (run_dir / "chapter_packet.yml").read_text(encoding="utf-8")
        ) or {}
        intent = packet.get("chapter_intent") or {}
        for field in ("target_character_range", "hard_character_range"):
            value = intent.get(field)
            if (
                isinstance(value, list)
                and len(value) == 2
                and all(isinstance(item, int) for item in value)
            ):
                character_ranges[field] = value
    except (OSError, yaml.YAMLError, AttributeError):
        pass
    _write_yaml(
        run_dir / "writer_contract_retry_feedback.yml",
        {
            "schema_version": 1,
            "status": "correction_required",
            "source_attempt": attempt,
            "chapter": chapter,
            "issues": issues,
            "draft_character_contract": character_ranges,
            "instructions": [
                "Emit all four complete AGENTLAB_EDIT blocks again in the required order.",
                "Use the exact canonical fields and enum values below; do not use aliases.",
                "Keep prose candidate-only and do not write production.",
            ],
            "required_envelopes": {
                "continuity_ledger.yml": {
                    "schema_version": 1,
                    "chapter": chapter,
                    "baseline_mode": "reset" if chapter == 1 else "continuation",
                    "timeline": {
                        "monotonic": True,
                    },
                    "plot_state_changes": "list",
                    "character_changes": "list",
                    "relationship_or_worldline_changes": "list",
                    "foreshadowing": "list",
                },
                "state_transition_proposal.yml": {
                    "schema_version": 1,
                    "status": "candidate",
                    "chapter": chapter,
                    "requires_user_promotion": True,
                    "events": [
                        {
                            "event_type": "chapter_state_change",
                            "scope": "candidate_only",
                            "summary": "concrete chapter fact",
                        }
                    ],
                },
                "narrative_delivery_receipt.yml": {
                    "schema_version": 1,
                    "status": "pass",
                    "candidate_only": True,
                    "checks": {
                        "chapter_and_title": "pass",
                        "required_beats": "pass",
                        "continuity_outputs": "pass",
                        "production_untouched": "pass",
                        "deprecated_sources_excluded": "pass",
                    },
                },
            },
            "forbidden_aliases": {
                "state_transition_proposal.status": ["proposal_not_promoted"],
                "narrative_delivery_receipt.status": ["candidate_delivered"],
                "narrative_delivery_receipt.checks": ["quality_gate_checks"],
            },
        },
    )


def _collect(project_root: Path, patterns: list[str], *, limit: int = 200) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(project_root.glob(pattern)):
            if len(found) >= limit:
                return found
            if path.is_file():
                found.append(_rel(path, project_root))
    return found


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_eval_task_id(chapter: int, eval_id: str) -> str:
    cleaned_eval_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(eval_id)).strip("_-") or "eval"
    return ensure_safe_task_id(f"task_narrative_eval_ch{chapter:02d}_{cleaned_eval_id}"[:85])


def _predecessor_identity_issues(run_dir: Path, task_id: str, expected_chapter: int) -> list[str]:
    packet_path = run_dir / "chapter_packet.yml"
    if not packet_path.is_file():
        return ["predecessor_chapter_packet_missing"]
    try:
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ["predecessor_chapter_packet_invalid"]
    issues: list[str] = []
    if not isinstance(packet, dict):
        return ["predecessor_chapter_packet_invalid"]
    if packet.get("task_id") != task_id:
        issues.append("predecessor_task_id_mismatch")
    if packet.get("chapter") != expected_chapter:
        issues.append("predecessor_chapter_mismatch")
    issues.extend(narrative_delivery_integrity_issues(run_dir))
    return issues


def _candidate_chapter_sources(task_id: str) -> list[str]:
    return [
        f"runs/{task_id}/fiction_draft.md",
        f"runs/{task_id}/continuity_ledger.yml",
        f"runs/{task_id}/state_transition_proposal.yml",
    ]


def _candidate_events_from_run(run_dir: Path, chapter: int, task_id: str) -> list[dict[str, Any]]:
    proposal_path = run_dir / "state_transition_proposal.yml"
    if not proposal_path.is_file():
        return []
    try:
        proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    events = proposal.get("events") if isinstance(proposal, dict) else []
    return [
        {
            **event,
            "source_chapter": chapter,
            "source_task_id": task_id,
            "event_index": index,
        }
        for index, event in enumerate(events or [], start=1)
        if isinstance(event, dict)
    ]


def _candidate_history_through_run(
    run_dir: Path,
    chapter: int,
    task_id: str,
) -> list[dict[str, Any]]:
    """Rebuild cumulative candidate facts from a chapter's rolling ledger and proposal."""
    ledger_path = run_dir / "candidate_fact_ledger.yml"
    prior_events: list[dict[str, Any]] = []
    if ledger_path.is_file():
        try:
            ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            ledger = {}
        events = ledger.get("events") if isinstance(ledger, dict) else []
        prior_events = [event for event in events or [] if isinstance(event, dict)]
    return [*prior_events, *_candidate_events_from_run(run_dir, chapter, task_id)]


def _write_candidate_fact_ledger(
    run_dir: Path,
    events: list[dict[str, Any]],
) -> str | None:
    if not events:
        return None
    path = run_dir / "candidate_fact_ledger.yml"
    _write_yaml(
        path,
        {
            "schema_version": 1,
            "status": "candidate",
            "promoted": False,
            "through_chapter": max(int(event["source_chapter"]) for event in events),
            "event_count": len(events),
            "events": events,
        },
    )
    return f"runs/{run_dir.name}/candidate_fact_ledger.yml"


def _write_light_chapter_workflow_plan(
    root: Path,
    project: str,
    task_id: str,
    run_dir: Path,
    *,
    writer_budget_mode: str = "balanced",
) -> Any | None:
    try:
        from agent_runtime.routing.route_catalog import RouteCatalog
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from routing.route_catalog import RouteCatalog

    narrative_route_key = "narrative_light_chapter"
    narrative_agents = RouteCatalog.from_file(
        root / "config" / "routing_rules.yml"
    ).agents_for(narrative_route_key)
    fallback = {
        "route": {
            "route_key": narrative_route_key,
            "agents": narrative_agents,
        },
        "production_pack": {
            "pack_id": "narrative_longform",
            "mode": "light_chapter",
            "candidate_only": True,
        },
    }
    try:
        from workflow_plan import build_workflow_plan

        plan = build_workflow_plan(
            root,
            project,
            task_id,
            user_request_path=run_dir / "user_request.md",
            budget_mode=writer_budget_mode,
        )
        data = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else fallback
        route = data.setdefault("route", {})
        if route.get("route_key") == "fiction_chapter_pipeline":
            route["route_key"] = narrative_route_key
        route.setdefault("route_key", narrative_route_key)
        route.setdefault("agents", narrative_agents)
        data.setdefault("production_pack", fallback["production_pack"])
    except Exception:
        plan = None
        data = fallback
    _write_yaml(run_dir / "workflow_plan.yml", data)
    return plan


def _chapter_number(path: Path) -> int | None:
    patterns = [
        r"第\s*0*(\d+)\s*章",
        r"chapter[_\s-]*0*(\d+)",
        r"ch[_\s-]*0*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path.name, re.I)
        if match:
            return int(match.group(1))
    return None


def _production_chapters(project_root: Path) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for rel in _collect(project_root, ["production/manuscript/**/*.md"], limit=500):
        path = project_root / rel
        chapters.append({"chapter": _chapter_number(path), "path": rel, "status": "deprecated_for_reset_eval"})
    return sorted(chapters, key=lambda item: (item["chapter"] is None, item["chapter"] or 0, item["path"]))


def _audit_fact_sources(project_root: Path, project: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    required_files = [
        (project_root / "project_artifact_index.yml", "artifact_index_present"),
        (project_root / "project_brain" / "project_fact_snapshot.yml", "fact_snapshot_present"),
    ]
    for path, check in required_files:
        if not path.exists():
            issues.append({"severity": "error", "check": check, "message": f"missing {_rel(path, project_root)}"})

    bible_refs = _collect(project_root, ["production/bible/**/*.md"], limit=20)
    outline_refs = _collect(project_root, ["production/outlines/**/*.md"], limit=20)
    if not bible_refs:
        issues.append({"severity": "error", "check": "bible_present", "message": "missing production/bible/**/*.md"})
    if not outline_refs:
        issues.append({"severity": "error", "check": "outline_present", "message": "missing production/outlines/**/*.md"})

    revision_log = project_root / "project_brain" / "revision_log.jsonl"
    if not revision_log.exists():
        warnings.append({"severity": "warning", "check": "revision_log_present", "message": "missing project_brain/revision_log.jsonl"})

    deprecated_chapters = _production_chapters(project_root)
    return {
        "status": "fail" if issues else "pass",
        "project": project,
        "live_generation_blocked": bool(issues),
        "required_sources": {
            "artifact_index": "project_artifact_index.yml",
            "fact_snapshot": "project_brain/project_fact_snapshot.yml",
            "bible_refs": bible_refs,
            "outline_refs": outline_refs,
        },
        "deprecated_production_chapters": deprecated_chapters,
        "issues": issues + warnings,
    }


def _audit_history(project_root: Path) -> dict[str, Any]:
    deprecated_chapters = _production_chapters(project_root)
    rebuild_paths: list[str] = []
    for path in sorted(project_root.rglob("*rebuild*")):
        if len(rebuild_paths) >= 100:
            break
        rebuild_paths.append(_rel(path, project_root))

    run_findings: list[dict[str, Any]] = []
    blocked_live_runs: list[dict[str, Any]] = []
    runs_dir = project_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir())[-100:]:
            if (run_dir / "narrative_audit_manifest.yml").is_file():
                continue
            prompt = run_dir / "user_request.md"
            prompt_text = prompt.read_text(encoding="utf-8", errors="replace") if prompt.exists() else ""
            if re.search(r"(fiction|chapter|novel|rewrite|revise|小说|章节|重写|修改)", prompt_text, re.I):
                delivery = validate_narrative_delivery(run_dir)
                missing = [
                    str(issue.get("file"))
                    for issue in delivery.get("issues", [])
                    if issue.get("check") == "delivery_file_present" and issue.get("file")
                ]
                if missing:
                    live_error = _load_live_generation_error(run_dir, project_root)
                    if live_error:
                        blocked_live_runs.append(
                            {
                                "task_id": run_dir.name,
                                "missing": missing,
                                "path": _rel(run_dir, project_root),
                                "live_generation_error": live_error,
                            }
                        )
                    else:
                        run_findings.append({"task_id": run_dir.name, "missing": missing, "path": _rel(run_dir, project_root)})

    return {
        "status": "warn" if deprecated_chapters or rebuild_paths or run_findings or blocked_live_runs else "pass",
        "deprecated_production_chapters": deprecated_chapters,
        "legacy_rebuild_paths": rebuild_paths,
        "incomplete_historical_narrative_runs": run_findings,
        "blocked_live_generation_runs": blocked_live_runs,
        "policy": "Historical manuscript and rebuild runs are audit evidence only during reset evaluation.",
    }


def _mock_draft(project: str, chapter: int) -> str:
    seed = (
        f"# 第{chapter:02d}章 候选稿\n\n"
        f"{project} reset acceptance candidate chapter {chapter}.\n\n"
        "灰谷镇的钟声在晨雾里低低回响，主角没有沿用旧稿中的选择，而是从新的事实快照出发。"
        "本章推进一个明确剧情状态：队伍确认灰冠余烬仍在边境传递命令。"
        "本章推进一个明确人物状态：主角从被动防守转为主动追索证据。"
        "本章推进一个关系或世界线状态：地方守卫与流亡书记官形成临时同盟。"
        "线索被登记在伏笔账本中，等待后续章节触碰、升级或回收。\n\n"
    )
    paragraph = (
        "雾气贴着石阶流动，书记官把烧焦的缎带压在地图角上，"
        "每个人都必须为新的判断付出代价：守卫交出巡逻路线，主角承认旧避难所已经不安全，"
        "而远处堡垒的旗语说明敌方没有停在上一章的状态里。"
    )
    body = "\n\n".join(paragraph for _ in range(52))
    return seed + body + "\n"


def _write_structured_delivery_files(
    run_dir: Path,
    *,
    chapter: int,
    previous: list[str],
    created_by: str,
    baseline_mode: str,
    include_review: bool = True,
) -> None:
    draft_path = run_dir / "fiction_draft.md"
    draft = draft_path.read_text(encoding="utf-8", errors="replace") if draft_path.exists() else ""
    character_count_ok = 4500 <= len(draft) <= 5500
    if include_review:
        review = {
            "schema_version": 1,
            "verdict": "pass" if character_count_ok else "fail",
            "blocking": not character_count_ok,
            "chapter": chapter,
            "character_count": len(draft),
            "target_character_range": [4500, 5500],
            "gates": {
                gate: {
                    "status": "pass" if gate != "word_count" or character_count_ok else "fail",
                    "evidence": f"structured evidence for {gate}",
                }
                for gate in REQUIRED_REVIEW_GATES
            },
            "required_state_changes": {
                "plot_state_change": "The border command channel is confirmed active.",
                "character_state_change": "The protagonist shifts from defense to evidence pursuit.",
                "relationship_or_worldline_progress": "A local guard and exile scribe enter a provisional alliance.",
            },
            "foreshadowing": [
                {"id": f"coa-reset-{chapter:02d}-ash-ribbon", "status": "introduced", "evidence": "burned ribbon on the map"},
            ],
        }
        _write_yaml(run_dir / "fiction_review.yml", review)
        if not (run_dir / "fiction_review.md").exists():
            (run_dir / "fiction_review.md").write_text("# Fiction Review\n\nStructured review stored in fiction_review.yml.\n", encoding="utf-8")
    _write_yaml(
        run_dir / "continuity_ledger.yml",
        {
            "schema_version": 1,
            "chapter": chapter,
            "baseline_mode": baseline_mode,
            "previous_candidate_sources": previous,
            "timeline": {"monotonic": True, "chapter_day": chapter},
            "worldline_changes": ["enemy command channel remains active"],
            "character_changes": ["protagonist becomes more proactive"],
            "foreshadowing": [
                {"id": f"coa-reset-{chapter:02d}-ash-ribbon", "status": "introduced"},
            ],
        },
    )
    _write_yaml(
        run_dir / "state_transition_proposal.yml",
        {
            "schema_version": 1,
            "status": "candidate",
            "chapter": chapter,
            "events": [
                {
                    "event_type": "chapter_state_change",
                    "scope": "candidate_only",
                    "summary": f"Reset acceptance chapter {chapter} advances plot, character, and worldline state.",
                }
            ],
            "requires_user_promotion": True,
        },
    )
    _write_yaml(
        run_dir / "artifact_lineage.yml",
        {
            "schema_version": 1,
            "chapter": chapter,
            "created_by": created_by,
            "production_modified": False,
            "previous_candidate_sources": previous,
        },
    )
    write_narrative_delivery_receipt(run_dir)


def _write_mock_chapter_outputs(
    run_dir: Path,
    project: str,
    chapter: int,
    previous: list[str],
    baseline_mode: str,
) -> None:
    draft = _mock_draft(project, chapter)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "fiction_draft.md").write_text(draft, encoding="utf-8")
    _write_structured_delivery_files(
        run_dir,
        chapter=chapter,
        previous=previous,
        created_by="narrative-eval mock harness",
        baseline_mode=baseline_mode,
    )


def _capacity_failure_metadata(result: Any) -> dict[str, Any]:
    """Copy normalized capacity facts without parsing provider logs locally."""
    raw_usage = getattr(result, "raw_usage", None)
    raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
    return {
        key: raw_usage[key]
        for key in (
            "failure_class",
            "capacity_route",
            "capacity_pool",
            "capacity_status",
            "capacity_reset_at",
        )
        if raw_usage.get(key) is not None
    }


def _write_live_generation_error(run_dir: Path, *, agent: str, result: Any) -> None:
    data = {
        "schema_version": 1,
        "status": "blocked",
        "agent": agent,
        "result_status": getattr(result, "status", "unknown"),
        "provider": getattr(result, "provider", None),
        "model": getattr(result, "model", None),
        "error": getattr(result, "error", None) or "agent did not produce the required output",
    }
    data.update(_capacity_failure_metadata(result))
    _write_yaml(run_dir / "live_generation_error.yml", data)


def _write_live_guard_error(run_dir: Path, *, agent: str, guard: dict[str, Any]) -> None:
    _write_yaml(
        run_dir / "live_generation_error.yml",
        {
            "schema_version": 1,
            "status": "blocked",
            "agent": agent,
            "result_status": guard.get("status"),
            "provider": None,
            "model": None,
            "error": guard.get("message") or guard.get("reason"),
            "role_session_guard": guard,
        },
    )


def validate_narrative_live_role_session(
    project: str,
    task_id: str,
    role_session: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate Writer role-session evidence required by live narrative eval."""
    if not role_session:
        return {
            "status": "blocked",
            "reason": "missing_role_session",
            "message": "live narrative eval requires an AgentLab Writer role-session packet",
        }
    checks: list[dict[str, Any]] = []

    def check(ok: bool, check_id: str, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": message})

    binding = role_session.get("binding") if isinstance(role_session.get("binding"), dict) else {}
    check(role_session.get("packet_type") == "agentlab_role_session", "packet_type", "packet is an AgentLab role-session")
    check(role_session.get("role") == "Writer", "role_owner", "role-session belongs to Writer")
    check(binding.get("allowed") is True, "binding_allowed", "role binding is allowed")
    check(role_session.get("project") == project, "project_match", "role-session project matches narrative eval")
    check(role_session.get("task_id") == task_id, "task_id_match", "role-session task_id matches chapter run")
    failed = [item for item in checks if item["status"] != "pass"]
    if failed:
        return {
            "status": "blocked",
            "reason": "invalid_role_session",
            "message": "live narrative eval must be owned by an allowed Writer role-session",
            "checks": checks,
        }
    return {
        "status": "pass",
        "reason": None,
        "checks": checks,
        "role": role_session.get("role"),
        "worker": role_session.get("worker"),
        "project": role_session.get("project"),
        "task_id": role_session.get("task_id"),
    }


def _try_writer_cli_fallback(
    root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    result: Any,
) -> bool:
    if getattr(result, "error", None) == "writer_outbound_context_gate_blocked":
        return False
    script = Path(root) / "agentlab.sh"
    if not script.exists():
        return False

    timeout = int(os.getenv("AGENTLAB_LIVE_WRITER_TIMEOUT_SECONDS", "300"))
    attempts = max(1, int(os.getenv("AGENTLAB_LIVE_WRITER_CLI_ATTEMPTS", "2")))
    command = [
        str(script),
        "run-agent",
        "Writer",
        "--project",
        project,
        "--task-id",
        task_id,
        "--execute",
        "--force",
        "--no-apply-patches",
        "--overwrite-report",
        "--output",
        "writer_cli_fallback_capture.md",
    ]
    if getattr(result, "provider", None):
        command.extend(["--provider", str(getattr(result, "provider"))])
    if getattr(result, "model", None):
        command.extend(["--model", str(getattr(result, "model"))])
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        attempt_records: list[dict[str, Any]] = []
        status = "blocked"
        for attempt in range(1, attempts + 1):
            fallback_capture = run_dir / "writer_cli_fallback_capture.md"
            fallback_capture.unlink(missing_ok=True)
            completed = subprocess.run(
                command,
                cwd=root,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            materialized = False
            if completed.returncode == 0 and fallback_capture.is_file():
                materialized = materialize_writer_candidate_content(
                    fallback_capture.read_text(encoding="utf-8", errors="replace"),
                    run_dir,
                    task_id,
                    capture_name="writer_cli_fallback_capture.md",
                )
            attempt_status = "completed" if materialized else "blocked"
            attempt_records.append(
                {
                    "attempt": attempt,
                    "status": attempt_status,
                    "exit_code": completed.returncode,
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                }
            )
            status = attempt_status
            if status == "completed":
                break
        _write_yaml(
            run_dir / "live_writer_cli_fallback.yml",
            {
                "schema_version": 1,
                "status": status,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "trigger_result_status": getattr(result, "status", None),
                "trigger_provider": getattr(result, "provider", None),
                "trigger_model": getattr(result, "model", None),
                "trigger_error": getattr(result, "error", None),
                "attempts": attempt_records,
            },
        )
        return status == "completed"
    except Exception as exc:
        _write_yaml(
            run_dir / "live_writer_cli_fallback.yml",
            {
                "schema_version": 1,
                "status": "blocked",
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "trigger_result_status": getattr(result, "status", None),
                "trigger_provider": getattr(result, "provider", None),
                "trigger_model": getattr(result, "model", None),
                "trigger_error": getattr(result, "error", None),
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        return False


def _load_live_generation_error(run_dir: Path, root: Path) -> dict[str, Any] | None:
    error_path = run_dir / "live_generation_error.yml"
    if not error_path.exists():
        return None
    try:
        data = yaml.safe_load(error_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        data = {"status": "blocked", "error": f"could not parse live generation error: {exc}"}
    data["path"] = _rel(error_path, root)
    return data


def _write_live_chapter_outputs(
    root: Path,
    run_dir: Path,
    project: str,
    task_id: str,
    chapter: int,
    previous: list[str],
    *,
    allow_writer_cli_fallback: bool = False,
    writer_budget_mode: str = "balanced",
    workflow_plan: Any | None = None,
    clear_attempt_outputs: bool = True,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    if clear_attempt_outputs:
        _clear_chapter_attempt_outputs(run_dir)
    _write_yaml(
        run_dir / "live_generation_request.yml",
        {
            "schema_version": 1,
            "project": project,
            "chapter": chapter,
            "previous_candidate_sources": previous,
            "status": "ready_for_internal_writer_role_session",
            "execution_scope": "internal_agentlab_writer_role_session",
            "candidate_only": True,
            "writer_role_session_required": True,
            "writer_cli_fallback_allowed": allow_writer_cli_fallback,
            "provider_surface_fallback_allowed": False,
            "model_capacity_governance": "centralized",
            "required_outputs": [
                "fiction_draft.md",
                "continuity_ledger.yml",
                "state_transition_proposal.yml",
                "narrative_delivery_receipt.yml",
            ],
            "supplementary_outputs": [
                "artifact_lineage.yml",
            ],
        },
    )
    try:
        from agent_runner import run_agent_model
        from workflow_plan import build_workflow_plan

        plan = workflow_plan or build_workflow_plan(
            root,
            project,
            task_id,
            user_request_path=run_dir / "user_request.md",
            budget_mode=writer_budget_mode,
        )
        writer_result = None
        writer_materialized = False
        retry_attempts: list[dict[str, Any]] = []
        contract_redos = 0
        max_attempts = 1 + WRITER_MAX_CONTRACT_REDOS
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                (run_dir / "writer_role_session_capture.md").unlink(missing_ok=True)
                (run_dir / "writer_output_contract.yml").unlink(missing_ok=True)
            writer_result = run_agent_model(
                root,
                plan,
                "Writer",
                run_dir / "writer_role_session_capture.md",
                apply_patches=False,
                allow_cli_api_fallback=False,
            )
            writer_materialized = materialize_writer_candidate_result(
                writer_result,
                run_dir,
                task_id,
            )
            raw_usage = getattr(writer_result, "raw_usage", None)
            raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
            record = {
                "attempt": attempt,
                "result_status": getattr(writer_result, "status", None),
                "provider": getattr(writer_result, "provider", None),
                "model": getattr(writer_result, "model", None),
                "failure_class": raw_usage.get("failure_class"),
                "command_id": raw_usage.get("command_id"),
                "materialized": writer_materialized,
                "resolved_model_key": raw_usage.get("resolved_model_key"),
                "resolved_cli_model_id": raw_usage.get("cli_model_id"),
            }
            if writer_materialized or attempt == max_attempts:
                retry_attempts.append(record)
                break

            contract_issues = _writer_contract_issues(run_dir)
            if (
                getattr(writer_result, "status", None) == "completed"
                and contract_issues
                and contract_redos < WRITER_MAX_CONTRACT_REDOS
            ):
                record["retry_kind"] = "full_contract_redo"
                record["contract_issues"] = contract_issues
                record["snapshots"] = _snapshot_writer_contract_attempt(
                    run_dir,
                    attempt,
                )
                _write_writer_contract_retry_feedback(
                    run_dir,
                    attempt=attempt,
                    chapter=chapter,
                    issues=contract_issues,
                )
                contract_redos += 1
                retry_attempts.append(record)
                continue

            retry_attempts.append(record)
            break

        if len(retry_attempts) > 1:
            _write_yaml(
                run_dir / "writer_retry_ledger.yml",
                {
                    "schema_version": 1,
                    "status": "recovered" if writer_materialized else "blocked",
                    "role": "Writer",
                    "model_capacity_governance": "centralized",
                    "limits": {
                        "full_contract_redos": WRITER_MAX_CONTRACT_REDOS,
                        "total_attempts": max_attempts,
                    },
                    "attempts": retry_attempts,
                },
            )

        if not writer_materialized:
            fallback_completed = (
                allow_writer_cli_fallback
                and _try_writer_cli_fallback(root, run_dir, project, task_id, writer_result)
            )
            if not fallback_completed:
                _write_live_generation_error(run_dir, agent="Writer", result=writer_result)
                return

        _write_yaml(
            run_dir / "artifact_lineage.yml",
            {
                "schema_version": 1,
                "chapter": chapter,
                "created_by": "AgentLab Writer role-session",
                "production_modified": False,
                "previous_candidate_sources": previous,
                "writer_outputs_preserved": True,
                "harness_generated_story_state": False,
            },
        )
    except Exception as exc:
        _write_yaml(
            run_dir / "live_generation_error.yml",
            {
                "schema_version": 1,
                "status": "blocked",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )


def _generate_chapters(
    root: Path,
    project: str,
    suite: str,
    chapters: list[int],
    mode: str,
    eval_dir: Path,
    deprecated_sources: list[str],
    eval_id: str,
    writer_worker: str | None = None,
    resume_valid: bool = False,
    stop_on_block: bool = False,
    allow_writer_cli_fallback: bool = False,
    chapter_state_plan: str | None = None,
    writer_budget_mode: str = "balanced",
    predecessor_task_id: str | None = None,
) -> dict[str, Any]:
    project_root = _project_root(root, project)
    generated: list[dict[str, Any]] = []
    previous_sources: list[str] = []
    candidate_fact_events: list[dict[str, Any]] = []
    resume_chain_intact = True
    if chapters and chapters[0] > 1:
        previous_chapter = chapters[0] - 1
        previous_task_id = (
            ensure_safe_task_id(predecessor_task_id)
            if predecessor_task_id
            else _safe_eval_task_id(previous_chapter, eval_id)
        )
        previous_run_dir = project_root / "runs" / previous_task_id
        previous_delivery = validate_narrative_delivery(previous_run_dir)
        predecessor_identity_issues = _predecessor_identity_issues(
            previous_run_dir,
            previous_task_id,
            previous_chapter,
        )
        previous_execution = (
            validate_writer_execution_contract(previous_run_dir, previous_task_id)
            if mode == "live"
            else {"status": "pass"}
        )
        if (
            not previous_delivery.get("valid")
            or previous_execution.get("status") != "pass"
            or predecessor_identity_issues
        ):
            return {
                "status": "blocked",
                "reason": "previous candidate chapter is unavailable or has invalid Writer provenance",
                "chapters": [],
                "selected_chapter_count": len(chapters),
                "completed_chapter_count": 0,
                "resume_valid": resume_valid,
                "stop_on_block": stop_on_block,
                "allow_writer_cli_fallback": allow_writer_cli_fallback,
                "chapter_state_plan": chapter_state_plan,
                "writer_budget_mode": writer_budget_mode,
                "predecessor_task_id": previous_task_id,
                "previous_chapter": previous_chapter,
                "previous_delivery": previous_delivery,
                "previous_writer_execution": previous_execution,
                "predecessor_identity_issues": predecessor_identity_issues,
                "model_capacity_governance": "centralized",
            }
        previous_sources = _candidate_chapter_sources(previous_task_id)
        candidate_fact_events = _candidate_history_through_run(
            previous_run_dir,
            previous_chapter,
            previous_task_id,
        )
    for chapter in chapters:
        task_id = _safe_eval_task_id(chapter, eval_id)
        run_dir = project_root / "runs" / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        existing_delivery = validate_narrative_delivery(run_dir)
        existing_execution = (
            validate_writer_execution_contract(run_dir, task_id)
            if mode == "live"
            else {"status": "pass"}
        )
        if (
            resume_valid
            and resume_chain_intact
            and existing_delivery.get("valid")
            and not existing_delivery.get("skipped")
            and existing_execution.get("status") == "pass"
        ):
            generated.append({
                "chapter": chapter,
                "task_id": task_id,
                "run_dir": _rel(run_dir, root),
                "mode": mode,
                "delivery": existing_delivery,
                "production_modified": False,
                "resumed_existing": True,
            })
            previous_sources = _candidate_chapter_sources(task_id)
            candidate_fact_events.extend(_candidate_events_from_run(run_dir, chapter, task_id))
            _write_generation_checkpoint(eval_dir, suite, chapters, generated)
            continue
        replacement_reason = None
        if resume_valid and any(
            (run_dir / name).is_file()
            for name in (*CHAPTER_ATTEMPT_OUTPUTS, *CHAPTER_REGENERATION_INPUTS)
        ):
            if not existing_delivery.get("valid"):
                replacement_reason = "invalid_candidate_delivery_replaced_on_resume"
            elif existing_execution.get("status") != "pass":
                replacement_reason = "invalid_writer_execution_contract_replaced_on_resume"
            else:
                replacement_reason = "upstream_candidate_regenerated_on_resume"
        if resume_valid:
            resume_chain_intact = False
        _clear_chapter_attempt_outputs(
            run_dir,
            replacement_reason=replacement_reason,
            clear_generation_inputs=True,
        )
        baseline_mode = "reset" if chapter == 1 else "continuation"
        baseline_instruction = (
            "Start from the reset fact snapshot and do not read any deprecated manuscript."
            if baseline_mode == "reset"
            else "Continue only from the previous candidate sources named by chapter_packet.yml."
        )
        (run_dir / "user_request.md").write_text(
            (
                f"Generate candidate chapter {chapter} for {project}. "
                "Fulfill chapter_intent and beat_plan in chapter_packet.yml. "
                f"{baseline_instruction} Do not write production or promote candidate facts."
            ),
            encoding="utf-8",
        )
        workflow_plan = _write_light_chapter_workflow_plan(
            root,
            project,
            task_id,
            run_dir,
            writer_budget_mode=writer_budget_mode,
        )
        candidate_fact_ledger = _write_candidate_fact_ledger(run_dir, candidate_fact_events)
        write_chapter_packet(
            root,
            project,
            task_id,
            chapter,
            baseline_mode=baseline_mode,
            previous_chapters=previous_sources,
            deprecated_sources=deprecated_sources,
            candidate_fact_ledger=candidate_fact_ledger,
            chapter_state_plan=chapter_state_plan,
        )
        if mode == "mock":
            _write_mock_chapter_outputs(run_dir, project, chapter, previous_sources, baseline_mode)
        elif mode == "live":
            role_session = None
            if writer_worker:
                try:
                    from agent_runtime.protocols import build_role_session

                    role_session = build_role_session(root, "Writer", writer_worker, project=project, task_id=task_id)
                except Exception as exc:
                    role_session = {
                        "packet_type": "agentlab_role_session",
                        "role": "Writer",
                        "worker": writer_worker,
                        "project": project,
                        "task_id": task_id,
                        "binding": {"allowed": False, "reason": f"role-session generation failed: {type(exc).__name__}: {exc}"},
                    }
            guard = validate_narrative_live_role_session(project, task_id, role_session)
            _write_yaml(run_dir / "live_writer_role_session_guard.yml", guard)
            if guard.get("status") == "pass":
                _write_live_chapter_outputs(
                    root,
                    run_dir,
                    project,
                    task_id,
                    chapter,
                    previous_sources,
                    allow_writer_cli_fallback=allow_writer_cli_fallback,
                    writer_budget_mode=writer_budget_mode,
                    workflow_plan=workflow_plan,
                    clear_attempt_outputs=False,
                )
            else:
                _write_live_guard_error(run_dir, agent="Writer", guard=guard)

        delivery = validate_narrative_delivery(run_dir)
        record = {
            "chapter": chapter,
            "task_id": task_id,
            "run_dir": _rel(run_dir, root),
            "mode": mode,
            "baseline_mode": baseline_mode,
            "delivery": delivery,
            "production_modified": False,
        }
        live_error = _load_live_generation_error(run_dir, root)
        if live_error:
            record["live_generation_error"] = live_error
        generated.append(record)
        if delivery.get("valid"):
            previous_sources = _candidate_chapter_sources(task_id)
            candidate_fact_events.extend(_candidate_events_from_run(run_dir, chapter, task_id))
        _write_generation_checkpoint(eval_dir, suite, chapters, generated)
        if stop_on_block and not delivery.get("valid"):
            break

    _write_generation_checkpoint(eval_dir, suite, chapters, generated)
    completed_chapters = {item["chapter"] for item in generated if item["delivery"].get("valid")}
    all_selected_completed = all(chapter in completed_chapters for chapter in chapters)
    return {
        "status": "pass" if all_selected_completed else "blocked",
        "chapters": generated,
        "selected_chapter_count": len(chapters),
        "completed_chapter_count": len(completed_chapters),
        "resume_valid": resume_valid,
        "stop_on_block": stop_on_block,
        "allow_writer_cli_fallback": allow_writer_cli_fallback,
        "chapter_state_plan": chapter_state_plan,
        "writer_budget_mode": writer_budget_mode,
        "predecessor_task_id": predecessor_task_id,
        "model_capacity_governance": "centralized",
    }


def _write_generation_checkpoint(
    eval_dir: Path,
    suite: str,
    selected_chapters: list[int],
    generated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    quality_rows = [
        {
            "chapter": item["chapter"],
            "task_id": item["task_id"],
            "status": "pass" if item["delivery"].get("valid") else "blocked",
            "blocking_issue_count": len([issue for issue in item["delivery"].get("issues", []) if issue.get("severity") == "error"]),
            "production_modified": False,
            "resumed_existing": bool(item.get("resumed_existing")),
        }
        for item in generated
    ]
    _write_yaml(eval_dir / "chapter_quality_matrix.yml", {"suite": suite, "chapters": quality_rows})
    _write_yaml(
        eval_dir / "continuity_failure_report.yml",
        {
            "suite": suite,
            "blocking_failures": [
                {"chapter": item["chapter"], "issues": item["delivery"].get("issues", [])}
                for item in generated
                if not item["delivery"].get("valid")
            ],
        },
    )
    completed = [row["chapter"] for row in quality_rows if row["status"] == "pass"]
    attempted = {row["chapter"] for row in quality_rows}
    next_chapter = next((chapter for chapter in selected_chapters if chapter not in attempted), None)
    blocking_chapter = next((row["chapter"] for row in quality_rows if row["status"] == "blocked"), None)
    blocking_record = next(
        (item for item in generated if item["chapter"] == blocking_chapter),
        {},
    )
    blocking_error = blocking_record.get("live_generation_error") or {}
    capacity = {
        key: blocking_error[key]
        for key in (
            "failure_class",
            "capacity_route",
            "capacity_pool",
            "capacity_status",
            "capacity_reset_at",
        )
        if key in blocking_error
    }
    _write_yaml(
        eval_dir / "generation_checkpoint.yml",
        {
            "schema_version": 1,
            "suite": suite,
            "selected_chapters": selected_chapters,
            "selected_chapter_count": len(selected_chapters),
            "attempted_chapter_count": len(quality_rows),
            "completed_chapters": completed,
            "completed_chapter_count": len(completed),
            "blocking_chapter": blocking_chapter,
            "next_chapter": next_chapter,
            "resume_chapter": blocking_chapter or next_chapter,
            "capacity": capacity or None,
            "status": (
                "blocked" if blocking_chapter is not None
                else "complete" if len(completed) == len(selected_chapters)
                else "in_progress"
            ),
            "production_modified": False,
        },
    )
    return quality_rows


def _build_scale_simulation(eval_dir: Path, suite: str, chapter_count: int = DEFAULT_SCALE_CHAPTERS) -> dict[str, Any]:
    phase_size = chapter_count // 3
    second_checkpoint = max(1, phase_size)
    third_checkpoint = max(1, phase_size * 2)
    governance_cadence = {
        "chapter_ledger": "every chapter",
        "continuity_batch_audit": "every 3 chapters",
        "character_foreshadowing_timeline_audit": "every 10 chapters",
        "volume_heavy_audit": "each part boundary",
        "promotion_gate": "before production promotion",
    }
    memory_contract = {
        "required_inputs": [
            "project_fact_snapshot.yml",
            "project_artifact_index.yml",
            "chapter_packet.yml",
            "previous continuity_ledger.yml",
        ],
        "candidate_outputs": [
            "fiction_draft.md",
            "continuity_ledger.yml",
            "state_transition_proposal.yml",
            "narrative_delivery_receipt.yml",
        ],
        "promotion_requires": [
            "accepted state_transition_proposal.yml",
            "updated fact events or fact snapshot proposal",
            "narrative-eval or narrative_heavy_audit pass",
        ],
    }
    series_arc = {
        "schema_version": 1,
        "suite": suite,
        "chapter_count": chapter_count,
        "target_total_chapters": chapter_count,
        "simulation_scope": "governance_ledger_only",
        "parts": [
            {"part": 1, "chapters": [1, phase_size], "phase": "survival_and_discovery"},
            {"part": 2, "chapters": [phase_size + 1, phase_size * 2], "phase": "war_and_cost"},
            {"part": 3, "chapters": [phase_size * 2 + 1, chapter_count], "phase": "reckoning_and_rebuild"},
        ],
        "governance_cadence": governance_cadence,
    }
    chapter_state_plan = {
        "chapter_count": chapter_count,
        "target_total_chapters": chapter_count,
        "simulation_scope": "governance_ledger_only",
        "timeline_monotonic": True,
        "state_delta_every_chapter": True,
        "sample_checkpoints": [
            {"chapter": 1, "plot": "new baseline opens", "worldline": "local threat appears"},
            {"chapter": second_checkpoint, "plot": "regional war cost peaks", "worldline": "alliances fracture"},
            {"chapter": third_checkpoint, "plot": "hidden cause is exposed", "worldline": "empire legitimacy collapses"},
            {"chapter": chapter_count, "plot": "primary arc resolves", "worldline": "new order remains unstable"},
        ],
        "governance_cadence": governance_cadence,
    }
    foreshadowing = {
        "allowed_statuses": ALLOWED_FORESHADOWING_STATUSES,
        "items": [
            {"id": "ash-ribbon", "introduced": 1, "touched": 12, "escalated": 90, "resolved": 240, "status": "resolved"},
            {"id": "silent-crown", "introduced": 30, "touched": 300, "escalated": 760, "resolved": 1320, "status": "resolved"},
            {"id": "border-ledger", "introduced": 5, "touched": 44, "escalated": 450, "status": "deferred", "defer_reason": "third-part payoff"},
        ],
    }
    character_arc = {
        "arcs_have_phase_changes": True,
        "major_arcs": [
            {"character": "protagonist", "phase_changes": [1, 180, 620, 1180, 1500]},
            {"character": "exile_scribe", "phase_changes": [1, 220, 700, 1100, 1450]},
        ],
    }
    timeline_worldline = {
        "timeline_monotonic": True,
        "worldline_phase_changes": [1, 500, 1000, 1500],
        "static_worldline_detected": False,
    }
    _write_yaml(eval_dir / "series_arc_ledger.yml", series_arc)
    _write_yaml(eval_dir / "chapter_state_plan.yml", chapter_state_plan)
    _write_yaml(eval_dir / "foreshadowing_ledger.yml", foreshadowing)
    _write_yaml(eval_dir / "character_arc_ledger.yml", character_arc)
    _write_yaml(eval_dir / "timeline_worldline_ledger.yml", timeline_worldline)
    report = {
        "suite": suite,
        "chapter_count": chapter_count,
        "target_total_chapters": chapter_count,
        "status": "pass",
        "simulation_scope": "governance_ledger_only",
        "text_generation": {
            "draft_chapters_generated": 0,
            "draft_text_generated": False,
            "reason": "L3 validates longform governance capacity; it does not generate manuscript prose.",
        },
        "timeline_monotonic": True,
        "foreshadowing_statuses_valid": all(item["status"] in ALLOWED_FORESHADOWING_STATUSES for item in foreshadowing["items"]),
        "character_arcs_have_phase_changes": True,
        "worldline_has_phase_progression": True,
        "governance_cadence": governance_cadence,
        "memory_contract": memory_contract,
        "promotion_gates": list(memory_contract["promotion_requires"]),
        "ledgers": {
            "series_arc": "series_arc_ledger.yml",
            "chapter_state_plan": "chapter_state_plan.yml",
            "foreshadowing": "foreshadowing_ledger.yml",
            "character_arc": "character_arc_ledger.yml",
            "timeline_worldline": "timeline_worldline_ledger.yml",
        },
    }
    _write_yaml(eval_dir / "series_scale_simulation.yml", report)
    return report


def _write_reset_proposal(eval_dir: Path, project: str, deprecated_sources: list[str]) -> dict[str, Any]:
    proposal = {
        "schema_version": 1,
        "project": project,
        "status": "pending_user_confirmation",
        "action": "start_new_manuscript_baseline",
        "production_modified": False,
        "deprecated_sources": deprecated_sources,
        "replacement_source": "acceptance candidate chapters generated by narrative-eval",
        "promotion_policy": "User confirmation is required before any candidate is copied into production/manuscript.",
    }
    _write_yaml(eval_dir / "manuscript_reset_proposal.yml", proposal)
    return proposal


def run_narrative_eval(
    root: Path,
    project: str,
    *,
    suite: str = DEFAULT_SUITE,
    mode: str = "live",
    chapters: list[int] | None = None,
    timestamp: str | None = None,
    writer_worker: str | None = None,
    resume_valid: bool = False,
    stop_on_block: bool = False,
    allow_writer_cli_fallback: bool = False,
    chapter_state_plan: str | None = None,
    writer_budget_mode: str = "balanced",
    predecessor_task_id: str | None = None,
) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}")
    selected_chapters = chapters or list(DEFAULT_CHAPTERS)
    root = Path(root)
    project_root = _project_root(root, project)
    eval_id = timestamp or _timestamp()
    eval_dir = root / "acceptance_runs" / "narrative_eval" / project / suite / eval_id
    eval_dir.mkdir(parents=True, exist_ok=True)

    l0 = _audit_fact_sources(project_root, project)
    l1 = _audit_history(project_root)
    deprecated_sources = [item["path"] for item in l1["deprecated_production_chapters"]]
    reset_proposal = _write_reset_proposal(eval_dir, project, deprecated_sources)

    if chapter_state_plan:
        chapter_state_plan_validation = validate_chapter_state_plan(
            project_root,
            chapter_state_plan,
            expected_chapters=selected_chapters,
        )
    elif len(selected_chapters) > 5 and mode != "audit-only":
        chapter_state_plan_validation = {
            "schema_version": 1,
            "status": "fail",
            "path": None,
            "chapter_count": 0,
            "selected_chapter_count": len(selected_chapters),
            "issues": [
                {
                    "check": "long_batch_requires_chapter_state_plan",
                    "message": (
                        "generation requests over five chapters must bind a validated "
                        "run-local chapter state plan"
                    ),
                }
            ],
        }
    else:
        chapter_state_plan_validation = {
            "schema_version": 1,
            "status": "skipped",
            "path": None,
            "chapter_count": 0,
            "selected_chapter_count": len(selected_chapters),
            "issues": [],
        }
    write_report_yaml(
        eval_dir / "chapter_state_plan_validation.yml",
        chapter_state_plan_validation,
        root,
    )

    if l0["status"] != "pass":
        l2 = {"status": "blocked", "reason": "L0 fact source health failed", "chapters": []}
    elif chapter_state_plan_validation["status"] == "fail":
        l2 = {
            "status": "blocked",
            "reason": "chapter state plan validation failed",
            "chapters": [],
            "chapter_state_plan_validation": chapter_state_plan_validation,
        }
    elif mode == "audit-only":
        l2 = {"status": "skipped", "reason": "audit-only mode", "chapters": []}
    else:
        l2 = _generate_chapters(
            root,
            project,
            suite,
            selected_chapters,
            mode,
            eval_dir,
            deprecated_sources,
            eval_id,
            writer_worker=writer_worker,
            resume_valid=resume_valid,
            stop_on_block=stop_on_block,
            allow_writer_cli_fallback=allow_writer_cli_fallback,
            chapter_state_plan=chapter_state_plan,
            writer_budget_mode=writer_budget_mode,
            predecessor_task_id=predecessor_task_id,
        )

    l3 = _build_scale_simulation(eval_dir, suite)
    overall_status = "pass"
    if l0["status"] != "pass" or l2["status"] == "blocked" or l3["status"] != "pass":
        overall_status = "fail"
    elif l1["status"] == "warn" or l2["status"] == "skipped":
        overall_status = "warn"

    report = {
        "schema_version": 1,
        "suite": suite,
        "project": project,
        "mode": mode,
        "writer_worker": writer_worker,
        "resume_valid": resume_valid,
        "stop_on_block": stop_on_block,
        "allow_writer_cli_fallback": allow_writer_cli_fallback,
        "chapter_state_plan": chapter_state_plan,
        "writer_budget_mode": writer_budget_mode,
        "predecessor_task_id": predecessor_task_id,
        "chapter_state_plan_validation": chapter_state_plan_validation,
        "model_capacity_governance": "centralized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "acceptance_run_dir": _rel(eval_dir, root),
        "production_modified": False,
        "baseline": {
            "start_from_chapter": min(selected_chapters) if selected_chapters else 1,
            "old_chapters_deprecated": True,
            "old_chapters_used_as_continuity_source": False,
        },
        "layers": {
            "L0_fact_source_health": l0,
            "L1_historical_audit": l1,
            "L2_real_chapter_sample": l2,
            "L3_series_scale_simulation": l3,
        },
        "reports": {
            "longform_eval_report": "longform_eval_report.yml",
            "chapter_quality_matrix": "chapter_quality_matrix.yml",
            "continuity_failure_report": "continuity_failure_report.yml",
            "series_scale_simulation": "series_scale_simulation.yml",
            "manuscript_reset_proposal": "manuscript_reset_proposal.yml",
            "chapter_state_plan_validation": "chapter_state_plan_validation.yml",
        },
        "reset_proposal": reset_proposal,
    }
    write_report_yaml(eval_dir / "longform_eval_report.yml", report, root)
    return report
