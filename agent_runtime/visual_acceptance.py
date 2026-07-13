"""Deterministic, candidate-only visual acceptance decisions.

This module validates evidence already produced by other roles.  It never invokes a
model, generates media, mutates an asset, or promotes a candidate into production.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "visual_acceptance.yml"
_STATUS_KEYS = frozenset({"status", "verdict", "auth_status", "authentication_status"})


@dataclass(frozen=True)
class VisualAcceptancePolicy:
    minimum_size_bytes: int
    restrict_paths_to_workspace: bool
    required_receipt_fields: tuple[str, ...]
    require_nonempty_prompt_parameters: bool
    allow_empty_reference_assets: bool
    required_observer_fields: tuple[str, ...]
    require_distinct_observer_session_id: bool
    media_requirements: dict[str, tuple[str, ...]]
    required_review_roles: tuple[str, ...]
    required_reviewer_fields: tuple[str, ...]
    require_review_asset_binding: bool
    require_distinct_reviewer_ids: bool
    require_distinct_backend_model_pairs: bool
    forbid_producer_identity_backend_or_model: bool
    required_dimensions: tuple[str, ...]
    required_dimensions_by_role: dict[str, tuple[str, ...]]
    required_checks_by_role: dict[str, tuple[str, ...]]
    require_dimension_evidence: bool
    require_check_evidence: bool
    passing_verdict: str
    terminal_review_status: str
    blocking_verdicts: frozenset[str]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisualAcceptancePolicy":
        data = raw.get("visual_acceptance", raw)
        if not isinstance(data, Mapping):
            raise ValueError("visual_acceptance policy must be a mapping")

        assets = _mapping(data.get("assets"))
        receipt = _mapping(data.get("generation_receipt"))
        observer = _mapping(data.get("observer_evidence"))
        review = _mapping(data.get("review"))
        verdicts = _mapping(data.get("verdicts"))
        raw_media = _mapping(observer.get("media_requirements"))
        media_requirements: dict[str, tuple[str, ...]] = {}
        for media_type, requirements in raw_media.items():
            requirement_mapping = _mapping(requirements)
            media_requirements[str(media_type).lower()] = _strings(
                requirement_mapping.get("required_locators")
            )

        required_roles = _strings(review.get("required_roles"))
        legacy_dimensions = _strings(review.get("required_dimensions"))
        raw_dimensions_by_role = _mapping(review.get("required_dimensions_by_role"))
        required_dimensions_by_role = {
            str(role): _strings(dimensions)
            for role, dimensions in raw_dimensions_by_role.items()
        }
        if not required_dimensions_by_role:
            required_dimensions_by_role = {
                role: legacy_dimensions for role in required_roles
            }
        ordered_dimensions = tuple(
            dict.fromkeys(
                dimension
                for dimensions in required_dimensions_by_role.values()
                for dimension in dimensions
            )
        ) or legacy_dimensions
        required_checks_by_role = {
            str(role): _strings(checks)
            for role, checks in _mapping(review.get("required_checks_by_role")).items()
        }

        return cls(
            minimum_size_bytes=max(0, _integer(assets.get("minimum_size_bytes"), default=1)),
            restrict_paths_to_workspace=assets.get("restrict_paths_to_workspace") is not False,
            required_receipt_fields=_strings(receipt.get("required_fields")),
            require_nonempty_prompt_parameters=(
                receipt.get("require_nonempty_prompt_parameters") is not False
            ),
            allow_empty_reference_assets=receipt.get("allow_empty_reference_assets") is True,
            required_observer_fields=_strings(observer.get("required_observer_fields")),
            require_distinct_observer_session_id=(
                observer.get("require_distinct_session_id") is not False
            ),
            media_requirements=media_requirements,
            required_review_roles=required_roles,
            required_reviewer_fields=_strings(review.get("required_reviewer_fields")),
            require_review_asset_binding=review.get("require_asset_binding") is not False,
            require_distinct_reviewer_ids=review.get("require_distinct_reviewer_ids") is not False,
            require_distinct_backend_model_pairs=(
                review.get("require_distinct_backend_model_pairs") is not False
            ),
            forbid_producer_identity_backend_or_model=(
                review.get("forbid_producer_identity_backend_or_model") is not False
            ),
            required_dimensions=ordered_dimensions,
            required_dimensions_by_role=required_dimensions_by_role,
            required_checks_by_role=required_checks_by_role,
            require_dimension_evidence=review.get("require_dimension_evidence") is not False,
            require_check_evidence=review.get("require_check_evidence") is not False,
            passing_verdict=_text(verdicts.get("passing")) or "pass",
            terminal_review_status=_text(verdicts.get("terminal_review_status")) or "complete",
            blocking_verdicts=frozenset(value.lower() for value in _strings(verdicts.get("blocking"))),
        )


class _Issues:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, code: str, path: str, message: str) -> None:
        key = (code, path)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append({"code": code, "path": path, "message": message})

    def has_prefix(self, prefix: str) -> bool:
        return any(item["code"].startswith(prefix) for item in self.items)


def load_visual_acceptance_policy(path: Path | None = None) -> VisualAcceptancePolicy:
    """Load the standalone policy without depending on the global config loader."""

    policy_path = path or DEFAULT_POLICY_PATH
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    return VisualAcceptancePolicy.from_mapping(data)


def evaluate_visual_candidate(
    candidate: Mapping[str, Any],
    *,
    workspace: Path,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic, machine-readable acceptance decision.

    A passing result is only eligible for a separate promotion gate.  This function
    deliberately has no write path other than reading candidate and reference assets.
    """

    policy = load_visual_acceptance_policy(policy_path)
    issues = _Issues()
    root = workspace.resolve()

    if candidate.get("candidate_only") is not True:
        issues.add(
            "boundary.candidate_only_required",
            "candidate_only",
            "visual acceptance only evaluates candidate-only artifacts",
        )

    asset = _mapping(candidate.get("asset"))
    media_type = _text(asset.get("media_type")).lower()
    verified_asset = _verify_asset_descriptor(
        asset,
        workspace=root,
        policy=policy,
        issues=issues,
        path="asset",
    )
    if media_type not in policy.media_requirements:
        issues.add(
            "asset.unsupported_media_type",
            "asset.media_type",
            f"unsupported media type: {media_type or '<missing>'}",
        )

    receipt = _mapping(candidate.get("generation_receipt"))
    _validate_generation_receipt(receipt, root, policy, issues)

    observer = _mapping(candidate.get("observer_evidence"))
    observer_identity = _validate_observer_evidence(
        observer,
        asset=asset,
        verified_asset=verified_asset,
        media_type=media_type,
        workspace=root,
        policy=policy,
        issues=issues,
    )

    reviews = candidate.get("reviews")
    review_rows = list(reviews) if _is_sequence(reviews) else []
    if not _is_sequence(reviews):
        issues.add("review.list_required", "reviews", "reviews must be a list")
    review_roles, dimensions = _validate_reviews(
        review_rows,
        receipt,
        observer_identity,
        asset,
        verified_asset,
        root,
        policy,
        issues,
    )

    _find_unresolved_statuses(candidate, policy.blocking_verdicts, issues)

    accepted = not issues.items
    checks = {
        "asset_integrity": not issues.has_prefix("asset."),
        "generation_receipt": not issues.has_prefix("receipt."),
        "observer_evidence": not issues.has_prefix("observer."),
        "review_independence": not issues.has_prefix("review."),
        "four_dimension_verdict": not issues.has_prefix("dimension."),
        "verification_evidence": not issues.has_prefix("verification."),
        "candidate_boundary": not issues.has_prefix("boundary."),
        "resolved_statuses": not issues.has_prefix("status."),
    }

    return {
        "schema_version": "visual-acceptance-decision/v1",
        "candidate_id": _text(candidate.get("candidate_id")),
        "status": "accepted_candidate" if accepted else "blocked",
        "candidate_only": True,
        "promotion": {
            "eligible": accepted,
            "performed": False,
            "requires_external_gate": True,
        },
        "asset": {
            "path": _text(asset.get("path")),
            "media_type": media_type,
            "sha256": verified_asset.get("sha256"),
            "size_bytes": verified_asset.get("size_bytes"),
            "verified": bool(verified_asset.get("verified")),
        },
        "review_roles": review_roles,
        "dimensions": dimensions,
        "checks": [
            {"id": check_id, "status": "pass" if passed else "blocked"}
            for check_id, passed in checks.items()
        ],
        "blocking_reasons": issues.items,
    }


def _validate_generation_receipt(
    receipt: Mapping[str, Any],
    workspace: Path,
    policy: VisualAcceptancePolicy,
    issues: _Issues,
) -> None:
    if not receipt:
        issues.add("receipt.required", "generation_receipt", "generation receipt is required")
    for field in policy.required_receipt_fields:
        if field not in receipt:
            issues.add(
                "receipt.field_missing",
                f"generation_receipt.{field}",
                f"generation receipt field is required: {field}",
            )

    producer = _mapping(receipt.get("producer"))
    for field in ("role", "id"):
        if not _text(producer.get(field)):
            issues.add(
                "receipt.producer_field_missing",
                f"generation_receipt.producer.{field}",
                f"producer {field} is required",
            )
    for field in ("backend", "model"):
        if not _text(receipt.get(field)):
            issues.add(
                "receipt.field_empty",
                f"generation_receipt.{field}",
                f"generation receipt {field} must be non-empty",
            )

    prompt_parameters = receipt.get("prompt_parameters")
    if not isinstance(prompt_parameters, Mapping) or (
        policy.require_nonempty_prompt_parameters and not prompt_parameters
    ):
        issues.add(
            "receipt.prompt_parameters_invalid",
            "generation_receipt.prompt_parameters",
            "prompt parameters must be a non-empty mapping",
        )

    references = receipt.get("reference_assets")
    if not _is_sequence(references):
        issues.add(
            "receipt.reference_assets_invalid",
            "generation_receipt.reference_assets",
            "reference assets must be a list, even when empty",
        )
        return
    if not references and not policy.allow_empty_reference_assets:
        issues.add(
            "receipt.reference_assets_empty",
            "generation_receipt.reference_assets",
            "at least one reference asset is required",
        )
    for index, reference in enumerate(references):
        _verify_asset_descriptor(
            _mapping(reference),
            workspace=workspace,
            policy=policy,
            issues=issues,
            path=f"generation_receipt.reference_assets[{index}]",
            code_prefix="receipt.reference_asset",
        )


def _validate_observer_evidence(
    observer: Mapping[str, Any],
    *,
    asset: Mapping[str, Any],
    verified_asset: Mapping[str, Any],
    media_type: str,
    workspace: Path,
    policy: VisualAcceptancePolicy,
    issues: _Issues,
) -> Mapping[str, Any]:
    if not observer:
        issues.add("observer.required", "observer_evidence", "observer evidence is required")
    observer_identity = _mapping(observer.get("observer"))
    for field in policy.required_observer_fields:
        if not _text(observer_identity.get(field)):
            issues.add(
                "observer.identity_field_missing",
                f"observer_evidence.observer.{field}",
                f"observer {field} is required",
            )

    bound_asset = _mapping(observer.get("asset"))
    candidate_path = _resolve_asset_path(_text(asset.get("path")), workspace)
    observer_path = _resolve_asset_path(_text(bound_asset.get("path")), workspace)
    if candidate_path is None or observer_path is None or candidate_path != observer_path:
        issues.add(
            "observer.asset_path_mismatch",
            "observer_evidence.asset.path",
            "observer evidence must bind the same candidate asset path",
        )

    observed_hash = _text(bound_asset.get("sha256")).lower()
    actual_hash = _text(verified_asset.get("sha256")).lower()
    if not observed_hash or not actual_hash or observed_hash != actual_hash:
        issues.add(
            "observer.asset_hash_mismatch",
            "observer_evidence.asset.sha256",
            "observer evidence must bind the verified candidate sha256",
        )
    observed_size = _strict_int(bound_asset.get("size_bytes"))
    actual_size = _strict_int(verified_asset.get("size_bytes"))
    if observed_size is None or actual_size is None or observed_size != actual_size:
        issues.add(
            "observer.asset_size_mismatch",
            "observer_evidence.asset.size_bytes",
            "observer evidence must bind the verified candidate size",
        )

    for locator in policy.media_requirements.get(media_type, ()):
        locator_rows = observer.get(locator)
        path = f"observer_evidence.{locator}"
        if not _is_sequence(locator_rows) or not locator_rows:
            issues.add(
                "observer.locator_missing",
                path,
                f"{media_type} observer evidence requires non-empty {locator}",
            )
            continue
        for index, row in enumerate(locator_rows):
            locator_mapping = _mapping(row)
            locator_path = f"{path}[{index}]"
            if not locator_mapping:
                issues.add("observer.locator_invalid", locator_path, "locator must be a mapping")
                continue
            if locator == "keyframes":
                if media_type == "video" and _number(locator_mapping.get("timestamp_seconds")) is None:
                    issues.add(
                        "observer.keyframe_timestamp_missing",
                        f"{locator_path}.timestamp_seconds",
                        "video keyframes require a numeric timestamp_seconds",
                    )
            elif locator == "timestamps":
                _validate_timestamp(locator_mapping, locator_path, issues)
            elif locator == "pages":
                page = _strict_int(locator_mapping.get("page"))
                if page is None or page < 1:
                    issues.add(
                        "observer.page_invalid",
                        f"{locator_path}.page",
                        "PDF page locators require a positive page number",
                    )
    return observer_identity


def _validate_timestamp(row: Mapping[str, Any], path: str, issues: _Issues) -> None:
    point = _number(row.get("timestamp_seconds"))
    start = _number(row.get("start_seconds"))
    end = _number(row.get("end_seconds"))
    if point is not None:
        if point < 0:
            issues.add("observer.timestamp_invalid", path, "timestamp must be non-negative")
        return
    if start is None or end is None or start < 0 or end < start:
        issues.add(
            "observer.timestamp_invalid",
            path,
            "timestamp locator requires a non-negative point or an ordered start/end range",
        )


def _validate_reviews(
    reviews: list[Any],
    receipt: Mapping[str, Any],
    observer: Mapping[str, Any],
    asset: Mapping[str, Any],
    verified_asset: Mapping[str, Any],
    workspace: Path,
    policy: VisualAcceptancePolicy,
    issues: _Issues,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    producer = _mapping(receipt.get("producer"))
    producer_role = _text(producer.get("role")).lower()
    producer_id = _text(producer.get("id")).lower()
    producer_backend = _text(receipt.get("backend")).lower()
    producer_model = _text(receipt.get("model")).lower()
    observer_id = _text(observer.get("id")).lower()
    if (
        policy.require_distinct_observer_session_id
        and observer_id
        and producer_id
        and observer_id == producer_id
    ):
        issues.add(
            "review.independence.observer_session_reused",
            "observer_evidence.observer.id",
            "observer session id must differ from the producer session id",
        )
    roles_seen: list[str] = []
    reviewer_ids: dict[str, str] = {}
    reviewer_pairs: dict[tuple[str, str], str] = {}
    dimension_rows: dict[str, dict[str, str]] = {
        dimension: {} for dimension in policy.required_dimensions
    }

    for index, raw_review in enumerate(reviews):
        review = _mapping(raw_review)
        base = f"reviews[{index}]"
        if not review:
            issues.add("review.invalid", base, "review must be a mapping")
            continue
        reviewer = _mapping(review.get("reviewer"))
        for field in policy.required_reviewer_fields:
            if not _text(reviewer.get(field)):
                issues.add(
                    "review.reviewer_field_missing",
                    f"{base}.reviewer.{field}",
                    f"reviewer {field} is required",
                )

        role = _text(reviewer.get("role"))
        reviewer_id = _text(reviewer.get("id"))
        backend = _text(reviewer.get("backend"))
        model = _text(reviewer.get("model"))
        if role:
            roles_seen.append(role)

        status = _text(review.get("status")).lower()
        if status != policy.terminal_review_status.lower():
            status_code = status if status in policy.blocking_verdicts else "unknown"
            issues.add(
                f"review.status.{status_code}",
                f"{base}.status",
                "review must have a complete terminal status",
            )

        if policy.require_review_asset_binding:
            bound_asset = _mapping(review.get("asset"))
            candidate_path = _resolve_asset_path(_text(asset.get("path")), workspace)
            review_path = _resolve_asset_path(_text(bound_asset.get("path")), workspace)
            if candidate_path is None or review_path is None or candidate_path != review_path:
                issues.add(
                    "review.asset_path_mismatch",
                    f"{base}.asset.path",
                    "review evidence must bind the exact candidate asset path",
                )
            review_hash = _text(bound_asset.get("sha256")).lower()
            actual_hash = _text(verified_asset.get("sha256")).lower()
            if not review_hash or not actual_hash or review_hash != actual_hash:
                issues.add(
                    "review.asset_hash_mismatch",
                    f"{base}.asset.sha256",
                    "review evidence must bind the verified candidate sha256",
                )
            review_size = _strict_int(bound_asset.get("size_bytes"))
            actual_size = _strict_int(verified_asset.get("size_bytes"))
            if review_size is None or actual_size is None or review_size != actual_size:
                issues.add(
                    "review.asset_size_mismatch",
                    f"{base}.asset.size_bytes",
                    "review evidence must bind the verified candidate size",
                )

        if policy.forbid_producer_identity_backend_or_model:
            collisions = []
            if producer_role and role.lower() == producer_role:
                collisions.append("role")
            if producer_id and reviewer_id.lower() == producer_id:
                collisions.append("identity")
            if producer_backend and backend.lower() == producer_backend:
                collisions.append("backend")
            if producer_model and model.lower() == producer_model:
                collisions.append("model")
            if collisions:
                issues.add(
                    "review.independence.producer_self_review",
                    f"{base}.reviewer",
                    "reviewer overlaps producer " + ", ".join(collisions),
                )

        if reviewer_id:
            normalized_id = reviewer_id.lower()
            if (
                policy.require_distinct_observer_session_id
                and observer_id
                and normalized_id == observer_id
            ):
                issues.add(
                    "review.independence.observer_session_reused",
                    f"{base}.reviewer.id",
                    "reviewer session id must differ from the observer session id",
                )
            if policy.require_distinct_reviewer_ids and normalized_id in reviewer_ids:
                issues.add(
                    "review.independence.duplicate_reviewer",
                    f"{base}.reviewer.id",
                    f"reviewer id already used by {reviewer_ids[normalized_id]}",
                )
            else:
                reviewer_ids[normalized_id] = role or base
        pair = (backend.lower(), model.lower())
        if all(pair):
            if policy.require_distinct_backend_model_pairs and pair in reviewer_pairs:
                issues.add(
                    "review.independence.duplicate_backend_model",
                    f"{base}.reviewer",
                    f"backend/model pair already used by {reviewer_pairs[pair]}",
                )
            else:
                reviewer_pairs[pair] = role or base

        dimensions = _mapping(review.get("dimensions"))
        role_dimensions = policy.required_dimensions_by_role.get(
            role,
            policy.required_dimensions,
        )
        for dimension in role_dimensions:
            dimension_path = f"{base}.dimensions.{dimension}"
            assessment = _mapping(dimensions.get(dimension))
            raw_verdict = _text(assessment.get("verdict")).lower()
            verdict = raw_verdict or "missing"
            dimension_rows[dimension][role or base] = verdict
            if verdict != policy.passing_verdict.lower():
                code_verdict = verdict if verdict in policy.blocking_verdicts else "unknown"
                issues.add(
                    f"dimension.{dimension}.{code_verdict}",
                    f"{dimension_path}.verdict",
                    f"{dimension} requires an explicit passing verdict",
                )
            evidence = assessment.get("evidence")
            if policy.require_dimension_evidence and not _nonempty_evidence(evidence):
                issues.add(
                    f"dimension.{dimension}.evidence_missing",
                    f"{dimension_path}.evidence",
                    f"{dimension} verdict requires evidence",
                )

        checks = _mapping(review.get("checks"))
        for check in policy.required_checks_by_role.get(role, ()):
            check_path = f"{base}.checks.{check}"
            assessment = _mapping(checks.get(check))
            raw_verdict = _text(assessment.get("verdict")).lower()
            verdict = raw_verdict or "missing"
            if verdict != policy.passing_verdict.lower():
                code_verdict = verdict if verdict in policy.blocking_verdicts else "unknown"
                issues.add(
                    f"verification.{check}.{code_verdict}",
                    f"{check_path}.verdict",
                    f"{role} must explicitly pass verification check {check}",
                )
            evidence = assessment.get("evidence")
            if policy.require_check_evidence and not _nonempty_evidence(evidence):
                issues.add(
                    f"verification.{check}.evidence_missing",
                    f"{check_path}.evidence",
                    f"{role} verification check {check} requires evidence",
                )

    for role in policy.required_review_roles:
        if role not in roles_seen:
            issues.add(
                "review.required_role_missing",
                "reviews",
                f"independent review role is required: {role}",
            )

    dimensions = {
        dimension: {
            "status": "blocked" if issues.has_prefix(f"dimension.{dimension}.") else "pass",
            "verdicts_by_role": verdicts,
        }
        for dimension, verdicts in dimension_rows.items()
    }
    return roles_seen, dimensions


def _verify_asset_descriptor(
    descriptor: Mapping[str, Any],
    *,
    workspace: Path,
    policy: VisualAcceptancePolicy,
    issues: _Issues,
    path: str,
    code_prefix: str = "asset",
) -> dict[str, Any]:
    raw_path = _text(descriptor.get("path"))
    resolved = _resolve_asset_path(raw_path, workspace)
    if not raw_path:
        issues.add(f"{code_prefix}.path_missing", f"{path}.path", "asset path is required")
        return {"verified": False}
    if resolved is None:
        issues.add(f"{code_prefix}.path_invalid", f"{path}.path", "asset path is invalid")
        return {"verified": False}
    if policy.restrict_paths_to_workspace and not _is_within(resolved, workspace):
        issues.add(
            f"{code_prefix}.path_outside_workspace",
            f"{path}.path",
            "asset path must stay inside the acceptance workspace",
        )
        return {"verified": False}
    if not resolved.exists() or not resolved.is_file():
        issues.add(f"{code_prefix}.missing", f"{path}.path", "asset file does not exist")
        return {"verified": False}

    actual_size = resolved.stat().st_size
    actual_hash = _sha256(resolved)
    declared_hash = _text(descriptor.get("sha256")).lower()
    declared_size = _strict_int(descriptor.get("size_bytes"))
    valid = True
    if actual_size < policy.minimum_size_bytes:
        issues.add(
            f"{code_prefix}.empty",
            f"{path}.size_bytes",
            f"asset must be at least {policy.minimum_size_bytes} byte(s)",
        )
        valid = False
    if len(declared_hash) != 64 or any(char not in "0123456789abcdef" for char in declared_hash):
        issues.add(
            f"{code_prefix}.sha256_invalid",
            f"{path}.sha256",
            "asset sha256 must be a 64-character lowercase hex digest",
        )
        valid = False
    elif declared_hash != actual_hash:
        issues.add(
            f"{code_prefix}.sha256_mismatch",
            f"{path}.sha256",
            "declared sha256 does not match the asset bytes",
        )
        valid = False
    if declared_size is None:
        issues.add(
            f"{code_prefix}.size_missing",
            f"{path}.size_bytes",
            "asset size_bytes must be an integer",
        )
        valid = False
    elif declared_size != actual_size:
        issues.add(
            f"{code_prefix}.size_mismatch",
            f"{path}.size_bytes",
            "declared size_bytes does not match the asset",
        )
        valid = False
    return {
        "path": str(resolved),
        "sha256": actual_hash,
        "size_bytes": actual_size,
        "verified": valid,
    }


def _find_unresolved_statuses(
    value: Any,
    blocking: frozenset[str],
    issues: _Issues,
    path: str = "candidate",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in _STATUS_KEYS:
                status = _text(child).lower()
                if status in blocking:
                    issues.add(
                        f"status.{status}",
                        child_path,
                        f"unresolved status blocks promotion eligibility: {status}",
                    )
            _find_unresolved_statuses(child, blocking, issues, child_path)
    elif _is_sequence(value):
        for index, child in enumerate(value):
            _find_unresolved_statuses(child, blocking, issues, f"{path}[{index}]")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_asset_path(raw_path: str, workspace: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    try:
        return (path if path.is_absolute() else workspace / path).resolve()
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _strings(value: Any) -> tuple[str, ...]:
    if not _is_sequence(value):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: Any, *, default: int) -> int:
    parsed = _strict_int(value)
    return default if parsed is None else parsed


def _strict_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _nonempty_evidence(value: Any) -> bool:
    if not _is_sequence(value) or not value:
        return False
    return all(bool(item) if isinstance(item, Mapping) else bool(_text(item)) for item in value)
