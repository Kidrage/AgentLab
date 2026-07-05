"""Deterministic delivery protocol for longform narrative tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

import yaml


REQUIRED_REVIEW_GATES = [
    "continuity",
    "character_state",
    "timeline",
    "pov",
    "style",
    "scene_goal",
    "chapter_hook",
    "word_count",
]

REQUIRED_DELIVERY_FILES = [
    "chapter_packet.yml",
    "fiction_draft.md",
    "fiction_review.yml",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "artifact_lineage.yml",
]


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or default
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _project_root(root: Path, project: str) -> Path:
    return Path(root) / "projects" / project


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _collect(project_root: Path, patterns: list[str], limit: int = 50) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(project_root.glob(pattern)):
            if len(found) >= limit:
                return found
            if path.is_file():
                found.append(_rel(path, project_root))
    return found


def _chapter_number(path: Path) -> int | None:
    text = path.name
    patterns = [
        r"第\s*0*(\d+)\s*章",
        r"chapter[_\s-]*0*(\d+)",
        r"ch[_\s-]*0*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def _is_fiction_route(route: dict[str, Any]) -> bool:
    route_data = route.get("route") if isinstance(route.get("route"), dict) else route
    if route_data.get("route_key") == "fiction_chapter_pipeline":
        return True
    agents = route_data.get("agents") or []
    return all(agent in agents for agent in ("Writer", "Reviewer", "Scribe"))


def _is_revision_like(text: str) -> bool:
    return bool(re.search(r"(write|chapter|fiction|novel|revise|rewrite|撰写|章节|小说|重写|修改)", text or "", re.I))


def is_narrative_run(run_dir: Path) -> bool:
    workflow = _read_yaml(run_dir / "workflow_plan.yml", {}) or {}
    if isinstance(workflow, dict) and _is_fiction_route(workflow):
        return True
    prompt_path = run_dir / "user_request.md"
    prompt = prompt_path.read_text(encoding="utf-8", errors="replace") if prompt_path.exists() else ""
    return _is_revision_like(prompt)


def build_chapter_packet(root: Path, project: str, task_id: str, chapter: int) -> dict[str, Any]:
    project_root = _project_root(root, project)
    run_rel = f"runs/{task_id}"
    bible_refs = _collect(project_root, ["production/bible/**/*.md"], limit=20)
    outline_refs = _collect(project_root, ["production/outlines/**/*.md"], limit=20)
    manuscript_refs = _collect(project_root, ["production/manuscript/**/*.md"], limit=200)
    previous_chapters = [
        ref
        for ref in manuscript_refs
        if (num := _chapter_number(project_root / ref)) is not None and num < chapter
    ]
    previous_chapters = sorted(previous_chapters, key=lambda ref: _chapter_number(project_root / ref) or 0)
    packet = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "chapter": chapter,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": {
            "fact_snapshot": "project_brain/project_fact_snapshot.yml",
            "artifact_index": "project_artifact_index.yml",
            "production_root": "production/",
        },
        "must_read": [
            "project_brain/project_fact_snapshot.yml",
            "project_artifact_index.yml",
            *bible_refs,
            *outline_refs,
            *previous_chapters[-3:],
        ],
        "story_authority": {
            "bible_refs": bible_refs,
            "outline_refs": outline_refs,
            "previous_chapters": previous_chapters[-3:],
        },
        "previous_chapters": previous_chapters[-3:],
        "required_outputs": list(REQUIRED_DELIVERY_FILES) + [
            "fiction_review.md",
            "narrative_delivery_receipt.yml",
        ],
        "quality_gates": list(REQUIRED_REVIEW_GATES),
        "allowed_output_files": [
            f"{run_rel}/fiction_draft.md",
            f"{run_rel}/fiction_review.yml",
            f"{run_rel}/continuity_ledger.yml",
            f"{run_rel}/state_transition_proposal.yml",
            f"{run_rel}/artifact_lineage.yml",
        ],
    }
    return packet


def write_chapter_packet(root: Path, project: str, task_id: str, chapter: int) -> dict[str, Any]:
    packet = build_chapter_packet(root, project, task_id, chapter)
    path = _project_root(root, project) / "runs" / task_id / "chapter_packet.yml"
    _write_yaml(path, packet)
    return {"status": "written", "path": f"projects/{project}/runs/{task_id}/chapter_packet.yml", "packet": packet}


def validate_narrative_delivery(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if not is_narrative_run(run_dir):
        return {"valid": True, "skipped": True, "reason": "not a narrative run", "issues": []}

    issues: list[dict[str, str]] = []
    for filename in REQUIRED_DELIVERY_FILES:
        if not (run_dir / filename).exists():
            issues.append({"severity": "error", "check": "delivery_file_present", "file": filename, "message": f"missing {filename}"})

    review_path = run_dir / "fiction_review.yml"
    review = _read_yaml(review_path, {}) or {}
    if review_path.exists() and isinstance(review, dict):
        verdict = str(review.get("verdict") or "").lower()
        if bool(review.get("blocking")) or verdict in {"fail", "failed", "rejected", "needs_revision"}:
            issues.append({
                "severity": "error",
                "check": "fiction_review_blocking",
                "file": "fiction_review.yml",
                "message": "fiction review blocks archive/promotion",
            })
        gates = review.get("gates") or {}
        if not isinstance(gates, dict):
            issues.append({"severity": "error", "check": "fiction_review_gates", "file": "fiction_review.yml", "message": "gates must be a mapping"})
        else:
            for gate in REQUIRED_REVIEW_GATES:
                if gate not in gates:
                    issues.append({
                        "severity": "warning",
                        "check": "fiction_review_gate_present",
                        "file": "fiction_review.yml",
                        "message": f"missing review gate: {gate}",
                    })

    return {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "skipped": False,
        "issues": issues,
        "required_files": REQUIRED_DELIVERY_FILES,
    }


def write_narrative_delivery_receipt(run_dir: Path) -> dict[str, Any]:
    result = validate_narrative_delivery(run_dir)
    receipt = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if result.get("valid") else "blocked",
        "delivery_check": result,
    }
    _write_yaml(Path(run_dir) / "narrative_delivery_receipt.yml", receipt)
    return receipt


def run_narrative_doctor(root: Path, project: str) -> dict[str, Any]:
    project_root = _project_root(root, project)
    issues: list[dict[str, str]] = []
    if not project_root.exists():
        return {
            "status": "fail",
            "project": project,
            "issue_count": 1,
            "issues": [{"severity": "error", "check": "project_exists", "message": f"project does not exist: {project}"}],
        }

    for path, check in [
        (project_root / "project_artifact_index.yml", "artifact_index_present"),
        (project_root / "project_brain" / "project_fact_snapshot.yml", "fact_snapshot_present"),
    ]:
        if not path.exists():
            issues.append({"severity": "error", "check": check, "message": f"missing {_rel(path, project_root)}"})

    for pattern, check in [
        ("production/bible/**/*.md", "bible_present"),
        ("production/outlines/**/*.md", "outline_present"),
        ("production/manuscript/**/*.md", "manuscript_present"),
    ]:
        if not _collect(project_root, [pattern], limit=1):
            issues.append({"severity": "error", "check": check, "message": f"missing {pattern}"})

    runs_dir = project_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir())[-30:]:
            if not is_narrative_run(run_dir):
                continue
            if not (run_dir / "chapter_packet.yml").exists():
                issues.append({
                    "severity": "error",
                    "check": "chapter_packet_present",
                    "path": f"projects/{project}/runs/{run_dir.name}",
                    "message": "narrative run is missing chapter_packet.yml",
                })
            if not (run_dir / "narrative_delivery_receipt.yml").exists():
                issues.append({
                    "severity": "error",
                    "check": "narrative_delivery_receipt",
                    "path": f"projects/{project}/runs/{run_dir.name}",
                    "message": "narrative run is missing narrative_delivery_receipt.yml",
                })

    return {
        "status": "fail" if any(issue["severity"] == "error" for issue in issues) else "pass",
        "project": project,
        "issue_count": len(issues),
        "issues": issues,
    }
