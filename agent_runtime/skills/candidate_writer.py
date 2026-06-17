"""R5: Candidate Writer — Serialise, Load, and Merge Skill Candidates.

Provides YAML-based persistence for discovery candidate dicts.  Supports:
- Writing a list of candidates to a YAML file.
- Loading candidates back from YAML.
- Merging two candidate lists with deduplication by ``candidate_id``.

This module never executes, enables, or promotes any candidate.  It is a
pure data-layer helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml
except ImportError:  # pragma: no cover — allow flat-import in tests
    from atomic_io import atomic_write_yaml, safe_read_yaml  # type: ignore[no-redef]


# ── Schema versioning ────────────────────────────────────────────────────────

_SCHEMA_VERSION = 1


def _wrap_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap a candidate list in the top-level envelope for YAML output."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "candidates": list(candidates),
    }


# ── Public API ───────────────────────────────────────────────────────────────


def write_candidates(
    candidates: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Write *candidates* to *output_path* as YAML.

    The output file is wrapped in an envelope that includes a
    ``schema_version`` field for forward compatibility.

    Parameters
    ----------
    candidates:
        List of candidate dicts (as produced by ``discover_candidates``).
    output_path:
        Destination file path.  Parent directories are created as needed.

    Returns
    -------
    Path
        The resolved *output_path* that was written.
    """
    output_path = Path(output_path)
    envelope = _wrap_candidates(candidates)
    atomic_write_yaml(output_path, envelope)
    return output_path


def load_candidates(path: Path) -> list[dict[str, Any]]:
    """Load candidate dicts from a YAML file previously written by ``write_candidates``.

    Handles both the wrapped envelope format (with ``candidates`` key) and a
    bare list at the top level for convenience.

    Parameters
    ----------
    path:
        Path to the YAML file.

    Returns
    -------
    list[dict]
        The candidate dicts, or an empty list when the file is missing,
        empty, or malformed.
    """
    path = Path(path)
    data = safe_read_yaml(path, default=None)
    if data is None:
        return []

    # Wrapped envelope format.
    if isinstance(data, dict):
        candidates = data.get("candidates")
        if isinstance(candidates, list):
            return [c for c in candidates if isinstance(c, dict)]
        return []

    # Bare list format (legacy / convenience).
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]

    return []


def merge_candidates(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge two candidate lists, deduplicating by ``candidate_id``.

    When a ``candidate_id`` appears in both *existing* and *new*, the
    **existing** entry is kept (it may have been annotated or partially
    reviewed) and the new entry's ``source_evidence`` is merged in.

    Parameters
    ----------
    existing:
        Previously known candidates.
    new:
        Freshly discovered candidates.

    Returns
    -------
    list[dict]
        Merged and deduplicated candidate list, preserving insertion order
        (existing first, then new).
    """
    merged: dict[str, dict[str, Any]] = {}

    # Index existing candidates first — they take precedence.
    for candidate in existing:
        cid = candidate.get("candidate_id", "")
        if cid:
            merged[cid] = candidate

    # Layer in new candidates.
    for candidate in new:
        cid = candidate.get("candidate_id", "")
        if not cid:
            continue
        if cid in merged:
            # Merge source_evidence from new into existing.
            existing_evidence_keys = {
                (e.get("path"), e.get("content_hash"))
                for e in merged[cid].get("source_evidence", [])
            }
            for ev in candidate.get("source_evidence", []):
                key = (ev.get("path"), ev.get("content_hash"))
                if key not in existing_evidence_keys:
                    merged[cid].setdefault("source_evidence", []).append(ev)
                    existing_evidence_keys.add(key)
        else:
            merged[cid] = candidate

    return list(merged.values())
