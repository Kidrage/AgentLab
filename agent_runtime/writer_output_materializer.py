"""Materialize Writer candidate edit blocks without touching production paths."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml

try:
    from agent_runtime.narrative_repetition import repetition_evidence
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from narrative_repetition import repetition_evidence


REQUIRED_WRITER_OUTPUTS = (
    "fiction_draft.md",
    "continuity_ledger.yml",
    "state_transition_proposal.yml",
    "narrative_delivery_receipt.yml",
)
REQUIRED_RECEIPT_CHECKS = (
    "chapter_and_title",
    "required_beats",
    "continuity_outputs",
    "production_untouched",
    "deprecated_sources_excluded",
)
REQUIRED_CONTINUITY_LISTS = (
    "plot_state_changes",
    "character_changes",
    "relationship_or_worldline_changes",
    "foreshadowing",
)
DUPLICATE_END_MARKER = re.compile(
    r"<!--\s*END(?:\s+END)+\s+AGENTLAB_EDIT\s*-->",
)
SAFE_CANDIDATE_SCOPE_CATEGORIES = {
    "character_action",
    "character_relationship_progress",
}


def _strip_optional_code_fence(content: str) -> str:
    lines = content.strip().splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("```")
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return content.strip()


def _normalize_writer_edit_markers(content: str) -> tuple[str, list[dict[str, Any]]]:
    normalized, count = DUPLICATE_END_MARKER.subn(
        "<!-- END AGENTLAB_EDIT -->",
        content,
    )
    normalizations = (
        [{"id": "duplicate_end_token", "count": count}]
        if count
        else []
    )
    return normalized, normalizations


def _normalize_candidate_event_scopes(
    materialized: dict[str, str],
) -> list[dict[str, Any]]:
    name = "state_transition_proposal.yml"
    try:
        proposal = yaml.safe_load(materialized[name]) or {}
    except (KeyError, yaml.YAMLError):
        return []
    if (
        not isinstance(proposal, dict)
        or proposal.get("schema_version") != 1
        or proposal.get("status") != "candidate"
        or proposal.get("requires_user_promotion") is not True
        or not isinstance(proposal.get("events"), list)
    ):
        return []

    copied_count = 0
    category_count = 0
    for event in proposal["events"]:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        scope = event.get("scope")
        if (
            isinstance(event_type, str)
            and event_type
            and scope == event_type
            and scope != "candidate_only"
        ):
            event["scope"] = "candidate_only"
            copied_count += 1
        elif scope in SAFE_CANDIDATE_SCOPE_CATEGORIES:
            event["scope"] = "candidate_only"
            category_count += 1
    if not copied_count and not category_count:
        return []

    materialized[name] = yaml.safe_dump(
        proposal,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    normalizations: list[dict[str, Any]] = []
    if copied_count:
        normalizations.append(
            {"id": "event_scope_copied_from_event_type", "count": copied_count}
        )
    if category_count:
        normalizations.append(
            {"id": "event_scope_category_to_candidate_only", "count": category_count}
        )
    return normalizations


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


def _governed_chapter_issues(materialized: dict[str, str], run_dir: Path) -> list[str]:
    packet_path = run_dir / "chapter_packet.yml"
    if not packet_path.is_file():
        return []
    try:
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8")) or {}
        ledger = yaml.safe_load(materialized["continuity_ledger.yml"]) or {}
        proposal = yaml.safe_load(materialized["state_transition_proposal.yml"]) or {}
        receipt = yaml.safe_load(materialized["narrative_delivery_receipt.yml"]) or {}
    except (KeyError, yaml.YAMLError):
        return ["invalid_governed_writer_output"]

    issues: list[str] = []
    chapter = packet.get("chapter")
    expected_baseline = "reset" if packet.get("baseline_mode") == "reset" else "continuation"
    intent = packet.get("chapter_intent") if isinstance(packet.get("chapter_intent"), dict) else {}
    hard_range = intent.get("hard_character_range") or [3000, 8000]
    draft = materialized.get("fiction_draft.md", "")
    if (
        not isinstance(hard_range, list)
        or len(hard_range) != 2
        or not all(isinstance(value, int) for value in hard_range)
        or not hard_range[0] <= len(draft) <= hard_range[1]
    ):
        issues.append("draft_character_count_out_of_range")

    first_heading = next((line.strip() for line in draft.splitlines() if line.strip()), "")
    if not first_heading.startswith("#") or ("章" not in first_heading and "chapter" not in first_heading.lower()):
        issues.append("draft_chapter_heading_missing")
    if ledger.get("chapter") != chapter:
        issues.append("continuity_chapter_mismatch")
    if ledger.get("baseline_mode") != expected_baseline:
        issues.append("continuity_baseline_mode_mismatch")
    for field in REQUIRED_CONTINUITY_LISTS:
        if not isinstance(ledger.get(field), list) or not ledger.get(field):
            issues.append(f"continuity_field_missing:{field}")
    if proposal.get("chapter") != chapter:
        issues.append("state_transition_chapter_mismatch")
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    for check in REQUIRED_RECEIPT_CHECKS:
        if checks.get(check) != "pass":
            issues.append(f"delivery_receipt_check_failed:{check}")

    previous_sources = packet.get("previous_candidate_sources")
    if previous_sources is None:
        previous_sources = packet.get("previous_chapters") or []
    project_root = run_dir.parent.parent.resolve()
    if isinstance(previous_sources, list):
        for source in previous_sources:
            if not isinstance(source, str) or Path(source).name != "fiction_draft.md":
                continue
            previous_path = (project_root / source).resolve()
            try:
                previous_path.relative_to(project_root)
            except ValueError:
                continue
            if not previous_path.is_file():
                continue
            evidence = repetition_evidence(
                draft,
                previous_path.read_text(encoding="utf-8", errors="replace"),
            )
            if evidence["blocking"]:
                issues.append(
                    "draft_repeats_previous_candidate:"
                    f"passages={evidence['passage_count']}:"
                    f"characters={evidence['repeated_characters']}:"
                    f"longest={evidence['longest_passage_characters']}"
                )
            break
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
    normalized_content, normalizations = _normalize_writer_edit_markers(content)
    blocks = parse_edit_blocks(normalized_content)
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
        normalizations.extend(_normalize_candidate_event_scopes(materialized))
        schema_issues = _writer_output_schema_issues(materialized)
        issues.extend(schema_issues)
        if not schema_issues:
            issues.extend(_governed_chapter_issues(materialized, run_dir))
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
            "normalizations": normalizations,
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


# ---------------------------------------------------------------------------
# v2 thin adapter — prose-only Writer path
# ---------------------------------------------------------------------------

WRITER_V2_REQUIRED = ("fiction_draft.md",)


def materialize_writer_v2_content(
    content: str,
    run_dir: Path,
    task_id: str,
    *,
    capture_name: str = "writer_v2_role_session_capture.md",
    provider: str = "",
    model: str = "",
    call_id: str = "",
) -> dict[str, Any]:
    """Thin v2 adapter: materialize prose-only Writer output.

    Validates every parsed edit block against the v2 contract:
    - Rejects non-fiction blocks (arbitrary scorecard/metadata names).
    - Rejects duplicate fiction blocks.
    - Rejects blank content.
    - Rejects absolute paths and traversal (``..``).
    - Rejects cross-run paths (targeting another task_id).

    On **any** issue, no ``fiction_draft.md`` is written to disk.

    Returns a dict with ``status``, ``prose_sha256``, ``issues``,
    ``agentlab_receipt``, and ``materialized_path`` (when successful).
    """
    try:
        from agent_runtime.patch_applicator import parse_edit_blocks
    except ModuleNotFoundError:
        from patch_applicator import parse_edit_blocks  # type: ignore[no-redef]
    try:
        from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
    except ModuleNotFoundError:
        from atomic_io import atomic_write_text, atomic_write_yaml  # type: ignore[no-redef]

    run_dir.mkdir(parents=True, exist_ok=True)
    capture_path = run_dir / capture_name
    out_path = run_dir / "fiction_draft.md"
    receipt_path = run_dir / "writer_execution_receipt.yml"

    def _cleanup_outputs() -> None:
        for output_path in (out_path, receipt_path):
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass

    # A retry starts from a clean materialization pair.  The capture is kept
    # independently as diagnostic lineage.
    _cleanup_outputs()
    try:
        atomic_write_text(capture_path, content, encoding="utf-8")
    except Exception:
        return {
            "schema_version": 2,
            "status": "blocked",
            "issues": ["materialization_capture_write_failed"],
            "prose_sha256": "",
            "canonical_prose": "",
            "agentlab_receipt": None,
        }

    normalized, _ = _normalize_writer_edit_markers(content)
    blocks = parse_edit_blocks(normalized)

    # Delegate block-level validation to production module.
    from agent_runtime.narrative.production.writer_contract import (
        WriterV2Contract,
    )

    validation = WriterV2Contract.validate_edit_blocks(
        blocks,
        task_id=task_id,
        provider=provider,
        model=model,
        call_id=call_id,
    )

    if validation["status"] == "pass" and validation["prose_sha256"]:
        # Use the one canonical prose string from validation — do NOT
        # re-extract a second representation from parsed blocks.  The
        # canonical prose already has exactly one trailing newline and
        # its hash equals the receipt hash.
        canonical_prose = validation.get("canonical_prose", "")
        if not canonical_prose:
            # Defensive: if canonical_prose is somehow absent, compute it.
            canonical_prose = ""  # fall through to blocked below

        try:
            # ---- Write prose -------------------------------------------------
            atomic_write_text(out_path, canonical_prose, encoding="utf-8")
            validation["materialized_path"] = str(out_path)

            # ---- Post-write hash binding -------------------------------------
            # Compute the prose SHA256 from the actual written file bytes so
            # the receipt hash always equals the persisted prose.
            import hashlib
            file_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
            validation["prose_sha256"] = file_hash
            receipt = validation.get("agentlab_receipt")
            if isinstance(receipt, dict):
                receipt["prose_sha256"] = file_hash

            # ---- Persist receipt to disk -------------------------------------
            receipt_data = validation.get("agentlab_receipt")
            if receipt_data is not None:
                atomic_write_yaml(
                    receipt_path,
                    receipt_data,
                    sort_keys=False,
                    allow_unicode=True,
                )
                validation["receipt_path"] = str(receipt_path)

        except Exception:
            # ---- Atomic cleanup ----------------------------------------------
            # Any exception during prose write, hash, receipt construction,
            # or receipt write removes BOTH fiction_draft.md and
            # writer_execution_receipt.yml.  The capture file remains as
            # diagnostic lineage.
            _cleanup_outputs()
            validation["status"] = "blocked"
            validation["agentlab_receipt"] = None
            validation.pop("receipt_path", None)
            validation.pop("materialized_path", None)
            issues = list(validation.get("issues", []))
            issues.append("materialization_write_failed")
            validation["issues"] = issues

    return validation
