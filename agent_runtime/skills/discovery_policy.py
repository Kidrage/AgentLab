"""R5: Skill Discovery Policy — Loading and Validation.

Provides policy defaults for the discovery pipeline and validates candidate
dicts against the expected schema.  This module is intentionally conservative:
all automatic actions (network, import, promote) default to disabled.

The policy file (YAML) is optional.  When absent, safe defaults are returned
that prevent any network access, auto-import, or auto-promotion.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

try:
    from agent_runtime.atomic_io import safe_read_yaml
except ImportError:  # pragma: no cover — allow flat-import in tests
    from atomic_io import safe_read_yaml  # type: ignore[no-redef]


# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "allow_network": False,
    "auto_import": False,
    "auto_promote": False,
    "max_candidates_per_scan": 50,
    "scanners": [
        "scripts",
        "acceptance_reports",
        "recovery_feedback",
        "docs",
    ],
    "safety": {
        "always_require_human_review": True,
        "never_execute_external_code": True,
        "never_copy_external_source": True,
    },
}


# ── Policy Loading ───────────────────────────────────────────────────────────


def load_discovery_policy(config_path: Path | None = None) -> dict[str, Any]:
    """Load a discovery policy from a YAML file, or return safe defaults.

    Parameters
    ----------
    config_path:
        Optional path to a YAML policy file.  When ``None`` or the file
        does not exist, the built-in defaults are returned.

    Returns
    -------
    dict
        A policy dict with at minimum the keys from ``_DEFAULT_POLICY``.
        User-provided values are merged on top of defaults.
    """
    policy = copy.deepcopy(_DEFAULT_POLICY)

    if config_path is not None:
        user_policy = safe_read_yaml(config_path, default=None)
        if isinstance(user_policy, dict):
            _merge_policy(policy, user_policy)

    return policy


_IMMUTABLE_KEYS = frozenset({"safety"})


def _merge_policy(
    base: dict[str, Any],
    overrides: dict[str, Any],
    *,
    _depth: int = 0,
) -> None:
    """Recursively merge *overrides* into *base* in place.

    Safety-related keys are immutable and are never overwritten regardless
    of nesting depth.
    """
    for key, value in overrides.items():
        # Safety block is entirely immutable.
        if key in _IMMUTABLE_KEYS:
            continue
        if key not in base:
            base[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge_policy(base[key], value, _depth=_depth + 1)
        else:
            base[key] = value


# ── Candidate Validation ─────────────────────────────────────────────────────

_REQUIRED_CANDIDATE_FIELDS = frozenset({
    "candidate_id",
    "title",
    "source_evidence",
    "proposed_capabilities",
    "suitable_task_types",
    "proposed_inputs",
    "proposed_outputs",
    "risk",
    "license",
    "lifecycle_status",
    "enabled",
    "promotion",
})

_VALID_LIFECYCLE_STATUSES = frozenset({
    "candidate",
    "draft",
    "pending_review",
    "staging",
    "active",
    "disabled",
    "rejected",
    "deprecated",
})

_VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

_VALID_SOURCE_CATEGORIES = frozenset({
    "repo_files",
    "docs",
    "config",
    "skills",
    "tests",
    "scripts",
    "acceptance_runs",
    "task_runs",
    "recovery_history",
    "closure_feedback",
    "external_inventory",
    "project_brain",
    "web_snapshots",
})


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    """Validate a candidate dict against the discovery schema.

    Parameters
    ----------
    candidate:
        A candidate dict as produced by ``discover_candidates``.

    Returns
    -------
    list[str]
        A list of human-readable error strings.  An empty list means the
        candidate passes all validation checks.
    """
    errors: list[str] = []
    cid = candidate.get("candidate_id") or "<missing>"

    # ── Required fields ──────────────────────────────────────────────────

    missing = _REQUIRED_CANDIDATE_FIELDS - set(candidate.keys())
    if missing:
        errors.append(f"{cid}: missing required fields: {sorted(missing)}")
        # Short-circuit: remaining checks depend on these fields existing.
        return errors

    # ── candidate_id ─────────────────────────────────────────────────────

    if not isinstance(candidate["candidate_id"], str) or not candidate["candidate_id"].strip():
        errors.append(f"{cid}: candidate_id must be a non-empty string")

    # ── title ────────────────────────────────────────────────────────────

    if not isinstance(candidate["title"], str) or not candidate["title"].strip():
        errors.append(f"{cid}: title must be a non-empty string")

    # ── source_evidence ──────────────────────────────────────────────────

    evidence = candidate.get("source_evidence")
    if not isinstance(evidence, list) or len(evidence) == 0:
        errors.append(f"{cid}: source_evidence must be a non-empty list")
    else:
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errors.append(f"{cid}: source_evidence[{i}] must be a dict")
                continue
            for required_key in ("path", "source_category", "content_hash"):
                if required_key not in ev:
                    errors.append(
                        f"{cid}: source_evidence[{i}] missing '{required_key}'"
                    )
            cat = ev.get("source_category", "")
            if cat and cat not in _VALID_SOURCE_CATEGORIES:
                errors.append(
                    f"{cid}: source_evidence[{i}] has invalid source_category '{cat}'"
                )

    # ── list fields ──────────────────────────────────────────────────────

    for field_name in (
        "proposed_capabilities",
        "suitable_task_types",
        "proposed_inputs",
        "proposed_outputs",
    ):
        val = candidate.get(field_name)
        if not isinstance(val, list):
            errors.append(f"{cid}: {field_name} must be a list")

    # ── risk ─────────────────────────────────────────────────────────────

    risk = candidate.get("risk")
    if not isinstance(risk, dict):
        errors.append(f"{cid}: risk must be a dict")
    else:
        level = risk.get("level", "")
        if level not in _VALID_RISK_LEVELS:
            errors.append(f"{cid}: risk.level '{level}' is not valid")
        if not isinstance(risk.get("reasons"), list):
            errors.append(f"{cid}: risk.reasons must be a list")
        if risk.get("requires_approval") is not True:
            errors.append(f"{cid}: risk.requires_approval must be True")

    # ── license ──────────────────────────────────────────────────────────

    license_info = candidate.get("license")
    if not isinstance(license_info, dict):
        errors.append(f"{cid}: license must be a dict")
    else:
        if not isinstance(license_info.get("source"), str):
            errors.append(f"{cid}: license.source must be a string")
        if not isinstance(license_info.get("review_required"), bool):
            errors.append(f"{cid}: license.review_required must be a bool")

    # ── lifecycle_status ─────────────────────────────────────────────────

    status = candidate.get("lifecycle_status", "")
    if status != "candidate":
        errors.append(
            f"{cid}: lifecycle_status must be 'candidate' for discovery candidates, "
            f"got '{status}'"
        )

    # ── enabled ──────────────────────────────────────────────────────────

    if candidate.get("enabled") is not False:
        errors.append(f"{cid}: enabled must be False for discovery candidates")

    # ── promotion ────────────────────────────────────────────────────────

    promotion = candidate.get("promotion")
    if not isinstance(promotion, dict):
        errors.append(f"{cid}: promotion must be a dict")
    else:
        if promotion.get("requires_human_review") is not True:
            errors.append(f"{cid}: promotion.requires_human_review must be True")
        if promotion.get("requires_tests") is not True:
            errors.append(f"{cid}: promotion.requires_tests must be True")
        if promotion.get("requires_metadata_completion") is not True:
            errors.append(f"{cid}: promotion.requires_metadata_completion must be True")

    return errors
