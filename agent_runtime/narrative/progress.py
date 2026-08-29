"""Evidence-derived progress projection for governed longform projects."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from agent_runtime.narrative.state_store import NarrativeStateStore
from agent_runtime.task_runtime_v2 import TaskRuntime


_COMPLETED_STAGE_STATUSES = {"waiting_review", "accepted"}


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"narrative progress event ledger line {line_number} is invalid"
            ) from exc
        if not isinstance(event, dict):
            raise ValueError(
                f"narrative progress event ledger line {line_number} is not a mapping"
            )
        events.append(event)
    return events


def _target_total(project_root: Path, snapshot: Mapping[str, Any]) -> int | None:
    authority_path = project_root / "production" / "blueprint_authority.yml"
    if authority_path.is_file() and not authority_path.is_symlink():
        try:
            authority = yaml.safe_load(authority_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            authority = {}
        story = authority.get("story_contract") if isinstance(authority, Mapping) else {}
        target = story.get("target_total_chapters") if isinstance(story, Mapping) else None
        if isinstance(target, int) and not isinstance(target, bool) and target > 0:
            return target
    series = snapshot.get("series")
    target = series.get("planned_total_chapters") if isinstance(series, Mapping) else None
    return target if isinstance(target, int) and not isinstance(target, bool) and target > 0 else None


def _candidate_stages(root: Path, *, project: str) -> dict[int, dict[str, Any]]:
    runtime = TaskRuntime(root, project=project)
    stages: dict[int, dict[str, Any]] = {}
    for entry in runtime.list_tasks():
        projection = runtime.load_task(str(entry["task_id"]))
        task = projection.get("task") or {}
        if task.get("protocol_ref") != "narrative.chapter.v1":
            continue
        profile = task.get("input_profile") or {}
        chapter = profile.get("chapter")
        if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
            continue
        record = stages.setdefault(
            chapter,
            {
                "task_ids": [],
                "generated": False,
                "reviewed": False,
                "selected": False,
                "projected": False,
            },
        )
        record["task_ids"].append(str(entry["task_id"]))
        items = projection.get("work_items") or {}
        gates = projection.get("protocol_gates") or {}
        record["generated"] = record["generated"] or (
            (items.get("writer") or {}).get("status") in _COMPLETED_STAGE_STATUSES
        )
        record["reviewed"] = record["reviewed"] or (
            (items.get("senior_editor") or {}).get("status")
            in _COMPLETED_STAGE_STATUSES
        )
        record["selected"] = record["selected"] or "candidate_hash_bound" in gates
        record["projected"] = record["projected"] or (
            (items.get("state_projector") or {}).get("status")
            in _COMPLETED_STAGE_STATUSES
        )
    for record in stages.values():
        record["task_ids"] = sorted(set(record["task_ids"]))
    return stages


def _blueprint_statuses(root: Path, *, project: str) -> list[dict[str, Any]]:
    """Project candidate-only blueprint work from immutable Runtime events."""

    runtime = TaskRuntime(root, project=project)
    statuses: list[dict[str, Any]] = []
    for entry in runtime.list_tasks():
        projection = runtime.load_task(str(entry["task_id"]))
        task = projection.get("task") or {}
        if task.get("protocol_ref") != "narrative.blueprint.v1":
            continue
        profile = task.get("input_profile") or {}
        counts: dict[str, int] = {}
        ready: list[str] = []
        for work_item_id, work_item in (projection.get("work_items") or {}).items():
            status = str((work_item or {}).get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            if status == "ready":
                ready.append(str(work_item_id))
        attempts = projection.get("attempts") or {}
        failed_attempts = [
            {
                "attempt_id": str(attempt_id),
                "work_item_id": str(attempt.get("work_item_id") or ""),
                "error": str((attempt.get("outcome") or {}).get("error") or ""),
                "provider_status": str(
                    (attempt.get("outcome") or {}).get("provider_status") or ""
                ),
            }
            for attempt_id, attempt in attempts.items()
            if isinstance(attempt, Mapping) and attempt.get("status") == "failed"
        ]
        artifacts = [
            {
                "artifact_id": str(artifact.get("artifact_id") or ""),
                "version_id": str(version_id),
                "sha256": str(artifact.get("sha256") or ""),
            }
            for version_id, artifact in (projection.get("artifacts") or {}).items()
            if isinstance(artifact, Mapping)
        ]
        active_artifacts = [
            artifact
            for version_id, artifact in (projection.get("artifacts") or {}).items()
            if isinstance(artifact, Mapping)
            and artifact.get("disposition", "eligible") == "eligible"
        ]
        artifacts_by_hash: dict[str, set[str]] = {}
        for artifact in active_artifacts:
            digest = str(artifact.get("sha256") or "")
            if digest:
                artifacts_by_hash.setdefault(digest, set()).add(
                    str(artifact.get("artifact_id") or "")
                )
        hash_collisions = [
            {"sha256": digest, "artifact_ids": sorted(artifact_ids)}
            for digest, artifact_ids in artifacts_by_hash.items()
            if len(artifact_ids) > 1
        ]
        quality_issues = [
            "candidate_artifact_content_hash_collision:"
            + collision["sha256"]
            + ":"
            + ",".join(collision["artifact_ids"])
            for collision in hash_collisions
        ]
        story_blueprint_present = any(
            artifact.get("artifact_id") == "story_blueprint"
            for artifact in active_artifacts
        )
        if not story_blueprint_present:
            quality_issues.append("story_blueprint_candidate_missing")
        statuses.append(
            {
                "task_id": str(task.get("task_id") or entry["task_id"]),
                "title": str(task.get("title") or ""),
                "user_goal": str(task.get("user_goal") or ""),
                "goal_fingerprint": str(task.get("goal_fingerprint") or ""),
                "task_status": str(task.get("status") or "unknown"),
                "target_total_chapters": profile.get("target_count"),
                "source_creative_brief_sha256": str(
                    profile.get("source_creative_brief_sha256") or ""
                ),
                "work_item_status_counts": dict(sorted(counts.items())),
                "ready_work_items": sorted(ready),
                "succeeded_attempt_count": sum(
                    1
                    for attempt in attempts.values()
                    if isinstance(attempt, Mapping)
                    and attempt.get("status") == "succeeded"
                ),
                "failed_attempts": failed_attempts,
                "candidate_artifacts": sorted(
                    artifacts,
                    key=lambda item: (item["artifact_id"], item["version_id"]),
                ),
                "artifact_hash_collisions": sorted(
                    hash_collisions,
                    key=lambda item: item["sha256"],
                ),
                "automated_quality_issues": quality_issues,
                "automated_acceptance_ready": not quality_issues,
                "protocol_gates": sorted(
                    str(gate_id)
                    for gate_id in (projection.get("protocol_gates") or {})
                ),
            }
        )
    return sorted(statuses, key=lambda item: item["task_id"])


def build_narrative_progress(
    agentlab_root: Path,
    *,
    project: str,
    verify_ledger: bool = True,
) -> dict[str, Any]:
    """Rebuild current progress from Task Runtime and narrative state evidence."""

    if verify_ledger is not True:
        raise ValueError("unverified narrative progress is forbidden")
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve(strict=False)
    projects_root = (root / "projects").resolve(strict=False)
    if project_root == projects_root or projects_root not in project_root.parents:
        raise ValueError("narrative progress project path is unsafe")
    store = NarrativeStateStore(project_root / "project_brain", project=project)
    snapshot: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    ledger_sha256: str | None = None
    if store.events_path.is_file():
        snapshot = store.read()
        events = _load_events(store.events_path)
        ledger_sha256 = hashlib.sha256(store.events_path.read_bytes()).hexdigest()

    commit_events = {
        str(event.get("event_id") or ""): event
        for event in events
        if event.get("event_type") == "VERIFIED_CHAPTER_COMMITTED"
    }
    accepted_records: dict[int, dict[str, Any]] = {}
    for raw_chapter, raw_record in (snapshot.get("chapters") or {}).items():
        if not isinstance(raw_record, Mapping):
            continue
        try:
            chapter = int(raw_chapter)
        except (TypeError, ValueError):
            continue
        event = commit_events.get(str(raw_record.get("event_id") or ""))
        payload = event.get("payload") if isinstance(event, Mapping) else None
        if (
            not isinstance(payload, Mapping)
            or payload.get("chapter") != chapter
            or payload.get("artifact_sha256") != raw_record.get("artifact_sha256")
        ):
            continue
        accepted_records[chapter] = {
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "artifact_sha256": payload["artifact_sha256"],
        }

    accepted = sorted(accepted_records)
    highest_contiguous = 0
    for chapter in accepted:
        if chapter != highest_contiguous + 1:
            break
        highest_contiguous = chapter
    gaps = [
        chapter
        for chapter in range(1, (max(accepted) if accepted else 0) + 1)
        if chapter not in accepted_records
    ]
    blueprint_statuses = _blueprint_statuses(root, project=project)
    candidate_stages = _candidate_stages(root, project=project)
    all_chapters = sorted(set(candidate_stages) | set(accepted_records))
    chapter_statuses: list[dict[str, Any]] = []
    for chapter in all_chapters:
        record = {
            "chapter": chapter,
            **candidate_stages.get(
                chapter,
                {
                    "task_ids": [],
                    "generated": False,
                    "reviewed": False,
                    "selected": False,
                    "projected": False,
                },
            ),
            "accepted": chapter in accepted_records,
        }
        if chapter in accepted_records:
            record["acceptance_evidence"] = accepted_records[chapter]
        chapter_statuses.append(record)

    target_total = _target_total(project_root, snapshot)
    if target_total is None:
        blueprint_targets = {
            item["target_total_chapters"]
            for item in blueprint_statuses
            if isinstance(item.get("target_total_chapters"), int)
            and not isinstance(item.get("target_total_chapters"), bool)
        }
        if len(blueprint_targets) == 1:
            target_total = next(iter(blueprint_targets))
    return {
        "schema_version": "narrative-progress-report/v1",
        "status": "pass",
        "project": project,
        "target_total_chapters": target_total,
        "blueprint_statuses": blueprint_statuses,
        "accepted_chapters": accepted,
        "accepted_count": len(accepted),
        "highest_contiguous_accepted": highest_contiguous,
        "next_production_chapter": highest_contiguous + 1,
        "accepted_gaps": gaps,
        "chapter_statuses": chapter_statuses,
        "event_ledger": {
            "initialized": bool(events),
            "verified": bool(events),
            "path": (
                store.events_path.relative_to(project_root).as_posix()
                if store.events_path.is_file()
                else None
            ),
            "sha256": ledger_sha256,
            "event_count": len(events),
            "last_event_hash": events[-1].get("event_hash") if events else None,
            "state_sha256": snapshot.get("state_sha256"),
        },
        "open_promises": sorted(
            str(promise_id)
            for promise_id, value in (snapshot.get("promise_graph") or {}).items()
            if isinstance(value, Mapping)
            and value.get("status") not in {"resolved", "cancelled"}
        ),
    }
