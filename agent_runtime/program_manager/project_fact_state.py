from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


EVENTS_FILE = "project_fact_events.jsonl"
SNAPSHOT_FILE = "project_fact_snapshot.yml"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_project_fact_snapshot(project: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": project,
        "generated_at": utc_now(),
        "event_count": 0,
        "entities": {},
        "artifacts": {},
        "relationships": [],
        "open_threads": {},
    }


def initialize_project_fact_state(project_brain_dir: Path, project: str | None = None) -> dict[str, Any]:
    project_brain_dir.mkdir(parents=True, exist_ok=True)
    events_path = project_brain_dir / EVENTS_FILE
    if not events_path.exists():
        atomic_write_text(events_path, "")
    snapshot = rebuild_project_fact_snapshot(project_brain_dir, project=project)
    return snapshot


def load_project_fact_snapshot(project_brain_dir: Path) -> dict[str, Any]:
    snapshot_path = project_brain_dir / SNAPSHOT_FILE
    if not snapshot_path.exists():
        return empty_project_fact_snapshot()
    import yaml

    data = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else empty_project_fact_snapshot()


def append_project_fact_events(project_brain_dir: Path, events: list[dict[str, Any]]) -> list[str]:
    project_brain_dir.mkdir(parents=True, exist_ok=True)
    path = project_brain_dir / EVENTS_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    event_ids: list[str] = []
    lines = []
    for event in events:
        entry = dict(event)
        entry.setdefault("created_at", utc_now())
        entry.setdefault("event_id", f"event_{len(existing.splitlines()) + len(lines) + 1:06d}")
        event_ids.append(str(entry["event_id"]))
        lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    content = existing
    if content and not content.endswith("\n"):
        content += "\n"
    content += "\n".join(lines)
    if lines:
        content += "\n"
    atomic_write_text(path, content)
    return event_ids


def rebuild_project_fact_snapshot(project_brain_dir: Path, project: str | None = None) -> dict[str, Any]:
    snapshot = empty_project_fact_snapshot(project)
    for event in read_project_fact_events(project_brain_dir):
        _apply_event(snapshot, event)
    snapshot["generated_at"] = utc_now()
    snapshot["event_count"] = len(read_project_fact_events(project_brain_dir))
    atomic_write_yaml(project_brain_dir / SNAPSHOT_FILE, snapshot)
    return snapshot


def read_project_fact_events(project_brain_dir: Path) -> list[dict[str, Any]]:
    path = project_brain_dir / EVENTS_FILE
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except json.JSONDecodeError:
            continue
    return events


def apply_state_transition_proposal(
    project_brain_dir: Path,
    proposal: dict[str, Any],
    acceptance_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = proposal.get("state_transition_proposal") or proposal
    existing_project = load_project_fact_snapshot(project_brain_dir).get("project")
    raw_events = body.get("events") or []
    events = []
    for raw in raw_events:
        event = dict(raw)
        event.setdefault("phase_id", body.get("phase_id") or (acceptance_result or {}).get("phase_id"))
        event.setdefault("source", "state_transition_proposal")
        events.append(event)
    event_ids = append_project_fact_events(project_brain_dir, events)
    snapshot = rebuild_project_fact_snapshot(project_brain_dir, project=body.get("project") or existing_project)
    return {"applied": True, "event_ids": event_ids, "snapshot": snapshot}


def _apply_event(snapshot: dict[str, Any], event: dict[str, Any]) -> None:
    kind = str(event.get("target_kind") or event.get("kind") or "entity")
    if kind not in {"entity", "artifact"}:
        return
    collection_key = "entities" if kind == "entity" else "artifacts"
    type_key = "entity_type" if kind == "entity" else "artifact_type"
    id_key = "entity_id" if kind == "entity" else "artifact_id"
    target_type = str(event.get("target_type") or event.get(type_key) or "generic")
    target_id = str(event.get("target_id") or event.get(id_key) or "")
    if not target_id:
        return
    collection = snapshot.setdefault(collection_key, {}).setdefault(target_type, {})
    current = collection.setdefault(
        target_id,
        {
            "status": "planned",
            "facts": {},
            "evidence_refs": [],
            "last_event_id": None,
        },
    )
    if event.get("to_status"):
        current["status"] = str(event["to_status"])
    facts = event.get("facts") or {}
    if isinstance(facts, dict):
        current.setdefault("facts", {}).update(facts)
    refs = [str(item) for item in event.get("evidence_refs") or []]
    current["evidence_refs"] = sorted(set([*current.get("evidence_refs", []), *refs]))
    current["last_event_id"] = event.get("event_id")
