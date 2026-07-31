"""Deterministic, evidence-bearing tools for Frontdesk search and reporting."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Iterable, Mapping

import yaml


MAX_SEARCH_FILE_BYTES = 1024 * 1024
MAX_EXCERPT_CHARS = 240
PASS_STATUSES = {"pass", "passed", "verified"}
FAIL_STATUSES = {"fail", "failed", "blocked", "error"}
VERIFICATION_FILENAMES = (
    "verification_report.yml",
    "validation_report.yml",
    "artifact_validation.yml",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_scope(value: str) -> str:
    scope = str(value).strip().strip("/")
    path = PurePosixPath(scope)
    if not scope or path.is_absolute() or ".." in path.parts:
        raise ValueError("frontdesk search scopes must be relative tracked paths")
    return path.as_posix()


def _tracked_paths(root: Path, scopes: tuple[str, ...]) -> list[str]:
    command = ["git", "ls-files", "-z"]
    if scopes:
        command.extend(["--", *scopes])
    result = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("frontdesk evidence search requires a Git worktree")
    return sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


def search_tracked_evidence(
    agentlab_root: Path,
    query: str,
    *,
    paths: Iterable[str] = (),
    max_results: int = 20,
) -> dict[str, Any]:
    """Search literal text in tracked files and return exact line/hash evidence."""

    root = Path(agentlab_root).resolve()
    literal = str(query).strip()
    if not literal:
        raise ValueError("frontdesk evidence query must not be empty")
    scopes = tuple(_safe_scope(value) for value in paths)
    if max_results < 1 or max_results > 100:
        raise ValueError("frontdesk evidence result limit must be between 1 and 100")
    needle = literal.casefold()
    matches: list[dict[str, Any]] = []
    match_count = 0
    skipped_binary_or_large = 0
    for relative in _tracked_paths(root, scopes):
        path = root / relative
        try:
            if not path.is_file() or path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                skipped_binary_or_large += 1
                continue
            raw = path.read_bytes()
            if b"\0" in raw:
                skipped_binary_or_large += 1
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            skipped_binary_or_large += 1
            continue
        digest: str | None = None
        for line_number, line in enumerate(text.splitlines(), start=1):
            if needle not in line.casefold():
                continue
            match_count += 1
            if len(matches) >= max_results:
                continue
            if digest is None:
                digest = hashlib.sha256(raw).hexdigest()
            matches.append(
                {
                    "path": relative,
                    "line": line_number,
                    "excerpt": line.strip()[:MAX_EXCERPT_CHARS],
                    "sha256": digest,
                }
            )
    return {
        "schema_version": "frontdesk-evidence-search/v1",
        "search_mode": "literal_tracked_text",
        "query": literal,
        "scopes": list(scopes) or ["<all-tracked-files>"],
        "match_count": match_count,
        "returned_count": len(matches),
        "truncated": match_count > len(matches),
        "skipped_binary_or_large": skipped_binary_or_large,
        "matches": matches,
    }


def _safe_identifier(value: str, label: str) -> str:
    selected = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", selected):
        raise ValueError(f"frontdesk {label} contains unsafe characters")
    return selected


def _load_mapping(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return value if isinstance(value, Mapping) else None


def _evidence(root: Path, path: Path, status: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
    }
    if status is not None:
        value["status"] = status
    return value


def build_grounded_task_report(
    agentlab_root: Path,
    project: str,
    task_id: str,
) -> dict[str, Any]:
    """Build a conservative report from canonical on-disk task evidence."""

    root = Path(agentlab_root).resolve()
    project_name = _safe_identifier(project, "project")
    selected_task_id = _safe_identifier(task_id, "task_id")
    run_dir = root / "projects" / project_name / "runs" / selected_task_id
    state_path = run_dir / "state.yml"
    state = _load_mapping(state_path)
    unknowns: list[str] = []
    if state is None:
        task_status = {"value": "unknown", "source": None}
        unknowns.append("No readable canonical task state was found.")
    else:
        task_status = {
            "value": str(state.get("status") or "unknown"),
            "source": state_path.relative_to(root).as_posix(),
            "sha256": _sha256(state_path),
        }

    verification_evidence: list[dict[str, Any]] = []
    observed_statuses: list[str] = []
    for filename in VERIFICATION_FILENAMES:
        path = run_dir / filename
        artifact = _load_mapping(path)
        if artifact is None:
            continue
        status = str(artifact.get("status") or "unknown").strip().casefold()
        observed_statuses.append(status)
        verification_evidence.append(_evidence(root, path, status=status))
    if any(status in FAIL_STATUSES for status in observed_statuses):
        verification_status = "fail"
    elif observed_statuses and all(
        status in PASS_STATUSES for status in observed_statuses
    ):
        verification_status = "pass"
    else:
        verification_status = "unknown"
    if not verification_evidence:
        unknowns.append("No canonical verification artifact was found.")
    elif verification_status == "unknown":
        unknowns.append(
            "Verification artifacts do not contain a recognized PASS/FAIL status."
        )

    return {
        "schema_version": "frontdesk-grounded-report/v1",
        "project": project_name,
        "task_id": selected_task_id,
        "task_exists": run_dir.is_dir(),
        "task_status": task_status,
        "verification_status": verification_status,
        "reportable_as_verified": verification_status == "pass",
        "verification_evidence": verification_evidence,
        "unknowns": unknowns,
        "reporting_rule": "Only claims with a path and sha256 may be presented as verified.",
    }
