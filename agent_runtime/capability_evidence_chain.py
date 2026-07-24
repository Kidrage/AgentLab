"""Canonical current evidence chain for AgentLab capability acceptance.

Exactly one machine-verifiable current chain is allowed. Historical and archived
artifacts may remain on disk for audit, but they never count as current evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import subprocess
from pathlib import Path
from typing import Any

try:
    from agent_runtime.atomic_io import atomic_write_text, safe_read_yaml
    from agent_runtime.report_sanitizer import dump_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from atomic_io import atomic_write_text, safe_read_yaml
    from report_sanitizer import dump_report_yaml


SCHEMA_VERSION = 1
REPORT_TYPE = "agentlab_capability_current_evidence_chain"
CHAIN_ID = "agentlab_capability_current"
CHAIN_FILENAME = "current_evidence_chain.yml"
SOURCE_REPORT_FILENAME = "current.yml"
SOURCE_REPORT_TYPE = "agentlab_capability_acceptance"
CANONICAL_SOURCE_REL = "acceptance_runs/agentlab_capability_acceptance/current.yml"

# Fallback markers when config is unavailable; real classification loads policy.
_DEFAULT_ARCHIVE_COMPONENTS = frozenset({"archive", "run_history", "_archive", "superseded", "retired"})
_RETIRED_META_STATUSES = frozenset({"retired", "superseded"})


def acceptance_base(root: Path) -> Path:
    return root.resolve() / "acceptance_runs" / "agentlab_capability_acceptance"


def chain_path(root: Path) -> Path:
    return acceptance_base(root) / CHAIN_FILENAME


def source_report_path(root: Path) -> Path:
    return root.resolve() / CANONICAL_SOURCE_REL


def _load_policy_maps(root: Path | None) -> tuple[frozenset[str], tuple[str, ...]]:
    """Load historical path markers from retention + content-governance config."""
    components = set(_DEFAULT_ARCHIVE_COMPONENTS)
    markers: list[str] = []
    if root is not None:
        root = root.resolve()
        retention = safe_read_yaml(root / "config" / "run_retention_policy.yml", default={}) or {}
        content = safe_read_yaml(root / "config" / "content_project_governance.yml", default={}) or {}
        archive_root = str(retention.get("archive_root") or "archive/run_history").replace("\\", "/").strip("/")
        if archive_root:
            markers.append(f"/{archive_root}/")
            markers.append(archive_root)
            components.update(part.lower() for part in Path(archive_root).parts if part not in {".", ".."})
        for item in content.get("archive_roots") or []:
            name = str(item).replace("\\", "/").strip("/")
            if not name:
                continue
            components.add(name.lower())
            markers.append(f"/{name}/")
            markers.append(name)
    if not markers:
        markers = ["/archive/", "/run_history/", "/superseded/", "/retired/", "archive/run_history"]
    return frozenset(components), tuple(dict.fromkeys(markers))


def is_historical_evidence_path(path_text: str, root: Path | None = None) -> bool:
    """Return True when a path may not count as current/active evidence."""
    normalized = str(path_text or "").replace("\\", "/").strip()
    if not normalized:
        return False
    components, markers = _load_policy_maps(root)
    lowered = normalized.lower()
    if any(marker.lower() in lowered for marker in markers):
        return True
    parts = {part.lower() for part in Path(normalized).parts}
    return bool(parts & components)


def _normalize_rel_text(path_text: str) -> str:
    return str(path_text or "").replace("\\", "/").strip()


def _is_safe_repo_relative(path_text: str) -> bool:
    text = _normalize_rel_text(path_text)
    if not text or text.startswith("/") or Path(text).is_absolute():
        return False
    if text.startswith("~") or "://" in text:
        return False
    return ".." not in Path(text).parts


def resolve_safe_evidence_file(root: Path, path_text: str) -> Path | None:
    """Return a repository-relative regular file path, or None if unsafe/unusable.

    Never follows or hashes absolute paths, escapes, symlinks, directories, or
    historical/retired/superseded artifacts.
    """
    root = root.resolve()
    text = _normalize_rel_text(path_text)
    if not _is_safe_repo_relative(text):
        return None
    if is_historical_evidence_path(text, root):
        return None
    candidate = root / text
    try:
        cursor = root
        for part in Path(text).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        if not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    if resolved.is_symlink() or not resolved.is_file():
        return None
    if resolved.suffix.lower() in {".yml", ".yaml"}:
        meta = safe_read_yaml(resolved, default=None)
        if isinstance(meta, dict):
            nested = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
            statuses = {
                str(meta.get("status") or "").strip().lower(),
                str(meta.get("authority_status") or "").strip().lower(),
                str(nested.get("status") or "").strip().lower(),
                str(nested.get("authority_status") or "").strip().lower(),
            }
            if statuses & _RETIRED_META_STATUSES:
                return None
    return candidate


def classify_evidence_path(root: Path, path_text: str) -> str:
    """Classify one evidence path as active, historical, or missing/unsafe."""
    text = _normalize_rel_text(path_text)
    if not text:
        return "missing"
    if is_historical_evidence_path(text, root):
        return "historical"
    if resolve_safe_evidence_file(root, text) is not None:
        return "active"
    return "missing"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_aggregate_digest(items: list[dict[str, str]]) -> str:
    """Deterministic root digest over selected current evidence path+hash pairs."""
    lines = [
        f"{item.get('path') or ''}:{item.get('sha256') or ''}"
        for item in sorted(items, key=lambda row: str(row.get("path") or ""))
    ]
    body = "\n".join(lines) + ("\n" if lines else "")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    data = safe_read_yaml(path, default={})
    return data if isinstance(data, dict) else {}


def _git_identity(root: Path) -> dict[str, Any]:
    identity: dict[str, Any] = {"root": ".", "head": None, "worktree_dirty": None}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if head.returncode == 0:
            identity["head"] = head.stdout.strip() or None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if status.returncode == 0:
            identity["worktree_dirty"] = bool(status.stdout.strip())
    except OSError:
        pass
    return identity


def partition_capability_evidence(root: Path, capability: dict[str, Any]) -> dict[str, Any]:
    """Split one capability's evidence into active vs historical references."""
    root = root.resolve()
    raw = [_normalize_rel_text(item) for item in (capability.get("evidence") or []) if str(item or "").strip()]
    existing_historical = [
        _normalize_rel_text(item)
        for item in (capability.get("historical_evidence") or [])
        if str(item or "").strip()
    ]
    active: list[str] = []
    historical: list[str] = []
    missing: list[str] = []
    for path_text in raw:
        # Canonical reports must already contain repository-relative paths.
        # Never resolve or inspect absolute input here.
        if Path(path_text).is_absolute() or path_text.startswith("/"):
            missing.append(path_text)
            continue
        kind = classify_evidence_path(root, path_text)
        if kind == "historical":
            historical.append(path_text)
        elif kind == "active":
            active.append(path_text)
        else:
            missing.append(path_text)
    for path_text in existing_historical:
        if path_text not in historical:
            historical.append(path_text)
    return {
        "active_evidence": active,
        "historical_evidence": historical,
        "missing_evidence": missing,
    }


def apply_current_evidence_policy(root: Path, capability: dict[str, Any]) -> dict[str, Any]:
    """Fail closed: historical-only proof cannot remain pass."""
    root = root.resolve()
    partitioned = partition_capability_evidence(root, capability)
    active = partitioned["active_evidence"]
    historical = partitioned["historical_evidence"]
    missing = partitioned["missing_evidence"]
    result = dict(capability)
    result["evidence"] = list(active)
    if historical:
        result["historical_evidence"] = list(historical)
    else:
        result.pop("historical_evidence", None)

    status = str(result.get("status") or "")
    issues = [str(item) for item in (result.get("issues") or [])]
    if status == "pass":
        if not active:
            result["status"] = "candidate" if historical else "fail"
            if historical:
                issue = (
                    "current pass requires active evidence; only historical/"
                    "archived evidence is available"
                )
                if issue not in issues:
                    issues.append(issue)
            if missing:
                issue = "current evidence files are missing"
                if issue not in issues:
                    issues.append(issue)
            if not historical and not missing:
                issue = "current pass requires at least one active evidence path"
                if issue not in issues:
                    issues.append(issue)
        elif missing:
            result["status"] = "fail"
            issue = "current pass evidence is missing on disk"
            if issue not in issues:
                issues.append(issue)
        elif historical:
            details = result.get("details") if isinstance(result.get("details"), dict) else {}
            details = dict(details)
            details["historical_evidence_excluded_from_current"] = True
            result["details"] = details
    result["issues"] = issues
    return result


def collect_report_evidence(
    root: Path,
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect unique active evidence and historical references from a report."""
    root = root.resolve()
    active_map: dict[str, dict[str, Any]] = {}
    historical_map: dict[str, dict[str, Any]] = {}

    for capability in report.get("capabilities") or []:
        if not isinstance(capability, dict):
            continue
        capability_id = str(capability.get("id") or "unknown")
        partitioned = partition_capability_evidence(root, capability)
        for path_text in partitioned["active_evidence"]:
            entry = active_map.setdefault(
                path_text,
                {"path": path_text, "class": "active", "capability_ids": []},
            )
            if capability_id not in entry["capability_ids"]:
                entry["capability_ids"].append(capability_id)
        for path_text in partitioned["historical_evidence"]:
            entry = historical_map.setdefault(
                path_text,
                {
                    "path": path_text,
                    "class": "historical",
                    "reason": "archive_or_run_history_or_superseded",
                    "capability_ids": [],
                },
            )
            if capability_id not in entry["capability_ids"]:
                entry["capability_ids"].append(capability_id)
        for path_text in partitioned["missing_evidence"]:
            entry = historical_map.setdefault(
                path_text,
                {
                    "path": path_text,
                    "class": "missing",
                    "reason": "missing_or_unsafe_for_current",
                    "capability_ids": [],
                },
            )
            if capability_id not in entry["capability_ids"]:
                entry["capability_ids"].append(capability_id)

    active_items: list[dict[str, Any]] = []
    for path_text, entry in sorted(active_map.items()):
        absolute = resolve_safe_evidence_file(root, path_text)
        if absolute is None:
            historical_map[path_text] = {
                "path": path_text,
                "class": "missing",
                "reason": "missing_or_unsafe_for_current",
                "capability_ids": entry["capability_ids"],
            }
            continue
        active_items.append(
            {
                "path": path_text,
                "class": "active",
                "capability_ids": sorted(entry["capability_ids"]),
                "sha256": sha256_file(absolute),
            }
        )

    historical_items = [
        {**entry, "capability_ids": sorted(entry.get("capability_ids") or [])}
        for _, entry in sorted(historical_map.items())
    ]
    return active_items, historical_items


def build_capability_current_evidence_chain(
    root: Path,
    *,
    capability_report: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the single canonical current evidence chain from the capability report."""
    root = root.resolve()
    report_path = source_report_path(root)
    report = capability_report if capability_report is not None else _read_yaml(report_path)
    if not report:
        report = {
            "schema_version": 1,
            "report_type": SOURCE_REPORT_TYPE,
            "capabilities": [],
            "overall_status": "fail",
        }

    active_items, historical_items = collect_report_evidence(root, report)
    source_digest = sha256_file(report_path) if report_path.is_file() and not report_path.is_symlink() else None

    aggregate = compute_aggregate_digest(
        [{"path": item["path"], "sha256": item["sha256"]} for item in active_items]
    )
    issues: list[dict[str, Any]] = []
    if report.get("report_type") not in {None, SOURCE_REPORT_TYPE}:
        issues.append(
            {
                "reason": "source_report_type_mismatch",
                "expected": SOURCE_REPORT_TYPE,
                "actual": report.get("report_type"),
            }
        )
    for capability in report.get("capabilities") or []:
        if not isinstance(capability, dict) or capability.get("status") != "pass":
            continue
        partitioned = partition_capability_evidence(root, capability)
        if not partitioned["active_evidence"]:
            issues.append(
                {
                    "reason": "pass_without_active_evidence",
                    "capability_id": capability.get("id"),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "chain_id": CHAIN_ID,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": _git_identity(root),
        "source_report": {
            "path": CANONICAL_SOURCE_REL,
            "report_type": SOURCE_REPORT_TYPE,
            "sha256": source_digest,
            "overall_status": report.get("overall_status"),
        },
        "current_evidence": active_items,
        "current_evidence_count": len(active_items),
        "historical_references": historical_items,
        "historical_reference_count": len(historical_items),
        "aggregate_digest": aggregate,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "notes": [
            "Exactly one canonical current evidence chain is authoritative.",
            "Paths under archive/run_history or retired/superseded trees never count as current evidence.",
            "Historical references remain available for audit only.",
            f"Source report is fixed to {CANONICAL_SOURCE_REL}.",
        ],
    }


def _find_duplicate_current_chains(root: Path) -> list[str]:
    """Return non-canonical paths that claim the current evidence-chain report type."""
    base = acceptance_base(root)
    if not base.is_dir():
        return []
    duplicates: list[str] = []
    for candidate in sorted(base.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in {".yml", ".yaml"}:
            continue
        if candidate.name == CHAIN_FILENAME and candidate.parent == base:
            continue
        if candidate.is_symlink():
            continue
        data = _read_yaml(candidate)
        if data.get("report_type") == REPORT_TYPE:
            try:
                duplicates.append(str(candidate.relative_to(root)).replace("\\", "/"))
            except ValueError:
                duplicates.append(str(candidate))
    return duplicates


def _evidence_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path:
            index[path] = item
    return index


def _duplicate_evidence_paths(items: list[dict[str, Any]]) -> list[str]:
    paths = [str(item.get("path") or "") for item in items if item.get("path")]
    return sorted({path for path in paths if paths.count(path) > 1})


def verify_capability_current_evidence_chain(
    root: Path,
    *,
    chain: dict[str, Any] | None = None,
    chain_file: Path | None = None,
) -> dict[str, Any]:
    """Verify uniqueness, fixed source binding, rebuilt evidence sets, and digest."""
    root = root.resolve()
    canonical_path = chain_path(root)
    path = chain_file or canonical_path
    if not path.is_absolute():
        path = root / path
    issues: list[dict[str, Any]] = []
    if chain is None:
        try:
            is_canonical_file = (
                path.absolute() == canonical_path.absolute()
                and not path.is_symlink()
            )
        except OSError:
            is_canonical_file = False
        if not is_canonical_file:
            issues.append(
                {
                    "reason": "chain_path_not_canonical",
                    "expected": str(canonical_path.relative_to(root)),
                    "actual": str(path),
                }
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "report_type": "agentlab_capability_current_evidence_chain_verification",
                "status": "fail",
                "chain_path": str(path),
                "issues": issues,
            }
    loaded = chain if chain is not None else _read_yaml(path)

    if not loaded:
        issues.append({"reason": "chain_missing", "path": str(path)})
        return {
            "schema_version": SCHEMA_VERSION,
            "report_type": "agentlab_capability_current_evidence_chain_verification",
            "status": "fail",
            "chain_path": str(path),
            "issues": issues,
        }

    if loaded.get("report_type") != REPORT_TYPE:
        issues.append(
            {
                "reason": "report_type_mismatch",
                "expected": REPORT_TYPE,
                "actual": loaded.get("report_type"),
            }
        )
    if loaded.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            {
                "reason": "schema_version_mismatch",
                "expected": SCHEMA_VERSION,
                "actual": loaded.get("schema_version"),
            }
        )
    if loaded.get("chain_id") != CHAIN_ID:
        issues.append(
            {
                "reason": "chain_id_mismatch",
                "expected": CHAIN_ID,
                "actual": loaded.get("chain_id"),
            }
        )

    duplicates = _find_duplicate_current_chains(root)
    if duplicates:
        issues.append(
            {
                "reason": "duplicate_current_chain",
                "paths": duplicates,
                "detail": "exactly one canonical current chain is allowed",
            }
        )

    source = loaded.get("source_report") if isinstance(loaded.get("source_report"), dict) else {}
    declared_source_path = _normalize_rel_text(str(source.get("path") or ""))
    if declared_source_path != CANONICAL_SOURCE_REL:
        issues.append(
            {
                "reason": "source_report_path_not_canonical",
                "expected": CANONICAL_SOURCE_REL,
                "actual": declared_source_path or None,
            }
        )
    if source.get("report_type") != SOURCE_REPORT_TYPE:
        issues.append(
            {
                "reason": "declared_source_report_type_mismatch",
                "expected": SOURCE_REPORT_TYPE,
                "actual": source.get("report_type"),
            }
        )

    # Always rebuild from the fixed canonical report; never trust a substituted source.
    source_abs = source_report_path(root)
    if not source_abs.is_file() or source_abs.is_symlink():
        issues.append({"reason": "source_report_missing", "path": CANONICAL_SOURCE_REL})
        source_data: dict[str, Any] = {}
    else:
        actual_source_digest = sha256_file(source_abs)
        if source.get("sha256") != actual_source_digest:
            issues.append(
                {
                    "reason": "source_report_hash_mismatch",
                    "path": CANONICAL_SOURCE_REL,
                    "expected": source.get("sha256"),
                    "actual": actual_source_digest,
                }
            )
        source_data = _read_yaml(source_abs)
        if source_data.get("report_type") != SOURCE_REPORT_TYPE:
            issues.append(
                {
                    "reason": "source_report_type_mismatch",
                    "expected": SOURCE_REPORT_TYPE,
                    "actual": source_data.get("report_type"),
                }
            )
        if source.get("overall_status") != source_data.get("overall_status"):
            issues.append(
                {
                    "reason": "source_overall_status_mismatch",
                    "expected": source_data.get("overall_status"),
                    "actual": source.get("overall_status"),
                }
            )

    rebuilt_active, rebuilt_historical = collect_report_evidence(root, source_data or {})
    declared_active = [
        item for item in (loaded.get("current_evidence") or []) if isinstance(item, dict)
    ]
    duplicate_active = _duplicate_evidence_paths(declared_active)
    if duplicate_active:
        issues.append(
            {
                "reason": "duplicate_current_evidence_path",
                "paths": duplicate_active,
            }
        )
    if loaded.get("current_evidence_count") != len(declared_active):
        issues.append(
            {
                "reason": "current_evidence_count_mismatch",
                "expected": len(declared_active),
                "actual": loaded.get("current_evidence_count"),
            }
        )
    declared_index = _evidence_index(declared_active)
    rebuilt_index = _evidence_index(rebuilt_active)

    if set(declared_index) != set(rebuilt_index):
        issues.append(
            {
                "reason": "current_evidence_set_mismatch",
                "expected_paths": sorted(rebuilt_index),
                "actual_paths": sorted(declared_index),
            }
        )

    for path_text, expected in rebuilt_index.items():
        actual = declared_index.get(path_text)
        if actual is None:
            continue
        if sorted(actual.get("capability_ids") or []) != sorted(expected.get("capability_ids") or []):
            issues.append(
                {
                    "reason": "current_evidence_capability_ids_mismatch",
                    "path": path_text,
                    "expected": sorted(expected.get("capability_ids") or []),
                    "actual": sorted(actual.get("capability_ids") or []),
                }
            )
        if str(actual.get("sha256") or "") != str(expected.get("sha256") or ""):
            issues.append(
                {
                    "reason": "current_evidence_hash_mismatch",
                    "path": path_text,
                    "expected": expected.get("sha256"),
                    "actual": actual.get("sha256"),
                }
            )

    for path_text, item in declared_index.items():
        if resolve_safe_evidence_file(root, path_text) is None:
            reason = (
                "historical_path_in_current_evidence"
                if is_historical_evidence_path(path_text, root)
                else "current_evidence_missing"
            )
            issues.append({"reason": reason, "path": path_text})
        elif path_text in rebuilt_index:
            # Already compared hashes above against rebuilt disk truth.
            pass

    expected_aggregate = compute_aggregate_digest(
        [{"path": item["path"], "sha256": item["sha256"]} for item in rebuilt_active]
    )
    declared_aggregate = str(loaded.get("aggregate_digest") or "")
    if declared_aggregate != expected_aggregate:
        issues.append(
            {
                "reason": "aggregate_digest_mismatch",
                "expected": expected_aggregate,
                "actual": declared_aggregate,
            }
        )

    declared_historical = [
        item
        for item in (loaded.get("historical_references") or [])
        if isinstance(item, dict)
    ]
    duplicate_historical = _duplicate_evidence_paths(declared_historical)
    if duplicate_historical:
        issues.append(
            {
                "reason": "duplicate_historical_reference_path",
                "paths": duplicate_historical,
            }
        )
    if loaded.get("historical_reference_count") != len(declared_historical):
        issues.append(
            {
                "reason": "historical_reference_count_mismatch",
                "expected": len(declared_historical),
                "actual": loaded.get("historical_reference_count"),
            }
        )
    declared_hist_index = _evidence_index(declared_historical)
    rebuilt_hist_index = _evidence_index(rebuilt_historical)
    if set(declared_hist_index) != set(rebuilt_hist_index):
        issues.append(
            {
                "reason": "historical_reference_set_mismatch",
                "expected_paths": sorted(rebuilt_hist_index),
                "actual_paths": sorted(declared_hist_index),
            }
        )
    for path_text, expected in rebuilt_hist_index.items():
        actual = declared_hist_index.get(path_text)
        if actual is None:
            continue
        for field in ("class", "reason"):
            if actual.get(field) != expected.get(field):
                issues.append(
                    {
                        "reason": f"historical_reference_{field}_mismatch",
                        "path": path_text,
                        "expected": expected.get(field),
                        "actual": actual.get(field),
                    }
                )
        if sorted(actual.get("capability_ids") or []) != sorted(
            expected.get("capability_ids") or []
        ):
            issues.append(
                {
                    "reason": "historical_reference_capability_ids_mismatch",
                    "path": path_text,
                    "expected": sorted(expected.get("capability_ids") or []),
                    "actual": sorted(actual.get("capability_ids") or []),
                }
            )
    overlap = set(declared_index) & set(declared_hist_index)
    if overlap:
        for path_text in sorted(overlap):
            issues.append({"reason": "historical_reference_also_current", "path": path_text})

    for capability in source_data.get("capabilities") or []:
        if not isinstance(capability, dict) or capability.get("status") != "pass":
            continue
        partitioned = partition_capability_evidence(root, capability)
        if not partitioned["active_evidence"]:
            issues.append(
                {
                    "reason": "source_pass_without_active_evidence",
                    "capability_id": capability.get("id"),
                    "historical_evidence": partitioned["historical_evidence"],
                    "missing_evidence": partitioned["missing_evidence"],
                }
            )
        historical_in_active = [
            str(path)
            for path in (capability.get("evidence") or [])
            if is_historical_evidence_path(str(path), root)
        ]
        if historical_in_active:
            issues.append(
                {
                    "reason": "source_pass_lists_historical_as_current_evidence",
                    "capability_id": capability.get("id"),
                    "paths": historical_in_active,
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "agentlab_capability_current_evidence_chain_verification",
        "status": "pass" if not issues else "fail",
        "chain_path": str(path.relative_to(root)).replace("\\", "/") if path.is_relative_to(root) else str(path),
        "chain_id": loaded.get("chain_id"),
        "current_evidence_count": len(declared_active),
        "historical_reference_count": len(loaded.get("historical_references") or []),
        "aggregate_digest": declared_aggregate,
        "issues": issues,
    }


def write_capability_current_evidence_chain(
    root: Path,
    out: Path | None = None,
    *,
    capability_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate and write an evidence chain YAML via atomic I/O.

    When the fixed canonical source report exists on disk, the chain is rebuilt
    from that file so verification cannot diverge from sanitized on-disk content.
    """
    root = root.resolve()
    out_path = out or chain_path(root)
    out_path = out_path if out_path.is_absolute() else root / out_path
    source_abs = source_report_path(root)
    if source_abs.is_file() and not source_abs.is_symlink():
        chain = build_capability_current_evidence_chain(root)
    else:
        chain = build_capability_current_evidence_chain(
            root, capability_report=capability_report
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_path, dump_report_yaml(chain, root), encoding="utf-8")
    return chain


def is_canonical_acceptance_report_path(root: Path, out: Path) -> bool:
    """True when ``out`` is the fixed canonical capability acceptance report."""
    root = root.resolve()
    target = out if out.is_absolute() else root / out
    try:
        return target.resolve() == source_report_path(root)
    except OSError:
        return False
