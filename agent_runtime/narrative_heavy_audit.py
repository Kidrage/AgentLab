"""Materialize candidate-only outputs for narrative heavy-audit role sessions."""

from __future__ import annotations

from pathlib import Path
import hashlib
import re
from typing import Any

import yaml

try:
    from agent_runtime.narrative_delivery import validate_narrative_delivery
    from agent_runtime.policies import ensure_safe_task_id
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from narrative_delivery import validate_narrative_delivery
    from policies import ensure_safe_task_id


HEAVY_AUDIT_OUTPUTS_BY_AGENT: dict[str, tuple[str, ...]] = {
    "Reviewer": ("fiction_review.yml", "continuity_failure_report.yml"),
    "Scribe": ("state_transition_proposal.yml",),
    "Verifier": ("revision_or_rewrite_proposal.yml",),
}
MAX_AUDIT_BUNDLE_CHAPTERS = 20


def heavy_audit_primary_output(agent_name: str) -> str | None:
    outputs = HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name, ())
    return outputs[0] if outputs else None


def _strip_optional_code_fence(content: str) -> str:
    lines = content.strip().splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return content.strip()


def _schema_issues(name: str, value: str) -> list[str]:
    try:
        data = yaml.safe_load(value) or {}
    except yaml.YAMLError:
        return [f"invalid_heavy_audit_yaml:{name}"]
    if not isinstance(data, dict):
        return [f"invalid_heavy_audit_schema:{name}:mapping_required"]

    issues: list[str] = []
    if data.get("schema_version") != 1:
        issues.append(f"invalid_heavy_audit_schema:{name}:schema_version")
    if data.get("candidate_only") is not True:
        issues.append(f"invalid_heavy_audit_boundary:{name}:candidate_only")
    if data.get("production_modified") is not False:
        issues.append(f"invalid_heavy_audit_boundary:{name}:production_modified")

    if name == "fiction_review.yml":
        if data.get("status") not in {"pass", "warn", "blocked"}:
            issues.append(f"invalid_heavy_audit_schema:{name}:status")
        if not isinstance(data.get("findings"), list):
            issues.append(f"invalid_heavy_audit_schema:{name}:findings")
    elif name == "continuity_failure_report.yml":
        if data.get("status") not in {"pass", "warn", "blocked"}:
            issues.append(f"invalid_heavy_audit_schema:{name}:status")
        if not isinstance(data.get("blocking_issue_count"), int):
            issues.append(f"invalid_heavy_audit_schema:{name}:blocking_issue_count")
        if not isinstance(data.get("failures"), list):
            issues.append(f"invalid_heavy_audit_schema:{name}:failures")
    elif name == "state_transition_proposal.yml":
        events = data.get("events")
        if data.get("status") != "candidate":
            issues.append(f"invalid_heavy_audit_schema:{name}:status")
        if data.get("requires_user_promotion") is not True:
            issues.append(f"invalid_heavy_audit_boundary:{name}:requires_user_promotion")
        if not isinstance(events, list):
            issues.append(f"invalid_heavy_audit_schema:{name}:events")
        elif any(
            not isinstance(event, dict) or event.get("scope") != "candidate_only"
            for event in events
        ):
            issues.append(f"invalid_heavy_audit_boundary:{name}:event_scope")
    elif name == "revision_or_rewrite_proposal.yml":
        if data.get("status") not in {"not_required", "proposed", "blocked"}:
            issues.append(f"invalid_heavy_audit_schema:{name}:status")
        if not isinstance(data.get("rewrite_required"), bool):
            issues.append(f"invalid_heavy_audit_schema:{name}:rewrite_required")
        if data.get("direct_draft_edits") is not False:
            issues.append(f"invalid_heavy_audit_boundary:{name}:direct_draft_edits")
        if not isinstance(data.get("proposals"), list):
            issues.append(f"invalid_heavy_audit_schema:{name}:proposals")
    return issues


def _clear_role_outputs(run_dir: Path, required: tuple[str, ...]) -> None:
    for name in required:
        (run_dir / name).unlink(missing_ok=True)


def _blocking_rewrite_consistency_issues(
    run_dir: Path,
    materialized: dict[str, str],
) -> list[str]:
    proposal_value = materialized.get("revision_or_rewrite_proposal.yml")
    if proposal_value is None:
        return []
    continuity_path = run_dir / "continuity_failure_report.yml"
    if not continuity_path.is_file():
        return (
            ["missing_upstream_heavy_audit_output:continuity_failure_report.yml"]
            if (run_dir / "narrative_audit_manifest.yml").exists()
            else []
        )
    try:
        continuity = yaml.safe_load(continuity_path.read_text(encoding="utf-8")) or {}
        proposal = yaml.safe_load(proposal_value) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(continuity, dict) or not isinstance(proposal, dict):
        return []
    blocking_issue_count = continuity.get("blocking_issue_count")
    blocking = continuity.get("status") == "blocked" or (
        isinstance(blocking_issue_count, int) and blocking_issue_count > 0
    )
    if not blocking:
        return []
    if (
        proposal.get("status") not in {"proposed", "blocked"}
        or proposal.get("rewrite_required") is not True
        or not proposal.get("proposals")
    ):
        return ["blocking_continuity_requires_rewrite_proposal"]
    return []


def materialize_narrative_heavy_audit_content(
    content: str,
    run_dir: Path,
    task_id: str,
    agent_name: str,
) -> bool:
    try:
        from agent_runtime.patch_applicator import parse_edit_blocks
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from patch_applicator import parse_edit_blocks

    required = HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name)
    if not required:
        return False
    run_dir.mkdir(parents=True, exist_ok=True)
    _clear_role_outputs(run_dir, required)
    capture_name = f"{agent_name.lower()}_role_session_capture.md"
    (run_dir / capture_name).write_text(content, encoding="utf-8")

    materialized: dict[str, str] = {}
    issues: list[str] = []
    for block in parse_edit_blocks(content):
        raw_path = str(block.get("path") or "").strip().replace("\\", "/")
        path = Path(raw_path)
        name = path.name
        if name not in required:
            issues.append(f"unexpected_heavy_audit_output:{raw_path or '<blank>'}")
            continue
        if ".." in path.parts or raw_path.startswith("/"):
            issues.append(f"unsafe_heavy_audit_output_path:{raw_path}")
            continue
        if len(path.parts) > 1 and path.parts[-2] != task_id:
            issues.append(f"heavy_audit_output_wrong_run:{raw_path}")
            continue
        if name in materialized:
            issues.append(f"duplicate_heavy_audit_output:{name}")
            continue
        value = _strip_optional_code_fence(str(block.get("html_block_content") or ""))
        if not value:
            issues.append(f"empty_heavy_audit_output:{name}")
            continue
        materialized[name] = value

    issues.extend(
        f"missing_heavy_audit_output:{name}"
        for name in required
        if name not in materialized
    )
    if not issues:
        for name in required:
            issues.extend(_schema_issues(name, materialized[name]))
    if not issues:
        issues.extend(_blocking_rewrite_consistency_issues(run_dir, materialized))

    contract_name = f"narrative_heavy_audit_{agent_name.lower()}_output_contract.yml"
    (run_dir / contract_name).write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass" if not issues else "blocked",
                "task_id": task_id,
                "agent": agent_name,
                "capture_path": capture_name,
                "required_outputs": list(required),
                "materialized_outputs": sorted(materialized) if not issues else [],
                "candidate_only": True,
                "production_modified": False,
                "issues": issues,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    if issues:
        return False
    for name, value in materialized.items():
        (run_dir / name).write_text(value.rstrip() + "\n", encoding="utf-8")
    return True


def materialize_narrative_heavy_audit_result(
    result: Any,
    run_dir: Path,
    task_id: str,
    agent_name: str,
) -> bool:
    required = HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name)
    if not required:
        return False
    if getattr(result, "status", None) != "completed":
        _clear_role_outputs(run_dir, required)
        return False
    content = str(getattr(result, "content", "") or "")
    return materialize_narrative_heavy_audit_content(
        content,
        run_dir,
        task_id,
        agent_name,
    )


def fake_narrative_heavy_audit_content(agent_name: str) -> str:
    payloads: dict[str, dict[str, Any]] = {
        "fiction_review.yml": {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [1, 1],
            "findings": [],
        },
        "continuity_failure_report.yml": {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [1, 1],
            "blocking_issue_count": 0,
            "failures": [],
        },
        "state_transition_proposal.yml": {
            "schema_version": 1,
            "status": "candidate",
            "candidate_only": True,
            "production_modified": False,
            "requires_user_promotion": True,
            "events": [],
        },
        "revision_or_rewrite_proposal.yml": {
            "schema_version": 1,
            "status": "not_required",
            "candidate_only": True,
            "production_modified": False,
            "rewrite_required": False,
            "direct_draft_edits": False,
            "proposals": [],
        },
    }
    blocks = []
    for name in HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name, ()):
        value = yaml.safe_dump(payloads[name], sort_keys=False, allow_unicode=True)
        blocks.append(
            f"<!-- AGENTLAB_EDIT: {name} -->\n"
            f"{value}"
            "<!-- END AGENTLAB_EDIT -->"
        )
    return "\n\n".join(blocks)


def _audit_source_task_id(chapter: int, eval_id: str) -> str:
    return f"task_narrative_eval_ch{chapter:02d}_{eval_id}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _production_manuscript_files(project_root: Path) -> list[str]:
    manuscript_root = project_root / "production" / "manuscript"
    if not manuscript_root.exists():
        return []
    return [
        str(path.relative_to(project_root))
        for path in sorted(manuscript_root.rglob("*"))
        if path.is_file() and path.name != ".gitkeep"
    ]


def prepare_crown_narrative_heavy_audit(
    root: Path,
    *,
    eval_id: str,
    start_chapter: int,
    end_chapter: int,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Create a fresh, provider-free audit bundle from valid candidate chapters."""
    root = Path(root).resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    chapter_count = end_chapter - start_chapter + 1
    issues: list[str] = []
    if start_chapter < 1 or end_chapter < start_chapter:
        issues.append("invalid_chapter_range")
    if chapter_count > MAX_AUDIT_BUNDLE_CHAPTERS:
        issues.append(f"chapter_range_exceeds_limit:{MAX_AUDIT_BUNDLE_CHAPTERS}")

    clean_eval_id = re.sub(r"[^A-Za-z0-9_-]+", "_", eval_id).strip("_-") or "eval"
    target_task_id = task_id or (
        f"task_narrative_heavy_audit_ch{start_chapter:03d}_ch{end_chapter:03d}_{clean_eval_id}"
    )
    try:
        target_task_id = ensure_safe_task_id(target_task_id)
    except Exception as exc:
        issues.append(f"invalid_task_id:{type(exc).__name__}")
    target_run = project_root / "runs" / target_task_id
    if target_run.exists():
        issues.append("target_run_already_exists")

    source_records: list[dict[str, Any]] = []
    context_sections: list[str] = []
    if not issues:
        for chapter in range(start_chapter, end_chapter + 1):
            source_task_id = _audit_source_task_id(chapter, clean_eval_id)
            source_run = project_root / "runs" / source_task_id
            delivery = validate_narrative_delivery(source_run)
            if delivery.get("valid") is not True or delivery.get("skipped") is True:
                issues.append(f"invalid_candidate_chapter:{chapter}")
                continue
            files: dict[str, dict[str, Any]] = {}
            chapter_values: dict[str, str] = {}
            for name in (
                "fiction_draft.md",
                "continuity_ledger.yml",
                "state_transition_proposal.yml",
            ):
                path = source_run / name
                if not path.is_file():
                    issues.append(f"missing_candidate_input:{chapter}:{name}")
                    continue
                value = path.read_text(encoding="utf-8", errors="replace")
                chapter_values[name] = value
                files[name] = {
                    "path": str(path.relative_to(project_root)),
                    "sha256": _sha256(path),
                    "characters": len(value),
                }
            if len(chapter_values) != 3:
                continue
            source_records.append(
                {
                    "chapter": chapter,
                    "task_id": source_task_id,
                    "files": files,
                }
            )
            context_sections.extend(
                [
                    f"## Chapter {chapter} draft\n\n{chapter_values['fiction_draft.md'].rstrip()}",
                    f"## Chapter {chapter} continuity ledger\n\n```yaml\n{chapter_values['continuity_ledger.yml'].rstrip()}\n```",
                    f"## Chapter {chapter} state transition proposal\n\n```yaml\n{chapter_values['state_transition_proposal.yml'].rstrip()}\n```",
                ]
            )

    production_files = _production_manuscript_files(project_root)
    if production_files:
        issues.append("production_manuscript_not_empty")
    status = "ready" if not issues else "blocked"
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "agentlab_narrative_heavy_audit_bundle",
        "status": status,
        "project": "Crown_of_Ash",
        "eval_id": clean_eval_id,
        "task_id": target_task_id,
        "chapter_range": [start_chapter, end_chapter],
        "chapter_count": chapter_count,
        "candidate_only": True,
        "production_modified": False,
        "production_manuscript_files": production_files,
        "sources": source_records,
        "issues": issues,
    }
    if issues:
        return report

    target_run.mkdir(parents=True, exist_ok=False)
    request = (
        f"审计 Crown_of_Ash 第 {start_chapter}-{end_chapter} 章候选稿。"
        "全面检查连续性、人物状态、关系与势力变化、伏笔、时间线、POV 和风格漂移。"
        "只审查已有正文；不得重写正文、写 production 或自动 promotion。"
        "发现 blocking issue 时只生成 revision_or_rewrite_proposal.yml。\n"
    )
    (target_run / "user_request.md").write_text(request, encoding="utf-8")
    (target_run / "brain_decisions.yml").write_text("decisions: []\n", encoding="utf-8")
    (target_run / "cost_ledger.yml").write_text("entries: []\n", encoding="utf-8")
    (target_run / "narrative_audit_manifest.yml").write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    context_header = (
        "# Narrative Heavy Audit Context\n\n"
        f"- Project: Crown_of_Ash\n"
        f"- Candidate chapters: {start_chapter}-{end_chapter}\n"
        "- Boundary: candidate-only; production untouched; no direct prose rewrites\n\n"
    )
    (target_run / "narrative_audit_context.md").write_text(
        context_header + "\n\n".join(context_sections).rstrip() + "\n",
        encoding="utf-8",
    )
    report["run_dir"] = str(target_run)
    report["manifest_path"] = str(target_run / "narrative_audit_manifest.yml")
    report["context_path"] = str(target_run / "narrative_audit_context.md")
    return report
