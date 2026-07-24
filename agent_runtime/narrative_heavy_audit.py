"""Materialize candidate-only outputs for narrative heavy-audit role sessions."""

from __future__ import annotations

from pathlib import Path
import hashlib
import re
from typing import Any, Mapping

import yaml

try:
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.narrative_delivery import validate_narrative_delivery
    from agent_runtime.narrative.efficiency.context_bundle import build_context_bundle
    from agent_runtime.policies import ensure_safe_task_id
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from atomic_io import atomic_write_yaml
    from narrative_delivery import validate_narrative_delivery
    from narrative.efficiency.context_bundle import build_context_bundle
    from policies import ensure_safe_task_id


HEAVY_AUDIT_OUTPUTS_BY_AGENT: dict[str, tuple[str, ...]] = {
    "Reviewer": (
        "fiction_review.yml",
        "continuity_failure_report.yml",
        "narrative_quality_scorecard.yml",
    ),
    "Scribe": ("state_transition_proposal.yml",),
    "Verifier": ("revision_or_rewrite_proposal.yml",),
}
MAX_AUDIT_BUNDLE_CHAPTERS = 20
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = int(getattr(mark, "line", -1)) + 1
        problem = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(getattr(exc, "problem", "parse_error") or "parse_error").lower(),
        ).strip("_")
        return [
            f"invalid_heavy_audit_yaml:{name}:line_{max(line, 1)}:{problem}"
        ]
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
    elif name == "narrative_quality_scorecard.yml":
        from agent_runtime.narrative.quality.scorecard import validate_quality_scorecard

        validation = validate_quality_scorecard(
            data,
            candidate_sha256=str(data.get("candidate_sha256") or ""),
        )
        if validation["valid"] is not True:
            issues.extend(
                f"invalid_heavy_audit_schema:{name}:{issue}"
                for issue in validation["issues"]
            )
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
        elif data.get("rewrite_required") is True:
            required_contract_fields = {
                "chapter_id",
                "target_scene",
                "problem_type",
                "evidence",
                "must_preserve",
                "must_change",
                "allowed_freedom",
                "causal_requirements",
                "character_knowledge_before",
                "character_knowledge_after",
                "decision_cost",
                "new_information",
                "forbidden_regressions",
            }
            for index, proposal in enumerate(data["proposals"]):
                if not isinstance(proposal, dict) or not required_contract_fields <= set(proposal):
                    issues.append(
                        f"invalid_heavy_audit_schema:{name}:scene_contract:{index}"
                    )
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
        "narrative_quality_scorecard.yml": {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "production_modified": False,
            "candidate_sha256": "dry-run-candidate",
            "chapters": [
                {
                    "chapter_id": 1,
                    "status": "pass",
                    "dimensions": {
                        name: {
                            "score": 5,
                            "severity": "pass",
                            "evidence": {
                                "chapter": 1,
                                "scene": "opening",
                                "excerpt_or_locator": "paragraph 1",
                            },
                            "reason": "dry-run fixture evidence",
                            "revision_target": "none",
                        }
                        for name in (
                            "causal_reasoning",
                            "strategic_competence",
                            "character_agency",
                            "dramatic_tension",
                            "reader_curiosity",
                            "non_formulaic_progression",
                        )
                    },
                }
            ],
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


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_revision_draft_binding(
    project_root: Path,
    *,
    chapter: int,
    source_task_id: str,
    revision_task_id: str,
    expected_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate one materialized revision without mutating its source run."""
    if not _SAFE_TASK_ID_RE.fullmatch(source_task_id) or not _SAFE_TASK_ID_RE.fullmatch(
        revision_task_id
    ):
        return {
            "status": "blocked",
            "issues": ["revision_task_id_invalid"],
            "draft_path": "",
        }
    project_root = Path(project_root).resolve()
    root = project_root.parent.parent
    source_run = project_root / "runs" / source_task_id
    revision_run = project_root / "runs" / revision_task_id
    legacy_request_path = revision_run / "narrative_v2_writer_request.yml"
    generic_revision = not legacy_request_path.is_file()
    request_path = (
        revision_run / "revision_request.yml"
        if generic_revision
        else legacy_request_path
    )
    draft = revision_run / "fiction_draft.md"
    output_contract_path = revision_run / (
        "writer_output_contract.yml"
        if generic_revision
        else "writer_v2_output_contract.yml"
    )
    session_receipt_path = revision_run / (
        "writer_session_receipt.yml"
        if generic_revision
        else "narrative_v2_writer_session_receipt.yml"
    )
    issues: list[str] = []
    for path, label in (
        (request_path, "request"),
        (draft, "draft"),
        (output_contract_path, "output_contract"),
        (session_receipt_path, "session_receipt"),
    ):
        if _has_symlink_component(root, path) or not path.is_file():
            issues.append(f"revision_{label}_missing_or_unsafe")
    if issues:
        return {"status": "blocked", "issues": issues, "draft_path": str(draft)}
    try:
        request = yaml.safe_load(request_path.read_text(encoding="utf-8")) or {}
        output_contract = yaml.safe_load(
            output_contract_path.read_text(encoding="utf-8")
        ) or {}
        session_receipt = yaml.safe_load(
            session_receipt_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {
            "status": "blocked",
            "issues": ["revision_binding_yaml_invalid"],
            "draft_path": str(draft),
        }
    if not isinstance(request, dict):
        request = {}
    if not isinstance(output_contract, dict):
        output_contract = {}
    if not isinstance(session_receipt, dict):
        session_receipt = {}
    expected_request = {
        "schema_version": 1,
        "job_kind": "narrative_revision",
        "run_mode": "targeted_rewrite",
        "project": project_root.name,
        "task_id": revision_task_id,
        "chapter_id": chapter,
        "source_run_id": source_task_id,
        "candidate_only": True,
        "production_modified": False,
    }
    if any(request.get(key) != value for key, value in expected_request.items()):
        issues.append("revision_request_identity_mismatch")
    if generic_revision:
        try:
            plan_path = revision_run / "workflow_plan.yml"
            plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            if (
                not isinstance(plan, dict)
                or plan.get("project") != project_root.name
                or plan.get("task_id") != revision_task_id
                or Path(str(plan.get("run_dir") or "")).resolve() != revision_run
                or Path(str(plan.get("user_request_path") or "")).resolve()
                != request_path
                or request.get("workflow_plan_sha256") != _sha256(plan_path)
                or session_receipt.get("workflow_plan_sha256")
                != _sha256(plan_path)
                or session_receipt.get("request_sha256") != _sha256(request_path)
            ):
                issues.append("revision_plan_activation_invalid")
        except (OSError, RuntimeError, TypeError, ValueError, yaml.YAMLError):
            issues.append("revision_plan_activation_invalid")
    else:
        try:
            from agent_runtime.narrative.production.live_writer_preflight import (
                load_validated_workflow_plan_data,
            )

            plan = load_validated_workflow_plan_data(
                agentlab_root=root,
                project=project_root.name,
                task_id=revision_task_id,
                plan_path=revision_run / "workflow_plan.yml",
            )
            if str(plan.get("sealed_user_request_content") or "").encode(
                "utf-8"
            ) != request_path.read_bytes():
                issues.append("revision_request_not_activated")
        except (OSError, RuntimeError, TypeError, ValueError):
            issues.append("revision_plan_activation_invalid")

    draft_hash = _sha256(draft)
    if (
        output_contract.get("status") != "pass"
        or output_contract.get("task_id") != revision_task_id
        or output_contract.get("candidate_only") is not True
        or output_contract.get("production_modified") is not False
        or output_contract.get("prose_sha256") != draft_hash
    ):
        issues.append("revision_output_contract_mismatch")
    if generic_revision and (
        session_receipt.get("status") != "pass"
        or session_receipt.get("task_id") != revision_task_id
        or session_receipt.get("candidate_only") is not True
        or session_receipt.get("production_modified") is not False
        or session_receipt.get("source_candidate_sha256")
        != _sha256(source_run / "fiction_draft.md")
        or session_receipt.get("prose_sha256") != draft_hash
    ):
        issues.append("revision_session_receipt_mismatch")

    def verify_ref(field: str, *, expected: Path | None = None) -> Path | None:
        value = request.get(field)
        if not isinstance(value, Mapping):
            issues.append(f"revision_reference_invalid:{field}")
            return None
        relative = str(value.get("path") or "")
        try:
            candidate = root / relative
            if _has_symlink_component(root, candidate):
                raise ValueError("symlink")
            path = candidate.resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError):
            issues.append(f"revision_reference_invalid:{field}")
            return None
        if path.is_symlink() or not path.is_file() or value.get("sha256") != _sha256(path):
            issues.append(f"revision_reference_hash_mismatch:{field}")
        if expected is not None and path != expected.resolve():
            issues.append(f"revision_reference_path_mismatch:{field}")
        return path

    verify_ref(
        "source_candidate",
        expected=source_run / "fiction_draft.md",
    )
    contract_path = verify_ref("revision_contract")
    verify_ref("triggering_audit")
    verify_ref("attempt_receipt")
    if contract_path is not None:
        try:
            contract_path.relative_to((project_root / "candidates").resolve())
        except ValueError:
            issues.append("revision_contract_outside_candidates")
    if expected_binding is not None:
        expected_identity = {
            "chapter": chapter,
            "task_id": revision_task_id,
            "source_task_id": source_task_id,
            "job_id": request.get("source_job_id"),
            "candidate_set_id": request.get("candidate_set_id"),
            "revision_attempt_id": request.get("attempt_id"),
        }
        if any(
            expected_binding.get(key) != value
            for key, value in expected_identity.items()
        ):
            issues.append("revision_selection_identity_mismatch")
        actual_bindings = {
            "draft_path": draft.relative_to(root).as_posix(),
            "draft_sha256": draft_hash,
            "revision_request_path": request_path.relative_to(root).as_posix(),
            "revision_request_sha256": _sha256(request_path),
            "writer_output_contract_path": output_contract_path.relative_to(root).as_posix(),
            "writer_output_contract_sha256": _sha256(output_contract_path),
            "writer_session_receipt_path": (
                session_receipt_path.relative_to(root).as_posix()
            ),
            "writer_session_receipt_sha256": _sha256(session_receipt_path),
        }
        if contract_path is not None:
            actual_bindings.update(
                {
                    "contract_path": contract_path.relative_to(root).as_posix(),
                    "contract_sha256": _sha256(contract_path),
                }
            )
            try:
                contract_value = yaml.safe_load(
                    contract_path.read_text(encoding="utf-8")
                ) or {}
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                contract_value = {}
            source_proposal = (
                contract_value.get("source_proposal")
                if isinstance(contract_value, dict)
                else None
            )
            if isinstance(source_proposal, Mapping):
                proposal_relative = str(source_proposal.get("path") or "")
                proposal_hash = str(source_proposal.get("sha256") or "")
                try:
                    proposal_candidate = root / proposal_relative
                    if _has_symlink_component(root, proposal_candidate):
                        raise ValueError("symlink")
                    proposal_path = proposal_candidate.resolve(strict=True)
                    proposal_path.relative_to(root)
                    if _sha256(proposal_path) != proposal_hash:
                        raise ValueError("hash")
                except (OSError, ValueError):
                    issues.append("revision_source_proposal_invalid")
                else:
                    actual_bindings.update(
                        {
                            "proposal_path": proposal_relative,
                            "proposal_sha256": proposal_hash,
                        }
                    )
        for prefix, path in (
            ("triggering_audit", verify_ref("triggering_audit")),
        ):
            if path is not None:
                actual_bindings[f"{prefix}_path"] = path.relative_to(root).as_posix()
                actual_bindings[f"{prefix}_sha256"] = _sha256(path)
        if any(
            expected_binding.get(key) != value
            for key, value in actual_bindings.items()
        ):
            issues.append("revision_selection_binding_mismatch")
    return {
        "status": "pass" if not issues else "blocked",
        "issues": list(dict.fromkeys(issues)),
        "draft_path": str(draft),
        "draft_sha256": draft_hash,
        "revision_task_id": revision_task_id,
        "source_task_id": source_task_id,
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


def prepare_crown_narrative_heavy_audit(
    root: Path,
    *,
    eval_id: str,
    start_chapter: int,
    end_chapter: int,
    task_id: str | None = None,
    chapter_ids: list[int] | None = None,
    draft_bindings: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a fresh, provider-free audit bundle from valid candidate chapters."""
    root = Path(root).resolve()
    project_root = root / "projects" / "Crown_of_Ash"
    selected_chapters = (
        sorted(set(int(chapter) for chapter in chapter_ids))
        if chapter_ids is not None
        else list(range(start_chapter, end_chapter + 1))
    )
    chapter_count = len(selected_chapters)
    issues: list[str] = []
    if start_chapter < 1 or end_chapter < start_chapter:
        issues.append("invalid_chapter_range")
    if not selected_chapters or any(
        chapter < start_chapter or chapter > end_chapter for chapter in selected_chapters
    ):
        issues.append("invalid_selected_chapters")
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
        for chapter in selected_chapters:
            source_task_id = _audit_source_task_id(chapter, clean_eval_id)
            source_run = project_root / "runs" / source_task_id
            delivery = validate_narrative_delivery(source_run)
            if delivery.get("valid") is not True or delivery.get("skipped") is True:
                issues.append(f"invalid_candidate_chapter:{chapter}")
                continue
            draft_binding = (draft_bindings or {}).get(chapter)
            draft_task_id = (
                str(draft_binding.get("task_id") or "")
                if isinstance(draft_binding, Mapping)
                else source_task_id
            )
            draft_run = project_root / "runs" / draft_task_id
            if draft_task_id != source_task_id:
                binding = validate_revision_draft_binding(
                    project_root,
                    chapter=chapter,
                    source_task_id=source_task_id,
                    revision_task_id=draft_task_id,
                    expected_binding=draft_binding,
                )
                if binding.get("status") != "pass":
                    issues.extend(
                        f"invalid_revision_candidate:{chapter}:{item}"
                        for item in binding.get("issues") or []
                    )
                    continue
            files: dict[str, dict[str, Any]] = {}
            chapter_values: dict[str, str] = {}
            for name in (
                "fiction_draft.md",
                "chapter_packet.yml",
                "continuity_ledger.yml",
                "state_transition_proposal.yml",
            ):
                path = (draft_run if name == "fiction_draft.md" else source_run) / name
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
            if len(chapter_values) != 4:
                continue
            source_records.append(
                {
                    "chapter": chapter,
                    "task_id": source_task_id,
                    "draft_task_id": draft_task_id,
                    "files": files,
                }
            )
            context_sections.extend(
                [
                    f"## Chapter {chapter} draft\n\n{chapter_values['fiction_draft.md'].rstrip()}",
                    f"## Chapter {chapter} contract\n\n```yaml\n{chapter_values['chapter_packet.yml'].rstrip()}\n```",
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
        "selected_chapters": selected_chapters,
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
    atomic_write_yaml(target_run / "narrative_audit_manifest.yml", report)
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
    fact_snapshot = project_root / "project_brain" / "project_fact_snapshot.yml"
    shared_files = [
        path
        for path in (
            fact_snapshot,
            project_root / "project_artifact_index.yml",
        )
        if path.is_file()
    ]
    context_path = target_run / "narrative_audit_context.md"
    bundle = build_context_bundle(
        target_run / "context_bundles",
        source_root=root,
        canon_snapshot_sha256=(
            _sha256(fact_snapshot) if fact_snapshot.is_file() else "missing"
        ),
        chapter_window=selected_chapters,
        shared_files=shared_files,
        role_specific_files={"Reviewer": [context_path]},
    )
    report["context_bundle_id"] = bundle["context_bundle_id"]
    report["context_bundle_manifest"] = bundle["manifest_path"]
    report["context_bundle_manifest_sha256"] = bundle["manifest_sha256"]
    report["run_dir"] = str(target_run)
    report["manifest_path"] = str(target_run / "narrative_audit_manifest.yml")
    report["context_path"] = str(context_path)
    atomic_write_yaml(target_run / "narrative_audit_manifest.yml", report)
    return report
