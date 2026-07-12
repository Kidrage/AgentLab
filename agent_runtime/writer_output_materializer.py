"""Materialize Writer candidate edit blocks without touching production paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_WRITER_OUTPUTS = (
    "fiction_draft.md",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "narrative_delivery_receipt.yml",
)


def _strip_optional_code_fence(content: str) -> str:
    lines = content.strip().splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return content.strip()


def _write_contract(run_dir: Path, data: dict[str, Any]) -> None:
    path = run_dir / "writer_output_contract.yml"
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _writer_output_schema_issues(materialized: dict[str, str]) -> list[str]:
    parsed: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for name in REQUIRED_WRITER_OUTPUTS:
        if not name.endswith(".yml") or name not in materialized:
            continue
        try:
            data = yaml.safe_load(materialized[name]) or {}
        except yaml.YAMLError:
            issues.append(f"invalid_writer_output_yaml:{name}")
            continue
        if not isinstance(data, dict):
            issues.append(f"invalid_writer_output_schema:{name}:mapping_required")
            continue
        parsed[name] = data

    ledger = parsed.get("continuity_ledger.yml", {})
    timeline = ledger.get("timeline") if isinstance(ledger.get("timeline"), dict) else {}
    if ledger and (
        ledger.get("schema_version") != 1
        or not isinstance(ledger.get("chapter"), int)
        or ledger.get("baseline_mode") not in {"reset", "continuation"}
        or timeline.get("monotonic") is not True
    ):
        issues.append("invalid_writer_output_schema:continuity_ledger.yml")

    proposal = parsed.get("state_transition_proposal.yml", {})
    events = proposal.get("events") if isinstance(proposal.get("events"), list) else []
    if proposal and (
        proposal.get("schema_version") != 1
        or proposal.get("status") != "candidate"
        or proposal.get("requires_user_promotion") is not True
        or not events
        or any(
            not isinstance(event, dict) or event.get("scope") != "candidate_only"
            for event in events
        )
    ):
        issues.append("invalid_writer_output_schema:state_transition_proposal.yml")

    receipt = parsed.get("narrative_delivery_receipt.yml", {})
    if receipt and (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "pass"
        or receipt.get("candidate_only") is not True
    ):
        issues.append("invalid_writer_output_schema:narrative_delivery_receipt.yml")
    return issues


def materialize_writer_candidate_content(
    content: str,
    run_dir: Path,
    task_id: str,
    *,
    capture_name: str = "writer_role_session_capture.md",
) -> bool:
    try:
        from agent_runtime.patch_applicator import parse_edit_blocks
    except ModuleNotFoundError:  # pragma: no cover - direct script path
        from patch_applicator import parse_edit_blocks

    run_dir.mkdir(parents=True, exist_ok=True)
    capture_path = run_dir / capture_name
    capture_path.write_text(content, encoding="utf-8")
    blocks = parse_edit_blocks(content)
    materialized: dict[str, str] = {}
    issues: list[str] = []
    for block in blocks:
        raw_path = str(block.get("path") or "").strip().replace("\\", "/")
        path = Path(raw_path)
        name = path.name
        if name not in REQUIRED_WRITER_OUTPUTS:
            issues.append(f"unexpected_writer_output:{raw_path or '<blank>'}")
            continue
        if ".." in path.parts or raw_path.startswith("/"):
            issues.append(f"unsafe_writer_output_path:{raw_path}")
            continue
        if len(path.parts) > 1 and path.parts[-2] != task_id:
            issues.append(f"writer_output_wrong_run:{raw_path}")
            continue
        if name in materialized:
            issues.append(f"duplicate_writer_output:{name}")
            continue
        value = _strip_optional_code_fence(str(block.get("html_block_content") or ""))
        if not value:
            issues.append(f"empty_writer_output:{name}")
            continue
        materialized[name] = value

    missing = [name for name in REQUIRED_WRITER_OUTPUTS if name not in materialized]
    issues.extend(f"missing_writer_output:{name}" for name in missing)
    if not missing:
        issues.extend(_writer_output_schema_issues(materialized))
    status = "pass" if not issues else "blocked"
    _write_contract(
        run_dir,
        {
            "schema_version": 1,
            "status": status,
            "task_id": task_id,
            "capture_path": capture_name,
            "required_outputs": list(REQUIRED_WRITER_OUTPUTS),
            "materialized_outputs": sorted(materialized) if not issues else [],
            "candidate_only": True,
            "harness_generated_story_state": False,
            "issues": issues,
        },
    )
    if issues:
        return False
    for name, value in materialized.items():
        (run_dir / name).write_text(value.rstrip() + "\n", encoding="utf-8")
    return True


def materialize_writer_candidate_result(
    result: Any,
    run_dir: Path,
    task_id: str,
    *,
    capture_name: str = "writer_role_session_capture.md",
) -> bool:
    if getattr(result, "status", None) != "completed":
        return False
    content = str(getattr(result, "content", "") or "")
    if not content.strip():
        return False
    return materialize_writer_candidate_content(
        content,
        run_dir,
        task_id,
        capture_name=capture_name,
    )
