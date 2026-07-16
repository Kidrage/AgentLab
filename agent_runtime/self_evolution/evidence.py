"""Capability-gap evidence aggregation and necessity gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
from typing import Any, Iterable, Mapping

import yaml

from agent_runtime.runtime_registry import RuntimeRegistry

from .models import ComponentManifest
from .role_catalog import RoleCatalog


def utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized(value: Any) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _flatten_scalars(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_scalars(item))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.extend(_flatten_scalars(item))
        return result
    return [str(value)] if value is not None else []


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def gap_fingerprint(
    capability_id: str,
    *,
    input_contract: Iterable[str] = (),
    output_contract: Iterable[str] = (),
    permission_class: str = "read_only",
) -> str:
    payload = {
        "capability_id": str(capability_id).strip().casefold(),
        "input_contract": sorted({str(item).strip() for item in input_contract if str(item).strip()}),
        "output_contract": sorted({str(item).strip() for item in output_contract if str(item).strip()}),
        "permission_class": str(permission_class).strip().casefold(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GapObservation:
    task_id: str
    capability_id: str
    reason: str
    observed_at: str
    fingerprint: str
    explicit_user_request: bool = False
    input_contract: tuple[str, ...] = ()
    output_contract: tuple[str, ...] = ()
    permission_class: str = "read_only"
    required_capabilities: tuple[str, ...] = ()
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "observation_type": "agentlab_capability_gap",
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "reason": self.reason,
            "observed_at": self.observed_at,
            "fingerprint": self.fingerprint,
            "explicit_user_request": self.explicit_user_request,
            "input_contract": list(self.input_contract),
            "output_contract": list(self.output_contract),
            "permission_class": self.permission_class,
            "required_capabilities": list(self.required_capabilities),
        }


def build_observation(
    *,
    task_id: str,
    capability_id: str,
    reason: str,
    explicit_user_request: bool = False,
    input_contract: Iterable[str] = (),
    output_contract: Iterable[str] = (),
    permission_class: str = "read_only",
    required_capabilities: Iterable[str] = (),
    observed_at: datetime | None = None,
) -> GapObservation:
    inputs = tuple(str(item) for item in input_contract)
    outputs = tuple(str(item) for item in output_contract)
    return GapObservation(
        task_id=str(task_id),
        capability_id=str(capability_id),
        reason=str(reason),
        observed_at=utc_timestamp(observed_at),
        fingerprint=gap_fingerprint(
            capability_id,
            input_contract=inputs,
            output_contract=outputs,
            permission_class=permission_class,
        ),
        explicit_user_request=bool(explicit_user_request),
        input_contract=inputs,
        output_contract=outputs,
        permission_class=str(permission_class),
        required_capabilities=tuple(str(item) for item in required_capabilities),
    )


def write_observation(observation: GapObservation, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(observation.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def observation_from_mapping(
    data: Mapping[str, Any],
    *,
    source_path: str | None = None,
) -> GapObservation:
    if not isinstance(data, Mapping):
        raise ValueError(f"gap observation must be a mapping: {source_path or '<memory>'}")
    capability_id = str(data.get("capability_id") or data.get("required_capability") or "")
    input_contract = tuple(str(item) for item in data.get("input_contract") or [])
    output_contract = tuple(str(item) for item in data.get("output_contract") or [])
    permission_class = str(data.get("permission_class") or "read_only")
    expected_fingerprint = gap_fingerprint(
        capability_id,
        input_contract=input_contract,
        output_contract=output_contract,
        permission_class=permission_class,
    )
    fingerprint = str(data.get("fingerprint") or "") or expected_fingerprint
    if fingerprint != expected_fingerprint:
        raise ValueError(
            "gap observation fingerprint does not match its contract: "
            f"{source_path or '<memory>'}"
        )
    task_id = str(data.get("task_id") or "").strip()
    reason = str(data.get("reason") or data.get("missing_backend_reason") or "").strip()
    observed_at = str(data.get("observed_at") or "")
    if not task_id or not capability_id.strip() or not reason:
        raise ValueError(
            "gap observation is missing task_id, capability_id, or reason: "
            f"{source_path or '<memory>'}"
        )
    if _parse_timestamp(observed_at) is None:
        raise ValueError(
            "gap observation has an invalid observed_at timestamp: "
            f"{source_path or '<memory>'}"
        )
    explicit = data.get("explicit_user_request", False)
    if not isinstance(explicit, bool):
        raise ValueError(
            "gap observation explicit_user_request must be boolean: "
            f"{source_path or '<memory>'}"
        )
    return GapObservation(
        task_id=task_id,
        capability_id=capability_id,
        reason=reason,
        observed_at=observed_at,
        fingerprint=fingerprint,
        explicit_user_request=explicit,
        input_contract=input_contract,
        output_contract=output_contract,
        permission_class=permission_class,
        required_capabilities=tuple(str(item) for item in data.get("required_capabilities") or []),
        source_path=source_path,
    )


def load_observation(path: Path) -> GapObservation:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"gap observation must be a mapping: {path}")
    return observation_from_mapping(data, source_path=str(path))


def evaluate_gap_eligibility(
    observations: Iterable[GapObservation],
    *,
    manifest: ComponentManifest,
    catalog: RoleCatalog,
    now: datetime | None = None,
    window_days: int = 30,
    minimum_unique_tasks: int = 2,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(days=window_days)
    items = list(observations)
    fingerprints = {item.fingerprint for item in items}
    if len(fingerprints) > 1:
        return {
            "status": "blocked",
            "reason": "evidence_fingerprints_do_not_match",
            "fingerprints": sorted(fingerprints),
        }
    recent = [
        item
        for item in items
        if (parsed := _parse_timestamp(item.observed_at)) is not None and parsed >= cutoff
    ]
    unique_tasks = sorted({item.task_id for item in recent if item.task_id})
    explicit = any(item.explicit_user_request for item in recent)
    trigger_satisfied = explicit or len(unique_tasks) >= minimum_unique_tasks

    required = set()
    for item in recent:
        required.update(item.required_capabilities)
    if manifest.kind == "agent_role":
        requirements = manifest.spec.get("role_requirements") or {}
        required.update(str(item) for item in requirements.get("required_capabilities") or [])
    compositions: list[dict[str, Any]] = []
    for role in catalog.roles():
        if role.display_name == manifest.display_name and manifest.replaces_legacy:
            continue
        covered = set(role.required_capabilities)
        if required and required.issubset(covered):
            compositions.append(
                {
                    "kind": "existing_role",
                    "role": role.display_name,
                    "covered_capabilities": sorted(required),
                }
            )
    capability_ids = {_normalized(item.capability_id) for item in recent}
    skills = _read_yaml(catalog.root / "skills" / "registry.yml").get("skills") or []
    for skill in skills:
        if not isinstance(skill, Mapping) or str(skill.get("status")) != "active":
            continue
        declared = {
            _normalized(item)
            for item in [
                skill.get("skill_id"),
                skill.get("skill_name"),
                skill.get("name"),
                *(skill.get("applies_to") or []),
            ]
        }
        matches = sorted(capability_ids & declared)
        if matches:
            compositions.append(
                {
                    "kind": "existing_skill",
                    "skill": skill.get("skill_name") or skill.get("name"),
                    "matched_capabilities": matches,
                }
            )
    for relative_path, kind in (
        ("config/production_packs.yml", "existing_production_pack"),
        ("config/domain_route_packs.yml", "existing_route_pack"),
    ):
        declared = {_normalized(item) for item in _flatten_scalars(_read_yaml(catalog.root / relative_path))}
        matches = sorted(capability_ids & declared)
        if matches:
            compositions.append(
                {
                    "kind": kind,
                    "source": relative_path,
                    "matched_capabilities": matches,
                }
            )
    worker_binding = manifest.spec.get("worker_binding") or {}
    allowed_workers = tuple(
        str(item) for item in worker_binding.get("allowed_workers") or []
    )
    runtime_registry = RuntimeRegistry.load(catalog.root)
    reusable_runtime_routes = runtime_registry.whitelisted_route_templates(
        allowed_workers=allowed_workers,
    )
    composition_checks = {
        "existing_role_plus_skill": {
            "status": "checked",
            "candidates": [
                item
                for item in compositions
                if item.get("kind") in {"existing_role", "existing_skill"}
            ],
        },
        "existing_route_or_production_pack": {
            "status": "checked",
            "candidates": [
                item
                for item in compositions
                if item.get("kind")
                in {"existing_route_pack", "existing_production_pack"}
            ],
        },
        "existing_worker_and_runtime_route": {
            "status": "checked",
            "allowed_workers": list(allowed_workers),
            "reusable_route_templates": reusable_runtime_routes,
            "satisfies_missing_role_governance": False,
            "disposition": (
                "reuse_as_execution_substrate"
                if reusable_runtime_routes
                else "no_registered_execution_substrate"
            ),
        },
    }
    if compositions:
        return {
            "status": "blocked",
            "reason": "existing_component_composition_available",
            "explicit_user_request": explicit,
            "unique_task_ids": unique_tasks,
            "composition_candidates": compositions,
            "composition_checks": composition_checks,
        }
    return {
        "status": "eligible" if trigger_satisfied else "observed",
        "reason": (
            "explicit_user_request"
            if explicit
            else "repeated_independent_gap"
            if trigger_satisfied
            else "insufficient_independent_evidence"
        ),
        "explicit_user_request": explicit,
        "unique_task_ids": unique_tasks,
        "minimum_unique_tasks": minimum_unique_tasks,
        "window_days": window_days,
        "fingerprint": next(iter(fingerprints), None),
        "composition_candidates": [],
        "composition_checks": composition_checks,
    }
