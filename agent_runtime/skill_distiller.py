"""Deterministic Project Memory to Skill Draft distillation."""

from __future__ import annotations

# text-integrity: keep this file as real physical lines in Git and GitHub raw.
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import hashlib
import json
import re

import yaml

from atomic_io import atomic_write_yaml, safe_read_yaml
from skill_evolution import build_skill_adoption_request, write_skill_adoption_request
from skill_vault import (
    create_project_run_pointer,
    list_vault_skills,
    move_skill_status,
    register_skill,
    resolve_skill_path,
    update_manifest,
)


REQUIRED_SKILL_HEADINGS = [
    "## When to use",
    "## Inputs and assumptions",
    "## Procedure",
    "## Validation checklist",
    "## Failure recovery",
    "## Anti-patterns",
    "## Evidence summary",
    "## Limits",
]

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,'\"]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9._\-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile("/" + "Users" + r"/[^\s`'\"<>]+"),
    re.compile(r"[A-Za-z]:\\Users\\[^\s`'\"<>]+"),
]

SOURCE_FILES = [
    ("project_memory", "project_memory.md", "project"),
    ("task_events", "task_events.jsonl", "run"),
    ("implementation_report", "06_implementation_report.md", "run"),
    ("validation_report", "07_validation_report.md", "run"),
    ("archive_update", "09_archive_update.md", "run"),
    ("learning_review", "learning_review.yml", "run"),
]

SOURCE_GLOBS = [
    ("implementation_report", "*implementation*report*.md"),
    ("validation_report", "*validation*report*.md"),
    ("archive_update", "*archive*update*.md"),
    ("learning_review", "learning_review*.yml"),
    ("skill_candidate", "skill_candidates/*.yml"),
    ("decision_card", "decision_cards/*.yml"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")[:48] or "item"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def redact_sensitive_text(text: str, *, max_chars: int | None = None) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = re.sub(
        r"(?m)^([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=).+$",
        r"\1[REDACTED]",
        redacted,
    )
    if max_chars is not None and len(redacted) > max_chars:
        redacted = redacted[:max_chars] + "\n[TRUNCATED]"
    return redacted


@dataclass
class EvidenceSource:
    path: Path
    role: str
    exists: bool
    text: str = ""
    sha256: str | None = None
    warning: str | None = None

    def rel(self, root: Path) -> str:
        try:
            return self.path.relative_to(root).as_posix()
        except ValueError:
            return self.path.as_posix()


def load_distillation_config(agentlab_root: Path) -> dict[str, Any]:
    data = safe_read_yaml(agentlab_root / "config" / "skill_distillation.yml", default={}) or {}
    return data if isinstance(data, dict) else {}


def _max_chars(config: dict[str, Any]) -> int:
    return int((config.get("thresholds") or {}).get("max_source_chars_per_file", 12000))


def _read_source(path: Path, role: str, max_chars: int) -> EvidenceSource:
    if not path.exists():
        return EvidenceSource(path=path, role=role, exists=False, warning=f"missing: {path.name}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    return EvidenceSource(
        path=path,
        role=role,
        exists=True,
        text=redact_sensitive_text(raw, max_chars=max_chars),
        sha256=sha256_text(raw),
    )


def collect_evidence(agentlab_root: Path, project: str, task_id: str, config: dict[str, Any] | None = None) -> list[EvidenceSource]:
    cfg = config or load_distillation_config(agentlab_root)
    project_dir = agentlab_root / "projects" / project
    run_dir = project_dir / "runs" / task_id
    max_chars = _max_chars(cfg)
    sources: list[EvidenceSource] = []
    for role, filename, scope in SOURCE_FILES:
        base = project_dir if scope == "project" else run_dir
        sources.append(_read_source(base / filename, role, max_chars))
    seen = {source.path for source in sources}
    for role, pattern in SOURCE_GLOBS:
        for path in sorted(run_dir.glob(pattern)):
            if path not in seen:
                sources.append(_read_source(path, role, max_chars))
                seen.add(path)
    return sources


def _summary(source: EvidenceSource) -> str:
    if not source.exists:
        return source.warning or "missing"
    for line in source.text.splitlines():
        clean = line.strip(" #\t-")
        if 16 <= len(clean) <= 180:
            return clean
    return f"{source.role} evidence present"


def _steps(sources: list[EvidenceSource]) -> list[str]:
    steps: list[str] = []
    for source in sources:
        for line in source.text.splitlines():
            item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            if item != line.strip() and 10 <= len(item) <= 180:
                steps.append(item)
            if len(steps) >= 6:
                return steps
    return [
        "Collect project memory and local task evidence.",
        "Extract reusable procedure, validation, recovery, and anti-patterns.",
        "Redact secrets, local paths, emails, tokens, and private keys.",
        "Create a reviewable draft and require manual approval before staging.",
    ]


def _skill_name(project: str, task_id: str, sources: list[EvidenceSource]) -> str:
    for source in sources:
        if source.exists:
            match = re.search(r"name:\s*['\"]?([^'\"\n]+)", source.text)
            if match:
                return match.group(1).strip()[:80]
    return f"{project} task evidence distillation"


def _reuse_score(sources: list[EvidenceSource]) -> float:
    existing = [s for s in sources if s.exists]
    roles = {s.role for s in existing}
    return round(min(0.25 + len(existing) * 0.06 + len(roles) * 0.04, 0.95), 2)


def _validation_signal(sources: list[EvidenceSource]) -> int:
    text = "\n".join(s.text.lower() for s in sources if s.exists)
    return sum(1 for needle in ["pytest", "validation", "pass", "audit_text_integrity", "bash -n"] if needle in text)


def _draft_id(project: str, task_id: str, sources: list[EvidenceSource]) -> str:
    material = "\n".join([project, task_id] + [s.sha256 or s.warning or "" for s in sources])
    return f"skill_{slug(project)}_{slug(task_id)}_{hashlib.sha256(material.encode()).hexdigest()[:10]}"


def durable_skill_drafts_dir(agentlab_root: Path) -> Path:
    """Return the central Skill Vault drafts directory."""
    return resolve_skill_path(agentlab_root, "__placeholder__", "drafts").parent


def _write_origin_pointer(agentlab_root: Path, draft_dir: Path, project: str, task_id: str, draft_id: str) -> dict[str, Any]:
    origin = {
        "source_project": project,
        "source_task_id": task_id,
        "source_run_path": f"projects/{project}/runs/{task_id}",
        "original_draft_path": f"projects/{project}/runs/{task_id}/skill_drafts/{draft_id}",
        "created_by": "skill_distiller",
        "created_at": utc_now(),
    }
    atomic_write_yaml(draft_dir / "origin_pointer.yml", origin)
    return origin


def _skill_md(name: str, sources: list[EvidenceSource]) -> str:
    lines = [
        f"# {name}",
        "",
        "## When to use",
        "Use when future AgentLab work resembles the local project memory or task evidence summarized here.",
        "",
        "## Inputs and assumptions",
        "- Evidence is local and reviewable.",
        "- Missing files are warnings, not fatal errors.",
        "- No network import or automatic promotion is allowed.",
        "",
        "## Procedure",
    ]
    lines.extend(f"- {step}" for step in _steps(sources))
    lines.extend([
        "",
        "## Validation checklist",
        "- Run `python scripts/audit_text_integrity.py --fail-on-suspicious`.",
        "- Run `pytest`.",
        "- Confirm no secrets, local paths, private keys, tokens, or emails remain.",
        "",
        "## Failure recovery",
        "- Regenerate missing local evidence and rerun distillation.",
        "- Repair failed validation before approving the draft.",
        "",
        "## Anti-patterns",
        "- Do not auto-promote this draft.",
        "- Do not copy secrets, local paths, or private one-off facts.",
        "- Do not use this for external skill discovery.",
        "",
        "## Evidence summary",
    ])
    lines.extend(f"- {_summary(source)}" for source in sources if source.exists)
    if not any(source.exists for source in sources):
        lines.append("- No complete evidence found; manual review required.")
    lines.extend([
        "",
        "## Limits",
        "This draft is deterministic, local-only, and requires manual approval.",
        "",
    ])
    return redact_sensitive_text("\n".join(lines))


def distill_skill_draft(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    config = load_distillation_config(agentlab_root)
    if config.get("enabled", True) is False:
        raise ValueError("Skill distillation is disabled")
    sources = collect_evidence(agentlab_root, project, task_id, config)
    existing = [source for source in sources if source.exists]
    warnings = [source.warning for source in sources if source.warning]
    draft_id = _draft_id(project, task_id, sources)
    name = _skill_name(project, task_id, sources)
    draft_dir = resolve_skill_path(agentlab_root, draft_id, "drafts")
    draft_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": draft_id,
        "name": name,
        "status": "draft",
        "source_type": "project_memory_distillation",
        "project": project,
        "task_ids": [task_id],
        "created_at": utc_now(),
        "reuse_score": _reuse_score(sources),
        "validation_signal": _validation_signal(sources),
        "risk_level": "low",
        "triggers": ["project_memory", "task_evidence", "learning_review"],
        "applies_to": sorted({source.role for source in existing}) or ["project_task_reuse"],
        "manual_approval_required": True,
        "auto_promote": False,
        "warnings": warnings,
        "vault_path": draft_dir.relative_to(agentlab_root).as_posix(),
    }
    source_trace = {
        "source_type": "project_memory_distillation",
        "project": project,
        "task_ids": [task_id],
        "sources": [
            {"path": source.rel(agentlab_root), "exists": source.exists, "sha256": source.sha256, "role": source.role, "summary": _summary(source)}
            for source in sources
        ],
    }
    evidence_map = {
        "evidence": [
            {"claim": _summary(source), "source_path": source.rel(agentlab_root), "signal_type": source.role, "confidence": 0.75}
            for source in existing
        ] or [{"claim": "No complete source evidence was available.", "source_path": "", "signal_type": "warning", "confidence": 0.0}],
    }
    validation_plan = {
        "validation": {
            "required": True,
            "mode": "local_dry_run",
            "commands": ["python scripts/audit_text_integrity.py --fail-on-suspicious", "pytest"],
            "success_criteria": ["text integrity audit passes", "tests pass"],
        }
    }
    (draft_dir / "SKILL.md").write_text(_skill_md(name, sources), encoding="utf-8")
    atomic_write_yaml(draft_dir / "validation_plan.yml", validation_plan)
    atomic_write_yaml(draft_dir / "evidence_map.yml", evidence_map)
    atomic_write_yaml(draft_dir / "source_trace.yml", source_trace)
    _write_origin_pointer(agentlab_root, draft_dir, project, task_id, draft_id)
    register_skill(agentlab_root, draft_id, draft_dir, metadata, status="drafts")
    pointer_path = create_project_run_pointer(agentlab_root, project, task_id, draft_id, draft_dir, status="draft")
    return {
        "draft_id": draft_id,
        "draft_path": str(draft_dir),
        "durable_path": str(draft_dir),
        "vault_path": str(draft_dir),
        "pointer_path": str(pointer_path),
        "metadata": metadata,
        "warnings": warnings,
    }


def list_skill_drafts(agentlab_root: Path, project: str) -> list[dict[str, Any]]:
    """List Skill Vault drafts and reviewed drafts for a project."""
    drafts = list_vault_skills(
        agentlab_root,
        project=project,
        statuses=["draft", "approved", "rejected"],
    )
    seen = {str(d.get("id")) for d in drafts}
    run_root = agentlab_root / "projects" / project / "runs"
    if run_root.exists():
        for path in sorted(run_root.glob("*/skill_drafts/*/metadata.yml")):
            data = safe_read_yaml(path, default={}) or {}
            if not isinstance(data, dict) or str(data.get("id")) in seen:
                continue
            data["path"] = str(path.parent)
            data["durable"] = False
            data["legacy_task_scoped"] = True
            data["migration_hint"] = "Run ./agentlab.sh skill-vault-migrate --project <Project> --dry-run"
            data["task_id"] = path.parents[2].name
            drafts.append(data)
    return drafts


def _find_draft(agentlab_root: Path, project: str, draft_id: str) -> tuple[dict[str, Any], Path]:
    for draft in list_skill_drafts(agentlab_root, project):
        if draft.get("id") == draft_id:
            return draft, Path(draft["path"])
    raise FileNotFoundError(f"Skill draft not found: {draft_id}")


def approve_skill_draft(agentlab_root: Path, project: str, draft_id: str) -> dict[str, Any]:
    draft, draft_dir = _find_draft(agentlab_root, project, draft_id)
    if draft.get("legacy_task_scoped"):
        raise ValueError("Legacy task-scoped draft must be migrated before approval")
    approved_dir = move_skill_status(agentlab_root, draft_id, "drafts", "approved")
    draft = safe_read_yaml(approved_dir / "metadata.yml", default={}) or draft
    draft["status"] = "approved"
    draft["approved_at"] = utc_now()
    request = build_skill_adoption_request(
        agentlab_root,
        project=project,
        skill_name=str(draft.get("name") or draft_id),
        source=f"skill-vault://approved/{draft_id}",
        purpose="Manual approval of Project Memory to Skill Draft. Stage and validate before promotion.",
        source_type="project_memory_distillation",
        risk={"has_scripts": False, "requires_network": False, "modifies_files": False, "permission_level": "low"},
        applies_to=list(draft.get("applies_to") or []),
    )
    request["created_from_skill_draft"] = draft_id
    request["draft_path"] = str(approved_dir)
    request["manual_approval_required"] = True
    request["auto_promote"] = False
    request_path = write_skill_adoption_request(agentlab_root, request)
    draft["skill_request_id"] = request["id"]
    draft["skill_request_path"] = str(request_path)
    atomic_write_yaml(approved_dir / "metadata.yml", draft)
    register_skill(agentlab_root, draft_id, approved_dir, draft, status="approved")
    update_manifest(agentlab_root)
    return {"draft": draft, "draft_path": str(approved_dir), "skill_request_id": request["id"], "skill_request_path": str(request_path)}



def reject_skill_draft(agentlab_root: Path, project: str, draft_id: str, reason: str) -> dict[str, Any]:
    draft, _draft_dir = _find_draft(agentlab_root, project, draft_id)
    if draft.get("legacy_task_scoped"):
        raise ValueError("Legacy task-scoped draft must be migrated before rejection")
    rejected_dir = move_skill_status(agentlab_root, draft_id, "drafts", "rejected")
    draft = safe_read_yaml(rejected_dir / "metadata.yml", default={}) or draft
    draft["status"] = "rejected"
    draft["rejected_at"] = utc_now()
    draft["rejection_reason"] = redact_sensitive_text(reason)
    atomic_write_yaml(rejected_dir / "metadata.yml", draft)
    register_skill(agentlab_root, draft_id, rejected_dir, draft, status="rejected")
    update_manifest(agentlab_root)
    return {"draft": draft, "draft_path": str(rejected_dir)}



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentLab deterministic SkillDistiller")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("distill"); p.add_argument("--project", required=True); p.add_argument("--task-id", required=True)
    p = sub.add_parser("list"); p.add_argument("--project", required=True)
    p = sub.add_parser("approve"); p.add_argument("--project", required=True); p.add_argument("--draft-id", required=True)
    p = sub.add_parser("reject"); p.add_argument("--project", required=True); p.add_argument("--draft-id", required=True); p.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.cmd == "distill":
        result = distill_skill_draft(root, args.project, args.task_id)
    elif args.cmd == "list":
        result = list_skill_drafts(root, args.project)
    elif args.cmd == "approve":
        result = approve_skill_draft(root, args.project, args.draft_id)
    else:
        result = reject_skill_draft(root, args.project, args.draft_id, args.reason)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
