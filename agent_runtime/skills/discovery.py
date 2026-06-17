"""R5: Skill Discovery v1 — Deterministic Candidate Discovery.

Scans local project sources (scripts, acceptance reports, recovery feedback,
docs) and produces *candidate* skill dicts.  Discovery is read-only and
metadata-only: it never installs, enables, executes, or copies source code
from any external source.

Every candidate is emitted with:
    - enabled: False
    - lifecycle_status: "candidate"
    - promotion.requires_human_review: True

This module is intentionally stdlib-only and deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from agent_runtime.local_search.document import content_hash_of
except ImportError:  # pragma: no cover — allow flat-import in tests
    from local_search.document import content_hash_of  # type: ignore[no-redef]


# ── Helpers ──────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _make_candidate_id(title: str) -> str:
    """Produce a deterministic, URL-safe slug from *title*.

    Lowercases, replaces non-alphanumeric runs with hyphens, and strips
    leading/trailing hyphens.  The result is stable across runs.
    """
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "unnamed-candidate"


def _read_text_safe(path: Path) -> str | None:
    """Read *path* as UTF-8 text, returning ``None`` on any failure."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _build_candidate(
    *,
    title: str,
    source_evidence: list[dict[str, str]],
    proposed_capabilities: list[str],
    suitable_task_types: list[str],
    proposed_inputs: list[str] | None = None,
    proposed_outputs: list[str] | None = None,
    risk_level: str = "medium",
    risk_reasons: list[str] | None = None,
    license_source: str = "unknown",
    license_review_required: bool = True,
) -> dict[str, Any]:
    """Build a fully-populated candidate dict with safe defaults."""
    return {
        "candidate_id": _make_candidate_id(title),
        "title": title,
        "source_evidence": list(source_evidence),
        "proposed_capabilities": list(proposed_capabilities),
        "suitable_task_types": list(suitable_task_types),
        "proposed_inputs": list(proposed_inputs or []),
        "proposed_outputs": list(proposed_outputs or []),
        "risk": {
            "level": risk_level,
            "reasons": list(risk_reasons or ["Discovered heuristically; not yet validated."]),
            "requires_approval": True,
        },
        "license": {
            "source": license_source,
            "review_required": license_review_required,
        },
        "lifecycle_status": "candidate",
        "enabled": False,
        "promotion": {
            "requires_human_review": True,
            "requires_tests": True,
            "requires_metadata_completion": True,
        },
    }


def _evidence_entry(path: str, source_category: str, text: str) -> dict[str, str]:
    """Create a single source_evidence entry."""
    return {
        "path": path,
        "source_category": source_category,
        "content_hash": content_hash_of(text),
    }


# ── Scanners ─────────────────────────────────────────────────────────────────

_SCRIPT_DIRS = ("scripts", "agent_templates")
_MIN_LINES = 100


def _scan_scripts(root: Path) -> list[dict[str, Any]]:
    """Find Python/Shell scripts with clear purpose (docstring, >100 lines).

    A script qualifies as a skill candidate when:
    - It lives under ``scripts/`` or ``agent_templates/``.
    - It has at least 100 lines (non-trivial).
    - It contains a module-level docstring (indicates documented purpose).
    """
    candidates: list[dict[str, Any]] = []
    for dirname in _SCRIPT_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for script_path in sorted(base.rglob("*.py")):
            text = _read_text_safe(script_path)
            if text is None:
                continue
            lines = text.splitlines()
            if len(lines) < _MIN_LINES:
                continue
            # Check for a module-level docstring (first non-blank, non-comment line starts with """ or ''')
            has_docstring = False
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    has_docstring = True
                break
            if not has_docstring:
                continue

            rel = str(script_path.relative_to(root))
            title = f"Script: {script_path.stem.replace('_', ' ').title()}"
            evidence = [_evidence_entry(rel, "scripts", text)]
            candidates.append(
                _build_candidate(
                    title=title,
                    source_evidence=evidence,
                    proposed_capabilities=[f"Run {script_path.stem} workflow"],
                    suitable_task_types=["automation", "scripting"],
                    proposed_inputs=["command_line_args"],
                    proposed_outputs=["text", "report"],
                    risk_level="medium",
                    risk_reasons=["Script discovered from local directory; not sandbox-tested."],
                    license_source="agentlab_internal",
                    license_review_required=False,
                )
            )
    return candidates


_ACCEPTANCE_DIR = "acceptance_runs"
_ACCEPTANCE_PATTERN = "acceptance_report*"


def _scan_acceptance_reports(root: Path) -> list[dict[str, Any]]:
    """Find repeated acceptance report patterns.

    Scans ``acceptance_runs/*/`` for files matching ``acceptance_report*``.
    Groups reports by directory stem to identify repeated patterns.  When
    two or more reports share a structural pattern (same file names), a
    candidate is emitted.
    """
    base = root / _ACCEPTANCE_DIR
    if not base.is_dir():
        return []

    # Collect all acceptance report files grouped by parent directory.
    report_groups: dict[str, list[tuple[Path, str]]] = {}
    for report_path in sorted(base.rglob("*")):
        if not report_path.is_file():
            continue
        if not report_path.name.startswith(_ACCEPTANCE_PATTERN.rstrip("*")):
            continue
        text = _read_text_safe(report_path)
        if text is None:
            continue
        parent_name = report_path.parent.name
        rel = str(report_path.relative_to(root))
        report_groups.setdefault(parent_name, []).append((report_path, text))

    # We need at least two report groups to detect a repeated pattern.
    if len(report_groups) < 2:
        return []

    # Build evidence from all discovered reports.
    evidence: list[dict[str, str]] = []
    all_texts: list[str] = []
    for _parent_name, entries in report_groups.items():
        for fpath, text in entries:
            rel = str(fpath.relative_to(root))
            evidence.append(_evidence_entry(rel, "acceptance_runs", text))
            all_texts.append(text)

    # Check for structural overlap: same file names across different runs.
    file_names_per_group: list[set[str]] = []
    for _parent_name, entries in report_groups.items():
        file_names_per_group.append({fp.name for fp, _ in entries})
    if not file_names_per_group:
        return []
    common_names = file_names_per_group[0]
    for name_set in file_names_per_group[1:]:
        common_names = common_names & name_set

    if not common_names:
        return []

    combined_text = "\n---\n".join(all_texts[:5])
    evidence.append(
        _evidence_entry("acceptance_runs/_pattern_summary", "acceptance_runs", combined_text)
    )

    return [
        _build_candidate(
            title="Acceptance Report Pattern Analyzer",
            source_evidence=evidence,
            proposed_capabilities=[
                "Detect recurring acceptance report structures",
                "Summarize acceptance outcomes across runs",
            ],
            suitable_task_types=["acceptance", "review", "reporting"],
            proposed_inputs=["acceptance_report_files"],
            proposed_outputs=["summary_report", "pattern_analysis"],
            risk_level="low",
            risk_reasons=["Read-only analysis of local acceptance artifacts."],
            license_source="agentlab_internal",
            license_review_required=False,
        )
    ]


_RECOVERY_DIR = "recovery_runs"
_CLOSURE_FEEDBACK_FILE = "closure_quality_feedback.json"


def _scan_recovery_feedback(root: Path) -> list[dict[str, Any]]:
    """Find repeated recovery closure feedback categories.

    Scans project run directories for ``recovery/closure_quality_feedback.json``
    files.  When three or more tasks share a failure category, a candidate is
    emitted suggesting a skill that could prevent or handle that category.
    """
    # Look in projects/*/runs/*/recovery/ and also in a flat recovery_runs/ dir.
    feedback_files: list[Path] = []

    # projects/*/runs/*/recovery/
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for fb in sorted(projects_dir.rglob(f"recovery/{_CLOSURE_FEEDBACK_FILE}")):
            if fb.is_file():
                feedback_files.append(fb)

    # Flat recovery_runs/ directory (each subdirectory may contain feedback).
    recovery_dir = root / _RECOVERY_DIR
    if recovery_dir.is_dir():
        for fb in sorted(recovery_dir.rglob(_CLOSURE_FEEDBACK_FILE)):
            if fb.is_file():
                feedback_files.append(fb)

    if not feedback_files:
        return []

    # Tally failure categories across feedback files.
    import json as _json

    category_counts: dict[str, int] = {}
    evidence: list[dict[str, str]] = []
    for fb_path in feedback_files:
        text = _read_text_safe(fb_path)
        if text is None:
            continue
        rel = str(fb_path.relative_to(root))
        evidence.append(_evidence_entry(rel, "closure_feedback", text))
        try:
            data = _json.loads(text)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for cat in data.get("failure_categories", []):
            if isinstance(cat, str) and cat.strip():
                category_counts[cat.strip()] = category_counts.get(cat.strip(), 0) + 1

    # Require at least one category appearing in 3+ tasks.
    repeated = {cat: cnt for cat, cnt in category_counts.items() if cnt >= 3}
    if not repeated:
        return []

    top_categories = sorted(repeated, key=lambda c: repeated[c], reverse=True)[:5]

    return [
        _build_candidate(
            title="Recovery Feedback Pattern Handler",
            source_evidence=evidence,
            proposed_capabilities=[
                f"Handle recurring failure category: {cat}" for cat in top_categories
            ],
            suitable_task_types=["recovery", "failure_handling", "retry"],
            proposed_inputs=["failure_event", "diagnosis", "recovery_history"],
            proposed_outputs=["recovery_plan", "prevention_recommendations"],
            risk_level="medium",
            risk_reasons=[
                "Derived from recovery patterns; may need domain-specific tuning.",
                "Failure categories are heuristic labels, not guaranteed accurate.",
            ],
            license_source="agentlab_internal",
            license_review_required=False,
        )
    ]


_DOCS_DIR = "docs"
_CHECKLIST_MARKERS = ("- [ ]", "- [x]", "- [X]", "* [ ]", "* [x]")


def _scan_docs(root: Path) -> list[dict[str, Any]]:
    """Find docs with checklist-like structure.

    Scans ``docs/`` for Markdown files that contain checklist markers
    (``- [ ]``, ``- [x]``).  Documents with at least 5 checklist items are
    considered candidates for workflow automation skills.
    """
    base = root / _DOCS_DIR
    if not base.is_dir():
        return []

    candidates: list[dict[str, Any]] = []
    for md_path in sorted(base.glob("*.md")):
        text = _read_text_safe(md_path)
        if text is None:
            continue
        lines = text.splitlines()

        # Count checklist items.
        checklist_count = sum(
            1 for line in lines if any(marker in line for marker in _CHECKLIST_MARKERS)
        )
        if checklist_count < 5:
            continue

        rel = str(md_path.relative_to(root))
        evidence = [_evidence_entry(rel, "docs", text)]
        title = f"Workflow: {md_path.stem.replace('_', ' ').title()}"
        candidates.append(
            _build_candidate(
                title=title,
                source_evidence=evidence,
                proposed_capabilities=[
                    f"Automate checklist steps from {md_path.name}",
                ],
                suitable_task_types=["workflow", "checklist", "process"],
                proposed_inputs=["checklist_document"],
                proposed_outputs=["execution_report", "status_update"],
                risk_level="low",
                risk_reasons=["Doc-based workflow; read-only discovery."],
                license_source="agentlab_internal",
                license_review_required=False,
            )
        )
    return candidates


# ── Deduplication ────────────────────────────────────────────────────────────


def _deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate candidates by ``candidate_id``, keeping the first seen.

    When duplicates are found, their ``source_evidence`` lists are merged so
    no evidence is lost.
    """
    seen: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        cid = candidate.get("candidate_id", "")
        if not cid:
            continue
        if cid in seen:
            # Merge evidence from the duplicate into the existing entry.
            existing_ids = {
                (e.get("path"), e.get("content_hash"))
                for e in seen[cid].get("source_evidence", [])
            }
            for ev in candidate.get("source_evidence", []):
                key = (ev.get("path"), ev.get("content_hash"))
                if key not in existing_ids:
                    seen[cid]["source_evidence"].append(ev)
                    existing_ids.add(key)
        else:
            seen[cid] = candidate
    return list(seen.values())


# ── Public API ───────────────────────────────────────────────────────────────


def discover_candidates(
    root: Path,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Scan local sources and return a deduplicated list of skill candidates.

    Parameters
    ----------
    root:
        The AgentLab project root directory.
    config:
        Optional configuration dict.  Recognised keys:
        - ``discovery.enabled`` (bool): when ``False`` return an empty list.
        - ``discovery.scanners`` (list[str]): limit which scanners run.
          Valid values: ``scripts``, ``acceptance_reports``,
          ``recovery_feedback``, ``docs``.  Defaults to all four.

    Returns
    -------
    list[dict]
        Deduplicated candidate dicts, each with ``enabled=False`` and
        ``lifecycle_status="candidate"``.
    """
    config = config or {}
    discovery_cfg = config.get("discovery", {}) if isinstance(config, dict) else {}

    # Honour the global enabled flag.
    if not discovery_cfg.get("enabled", True):
        return []

    # Determine which scanners to run.
    allowed_scanners = discovery_cfg.get("scanners")
    if allowed_scanners is not None:
        allowed_scanners = set(allowed_scanners)
    else:
        allowed_scanners = {"scripts", "acceptance_reports", "recovery_feedback", "docs"}

    all_candidates: list[dict[str, Any]] = []

    scanner_map = {
        "scripts": _scan_scripts,
        "acceptance_reports": _scan_acceptance_reports,
        "recovery_feedback": _scan_recovery_feedback,
        "docs": _scan_docs,
    }

    for name, scanner_fn in scanner_map.items():
        if name in allowed_scanners:
            try:
                found = scanner_fn(root)
            except Exception:
                # Scanners must never crash the discovery pipeline.
                found = []
            all_candidates.extend(found)

    return _deduplicate_candidates(all_candidates)
