"""Run-local model capacity governance.

The public seam is :class:`ModelCapacity`: callers report outcomes, request an
approved route, or run a policy-declared safe probe.  Provider text parsing,
shared-pool circuit state, canary leases, and atomic persistence stay local to
this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from contextlib import contextmanager
import fcntl
import re
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from atomic_io import atomic_write_yaml, safe_read_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import atomic_write_yaml, safe_read_yaml


Clock = Callable[[], datetime]


class CapacityPolicyError(ValueError):
    """Raised when a route or fallback is not explicitly authorized by policy."""


class UnsafeCapacityProbeError(CapacityPolicyError):
    """Raised before executing a probe outside the hard-coded safe allowlist."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed)


def _headers(headers: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _message_reset(message: str, observed_at: datetime) -> datetime | None:
    match = re.search(
        r"\bresets?\s+in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\b",
        message,
        re.IGNORECASE,
    )
    if match and any(match.groups()):
        hours, minutes, seconds = (int(value or 0) for value in match.groups())
        return observed_at + timedelta(hours=hours, minutes=minutes, seconds=seconds)

    retry = re.search(
        r"\bretry[- ]after\s*:?\s*(\d+(?:\.\d+)?)\s*"
        r"(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)?\b",
        message,
        re.IGNORECASE,
    )
    if not retry:
        return None
    amount = float(retry.group(1))
    unit = (retry.group(2) or "s").lower()
    multiplier = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
    return observed_at + timedelta(seconds=amount * multiplier)


def _retry_after_reset(value: Any, observed_at: datetime) -> datetime | None:
    seconds = _number(value)
    if seconds is not None:
        return observed_at + timedelta(seconds=float(seconds))
    if value is None:
        return None
    try:
        return _as_utc(parsedate_to_datetime(str(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def _classify_failure(message: str, headers: Mapping[str, Any] | None = None) -> str:
    lowered = message.lower()
    if any(
        marker in lowered
        for marker in (
            "missing access_token",
            "missing access token",
            "login required",
            "logged out",
            "not logged in",
            "not authenticated",
            "authentication required",
            "authentication failed",
            "auth required",
            "auth_required",
            "unauthorized",
            "invalid token",
            "invalid_grant",
        )
    ):
        return "auth_missing"
    if any(
        marker in lowered
        for marker in (
            "quota exhausted",
            "quota exceeded",
            "usage limit reached",
            "weekly limit reached",
            "insufficient quota",
            "credits exhausted",
        )
    ):
        return "quota_exhausted"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if (
        "model" in lowered
        and any(
            marker in lowered
            for marker in (
                "not available",
                "unavailable",
                "not found",
                "unsupported",
                "unknown model",
            )
        )
    ):
        return "model_unavailable"
    if _retry_after_reset(_headers(headers).get("retry-after"), _utc_now()) is not None:
        return "rate_limited"
    return "unknown"


def _canonical_role(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


class ModelCapacity:
    """Govern shared subscription capacity through a small, persistent seam."""

    def __init__(self, policy: Mapping[str, Any], ledger_path: Path, *, clock: Clock = _utc_now):
        self.policy = dict(policy)
        self.ledger_path = Path(ledger_path)
        self.clock = clock

    def _load_ledger(self) -> dict[str, Any]:
        ledger = safe_read_yaml(self.ledger_path, default={}) or {}
        if not isinstance(ledger, dict):
            ledger = {}
        ledger.setdefault("schema_version", 1)
        for section in ("pools", "routes"):
            if not isinstance(ledger.get(section), dict):
                ledger[section] = {}
        return ledger

    def record_runtime_failure(
        self,
        runtime_route_id: str,
        *,
        pool_id: str,
        message: str,
        headers: Mapping[str, Any] | None = None,
        attempt_id: str,
    ) -> dict[str, Any]:
        """Record a dynamic-route failure without selecting a replacement route."""

        if pool_id not in self.policy.get("pools", {}):
            raise CapacityPolicyError(f"unknown capacity pool: {pool_id}")
        failure_class = _classify_failure(message, headers)
        with self._exclusive_ledger_lock():
            if failure_class in {"model_unavailable", "unknown"}:
                return self._record_route_failure(
                    f"runtime:{runtime_route_id}",
                    pool_id=pool_id,
                    message=message,
                    headers=headers,
                    attempt_id=attempt_id,
                    blocks_route=failure_class == "model_unavailable",
                )
            return self._record_pool_failure(
                pool_id,
                message=message,
                headers=headers,
                attempt_id=attempt_id,
            )

    def record_runtime_success(
        self,
        runtime_route_id: str,
        *,
        pool_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        """Record success for a dynamic route without invoking legacy routing."""

        if pool_id not in self.policy.get("pools", {}):
            raise CapacityPolicyError(f"unknown capacity pool: {pool_id}")
        with self._exclusive_ledger_lock():
            return self._record_pool_success(
                pool_id,
                attempt_id=attempt_id,
                source_kind="runtime_success",
                route_id=f"runtime:{runtime_route_id}",
            )

    @contextmanager
    def _exclusive_ledger_lock(self):
        """Serialize capacity decisions that grant or replace shared canary leases."""
        lock_path = self.ledger_path.with_suffix(self.ledger_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def record_failure(
        self,
        route_id: str,
        *,
        message: str,
        headers: Mapping[str, Any] | None = None,
        attempt_id: str,
    ) -> dict[str, Any]:
        """Record a provider failure and open its route's shared pool breaker."""

        route = self.policy.get("routes", {}).get(route_id)
        if not isinstance(route, Mapping):
            raise ValueError(f"unknown capacity route: {route_id}")
        pool_id = str(route.get("pool", ""))
        if pool_id not in self.policy.get("pools", {}):
            raise ValueError(f"unknown capacity pool for route {route_id}: {pool_id}")

        failure_class = _classify_failure(message, headers)
        with self._exclusive_ledger_lock():
            if failure_class in {"model_unavailable", "unknown"}:
                return self._record_route_failure(
                    route_id,
                    pool_id=pool_id,
                    message=message,
                    headers=headers,
                    attempt_id=attempt_id,
                    blocks_route=failure_class == "model_unavailable",
                )
            return self._record_pool_failure(
                pool_id,
                message=message,
                headers=headers,
                attempt_id=attempt_id,
            )

    def _record_pool_failure(
        self,
        pool_id: str,
        *,
        message: str,
        headers: Mapping[str, Any] | None,
        attempt_id: str,
        source_kind: str | None = None,
    ) -> dict[str, Any]:
        """Persist a normalized failure without retaining raw provider output."""

        observation = self._failure_observation(
            message=message,
            headers=headers,
            attempt_id=attempt_id,
            source_kind=source_kind,
        )
        ledger = self._load_ledger()
        pool_state = ledger["pools"].setdefault(pool_id, {})
        if observation["failure_class"] in {"rate_limited", "quota_exhausted", "auth_missing"}:
            pool_state["status"] = "open"
            pool_state["failure_class"] = observation["failure_class"]
            pool_state["reset_at"] = observation["reset_at"]
            pool_state["remaining"] = observation["remaining"]
            pool_state["canary_lease"] = None
        elif "status" not in pool_state:
            pool_state["status"] = "unknown"
            pool_state["failure_class"] = "unknown"
            pool_state["reset_at"] = None
            pool_state["canary_lease"] = None
        pool_state.setdefault("observations", []).append(observation)
        ledger["updated_at"] = observation["observed_at"]
        atomic_write_yaml(self.ledger_path, ledger)
        return observation

    def _failure_observation(
        self,
        *,
        message: str,
        headers: Mapping[str, Any] | None,
        attempt_id: str,
        source_kind: str | None = None,
    ) -> dict[str, Any]:
        """Normalize provider signals while preserving unknowns as null."""

        now = _as_utc(self.clock())
        normalized_headers = _headers(headers)
        header_reset = _retry_after_reset(normalized_headers.get("retry-after"), now)
        message_reset = _message_reset(message, now)
        reset_at = header_reset or message_reset
        failure_class = _classify_failure(message, normalized_headers)
        observation = {
            "source_kind": source_kind or (
                "provider_header"
                if header_reset is not None
                else "provider_message"
                if message_reset is not None
                else "runtime_failure"
            ),
            "observed_at": _timestamp(now),
            "expires_at": _timestamp(reset_at) if reset_at else None,
            "reset_at": _timestamp(reset_at) if reset_at else None,
            "remaining": _number(normalized_headers.get("x-ratelimit-remaining")),
            "confidence": "high" if reset_at is not None else "unknown",
            "attempt_id": attempt_id,
            "failure_class": failure_class,
        }
        return observation

    def _record_route_failure(
        self,
        route_id: str,
        *,
        pool_id: str,
        message: str,
        headers: Mapping[str, Any] | None,
        attempt_id: str,
        blocks_route: bool,
    ) -> dict[str, Any]:
        """Persist model-specific or unknown failures without poisoning a pool."""

        observation = self._failure_observation(
            message=message,
            headers=headers,
            attempt_id=attempt_id,
        )
        ledger = self._load_ledger()
        route_state = ledger["routes"].setdefault(route_id, {})
        route_state["status"] = "blocked" if blocks_route else "unknown"
        route_state["pool_id"] = pool_id
        route_state["failure_class"] = observation["failure_class"]
        route_state["reset_at"] = observation["reset_at"]
        route_state.setdefault("observations", []).append(observation)
        pool_state = ledger["pools"].get(pool_id, {})
        lease = pool_state.get("canary_lease") if isinstance(pool_state, Mapping) else None
        if (
            blocks_route
            and isinstance(pool_state, dict)
            and pool_state.get("status") == "canary"
            and isinstance(lease, Mapping)
            and lease.get("attempt_id") == attempt_id
        ):
            # A model-scoped failure does not prove that shared quota recovered.
            # Release only this attempt's lease, preserving the expired breaker
            # so the next declared model must acquire the sole canary lease.
            pool_state["status"] = "open"
            pool_state["canary_lease"] = None
        ledger["updated_at"] = observation["observed_at"]
        atomic_write_yaml(self.ledger_path, ledger)
        return observation

    def safe_probe_command(self, pool_id: str) -> tuple[str, ...]:
        """Return a validated non-secret probe command declared for ``pool_id``."""

        pool = self.policy.get("pools", {}).get(pool_id)
        if not isinstance(pool, Mapping):
            raise CapacityPolicyError(f"unknown capacity pool: {pool_id}")
        raw_command = pool.get("probe")
        if not isinstance(raw_command, list) or not all(isinstance(part, str) for part in raw_command):
            raise UnsafeCapacityProbeError(f"capacity pool {pool_id!r} has no safe probe")
        command = tuple(raw_command)
        if command == ("agy", "models"):
            return command
        if (
            len(command) == 4
            and command[:3] == ("hermes", "auth", "status")
            and re.fullmatch(r"[A-Za-z0-9._-]+", command[3])
        ):
            return command
        raise UnsafeCapacityProbeError(
            "forbidden capacity probe; only 'agy models' and "
            "'hermes auth status <provider>' are allowed (never 'hermes status --all')"
        )

    def safe_quota_probe_spec(self, pool_id: str):
        """Return a validated interactive usage probe for one credential pool."""

        pool = self.policy.get("pools", {}).get(pool_id)
        if not isinstance(pool, Mapping):
            raise CapacityPolicyError(f"unknown capacity pool: {pool_id}")
        raw = pool.get("quota_probe")
        if not isinstance(raw, Mapping):
            raise UnsafeCapacityProbeError(f"capacity pool {pool_id!r} has no quota probe")
        try:
            from agent_runtime.quota_probes import QuotaProbeSpec
        except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
            from quota_probes import QuotaProbeSpec
        try:
            return QuotaProbeSpec.from_mapping(raw)
        except ValueError as exc:
            raise UnsafeCapacityProbeError(str(exc)) from exc

    def probe_quota(
        self,
        pool_id: str,
        *,
        runner: Callable[[Any], Any],
        attempt_id: str,
        probe_spec: Mapping[str, Any] | Any | None = None,
        predicted_unit_usage_percent: float = 0.0,
        risk_reserve_percent: float = 0.0,
    ) -> dict[str, Any]:
        """Run one bounded slash-command probe and persist only normalized data."""

        try:
            from agent_runtime.quota_probes import parse_quota_output
        except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
            from quota_probes import parse_quota_output
        if probe_spec is None:
            spec = self.safe_quota_probe_spec(pool_id)
        else:
            try:
                from agent_runtime.quota_probes import QuotaProbeSpec
            except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
                from quota_probes import QuotaProbeSpec
            try:
                if isinstance(probe_spec, Mapping):
                    spec = QuotaProbeSpec.from_mapping(probe_spec)
                else:
                    probe_spec.validate()
                    spec = probe_spec
            except (AttributeError, ValueError) as exc:
                raise UnsafeCapacityProbeError(str(exc)) from exc
        outcome = runner(spec)
        if isinstance(outcome, Mapping):
            returncode = int(outcome.get("returncode", 0))
            output = str(outcome.get("output", outcome.get("stdout", "")) or "")
            stderr = str(outcome.get("stderr", "") or "")
        else:
            returncode = int(getattr(outcome, "returncode", 0))
            output = str(getattr(outcome, "output", getattr(outcome, "stdout", "")) or "")
            stderr = str(getattr(outcome, "stderr", "") or "")
        snapshot = parse_quota_output(
            pool_id,
            "\n".join(part for part in (output, stderr) if part),
            observed_at=_as_utc(self.clock()),
            stale_after_seconds=int((self.policy.get("quota_policy") or {}).get("stale_after_seconds", 600)),
        )
        if returncode != 0 and snapshot.status == "unknown":
            snapshot_data = snapshot.to_dict()
            snapshot_data["failure_class"] = "telemetry_unparseable"
            snapshot_data["status"] = "telemetry_degraded"
            snapshot = snapshot_data
        return self.record_quota_snapshot(
            pool_id,
            snapshot,
            attempt_id=attempt_id,
            predicted_unit_usage_percent=predicted_unit_usage_percent,
            risk_reserve_percent=risk_reserve_percent,
        )

    def record_quota_snapshot(
        self,
        pool_id: str,
        snapshot: Any,
        *,
        attempt_id: str,
        predicted_unit_usage_percent: float = 0.0,
        risk_reserve_percent: float = 0.0,
    ) -> dict[str, Any]:
        """Persist an actual credential-pool quota reading and admission state."""

        if pool_id not in self.policy.get("pools", {}):
            raise CapacityPolicyError(f"unknown capacity pool: {pool_id}")
        raw = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
        if str(raw.get("credential_pool_id") or pool_id) != pool_id:
            raise CapacityPolicyError("quota snapshot credential pool mismatch")
        now = _as_utc(self.clock())
        hard_reserve = float((self.policy.get("quota_policy") or {}).get("hard_reserve_percent", 5.0))
        admission_floor = max(
            hard_reserve,
            max(0.0, float(predicted_unit_usage_percent)) + max(0.0, float(risk_reserve_percent)),
        )
        remaining_raw = raw.get("remaining_percent")
        remaining = float(remaining_raw) if remaining_raw is not None else None
        provider_reset = _parse_timestamp(raw.get("reset_at"))
        status = str(raw.get("status") or "unknown")
        failure_class = raw.get("failure_class")
        wait_state = None
        resume_at = None
        pool_status = "closed"
        if status == "auth_missing":
            pool_status = "open"
            failure_class = "auth_missing"
        elif remaining is not None and remaining <= admission_floor:
            pool_status = "open"
            failure_class = "quota_exhausted"
            wait_state = "waiting_for_quota"
            if provider_reset is not None:
                jitter_min, jitter_max = (self.policy.get("quota_policy") or {}).get(
                    "resume_jitter_seconds", [60, 180]
                )
                low = int(jitter_min)
                high = max(low, int(jitter_max))
                jitter = low + (sum(ord(ch) for ch in attempt_id) % (high - low + 1))
                resume_at = provider_reset + timedelta(seconds=jitter)
        elif status in {"unknown", "stale", "telemetry_degraded"} or remaining is None:
            pool_status = "telemetry_degraded"
            failure_class = failure_class or "telemetry_unparseable"

        observation = {
            "source_kind": str(raw.get("source_kind") or "cli_usage"),
            "observed_at": str(raw.get("observed_at") or _timestamp(now)),
            "expires_at": str(raw.get("stale_at")) if raw.get("stale_at") else None,
            "reset_at": str(raw.get("reset_at")) if raw.get("reset_at") else None,
            "remaining": remaining,
            "remaining_percent": remaining,
            "confidence": str(raw.get("confidence") or "unknown"),
            "attempt_id": attempt_id,
            "failure_class": failure_class,
            "windows": list(raw.get("windows") or []),
            "admission_floor_percent": admission_floor,
        }
        with self._exclusive_ledger_lock():
            ledger = self._load_ledger()
            pool_state = ledger["pools"].setdefault(pool_id, {})
            pool_state.update({
                "status": pool_status,
                "failure_class": failure_class,
                "provider_reset_at": _timestamp(provider_reset) if provider_reset else None,
                "reset_at": _timestamp(resume_at) if resume_at else (_timestamp(provider_reset) if provider_reset else None),
                "resume_at": _timestamp(resume_at) if resume_at else None,
                "wait_state": wait_state,
                "remaining": remaining,
                "remaining_percent": remaining,
                "quota_observed_at": observation["observed_at"],
                "quota_stale_at": observation["expires_at"],
                "admission_floor_percent": admission_floor,
                "quota_windows": observation["windows"],
                "canary_lease": None,
            })
            pool_state.setdefault("observations", []).append(observation)
            ledger["updated_at"] = observation["observed_at"]
            atomic_write_yaml(self.ledger_path, ledger)
        return {
            "status": wait_state or ("telemetry_degraded" if pool_status == "telemetry_degraded" else "available"),
            "capacity_status": pool_status,
            "pool_id": pool_id,
            "remaining_percent": remaining,
            "admission_floor_percent": admission_floor,
            "reset_at": observation["reset_at"],
            "resume_at": _timestamp(resume_at) if resume_at else None,
            "observation": observation,
        }

    def probe(
        self,
        pool_id: str,
        *,
        runner: Callable[[tuple[str, ...]], Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        """Execute one allowlisted probe through an injected runner and persist its status."""

        command = self.safe_probe_command(pool_id)
        outcome = runner(command)
        if isinstance(outcome, Mapping):
            returncode = int(outcome.get("returncode", 0))
            stdout = str(outcome.get("stdout", "") or "")
            stderr = str(outcome.get("stderr", "") or "")
        else:
            returncode = int(getattr(outcome, "returncode", 0))
            stdout = str(getattr(outcome, "stdout", "") or "")
            stderr = str(getattr(outcome, "stderr", "") or "")
        message = "\n".join(part for part in (stdout, stderr) if part)
        failure_class = _classify_failure(message)
        if returncode != 0 or failure_class in {"auth_missing", "quota_exhausted", "rate_limited"}:
            with self._exclusive_ledger_lock():
                observation = self._record_pool_failure(
                    pool_id,
                    message=message or f"safe probe exited {returncode}",
                    headers=None,
                    attempt_id=attempt_id,
                    source_kind="safe_probe",
                )
            status = "blocked" if observation["failure_class"] != "unknown" else "unknown"
            return {
                "status": status,
                "capacity_status": status,
                "pool_id": pool_id,
                "observation": observation,
            }

        with self._exclusive_ledger_lock():
            observation, capacity_status = self._record_probe_success(
                pool_id,
                attempt_id=attempt_id,
            )
        return {
            "status": capacity_status,
            "capacity_status": capacity_status,
            "pool_id": pool_id,
            "observation": observation,
        }

    def _record_probe_success(
        self,
        pool_id: str,
        *,
        attempt_id: str,
    ) -> tuple[dict[str, Any], str]:
        """Record auth/model discovery without claiming request capacity."""

        ledger = self._load_ledger()
        pool_state = ledger["pools"].setdefault(pool_id, {})
        if pool_state.get("failure_class") == "auth_missing":
            pool_state["status"] = "unknown"
            pool_state["failure_class"] = None
            pool_state["reset_at"] = None
            pool_state["remaining"] = None
            pool_state["canary_lease"] = None
        elif "status" not in pool_state:
            pool_state["status"] = "unknown"

        observed_at = _timestamp(_as_utc(self.clock()))
        observation = {
            "source_kind": "safe_probe",
            "observed_at": observed_at,
            "expires_at": None,
            "reset_at": None,
            "remaining": None,
            "confidence": "high",
            "attempt_id": attempt_id,
            "failure_class": None,
        }
        pool_state.setdefault("observations", []).append(observation)
        ledger["updated_at"] = observed_at
        atomic_write_yaml(self.ledger_path, ledger)
        capacity_status = "blocked" if pool_state.get("status") in {"open", "canary"} else "unknown"
        return observation, capacity_status

    def select_route(
        self,
        route_id: str,
        *,
        role: str,
        attempt_id: str,
        required_modalities: list[str] | set[str] | tuple[str, ...] | None = None,
        predicted_unit_usage_percent: float = 0.0,
        risk_reserve_percent: float = 0.0,
        long_batch: bool = False,
        explicit_canary: bool = False,
    ) -> dict[str, Any]:
        with self._exclusive_ledger_lock():
            return self._select_route_locked(
                route_id,
                role=role,
                attempt_id=attempt_id,
                required_modalities=required_modalities,
                predicted_unit_usage_percent=predicted_unit_usage_percent,
                risk_reserve_percent=risk_reserve_percent,
                long_batch=long_batch,
                explicit_canary=explicit_canary,
            )

    def _select_route_locked(
        self,
        route_id: str,
        *,
        role: str,
        attempt_id: str,
        required_modalities: list[str] | set[str] | tuple[str, ...] | None = None,
        predicted_unit_usage_percent: float = 0.0,
        risk_reserve_percent: float = 0.0,
        long_batch: bool = False,
        explicit_canary: bool = False,
    ) -> dict[str, Any]:
        """Select the first capacity-eligible route in an approved same-role chain."""

        routes = self.policy.get("routes", {})
        primary = routes.get(route_id) if isinstance(routes, Mapping) else None
        if not isinstance(primary, Mapping):
            raise CapacityPolicyError(f"unknown capacity route: {route_id}")
        requested_role = _canonical_role(role)
        required = {
            str(item).strip().lower()
            for item in (required_modalities or [])
            if str(item).strip()
        }
        if _canonical_role(primary.get("role")) != requested_role:
            raise CapacityPolicyError(
                f"route {route_id!r} is approved for role {primary.get('role')!r}, not {role!r}"
            )

        validated: set[str] = set()
        active_path: list[str] = []

        def validate_declared_routes(candidate_id: str) -> dict[str, Any] | None:
            """Validate every reachable declaration before granting capacity."""

            if candidate_id in validated:
                return None
            candidate = routes.get(candidate_id)
            if not isinstance(candidate, Mapping):
                predecessor = active_path[-1] if active_path else route_id
                raise CapacityPolicyError(
                    f"route {predecessor!r} names unknown fallback {candidate_id!r}"
                )
            if _canonical_role(candidate.get("role")) != requested_role:
                predecessor = active_path[-1] if active_path else route_id
                raise CapacityPolicyError(
                    f"route {predecessor!r} fallback {candidate_id!r} changes role "
                    f"to {candidate.get('role')!r}"
                )
            fallbacks = candidate.get("approved_fallbacks", []) or []
            if not isinstance(fallbacks, list):
                raise CapacityPolicyError(
                    f"route {candidate_id!r} approved_fallbacks must be a list"
                )
            fallback_on = candidate.get("fallback_on", []) or []
            if fallbacks and not isinstance(fallback_on, list):
                raise CapacityPolicyError(f"route {candidate_id!r} fallback_on must be a list")

            active_path.append(candidate_id)
            declared_here: set[str] = set()
            for raw_fallback_id in fallbacks:
                fallback_id = str(raw_fallback_id)
                if fallback_id in declared_here:
                    return {
                        "status": "blocked",
                        "route_id": None,
                        "route_chain": [*active_path, fallback_id],
                        "pool_id": candidate.get("pool"),
                        "capacity_status": "blocked",
                        "failure_class": "invalid_fallback_duplicate",
                        "reset_at": None,
                        "attempt_id": attempt_id,
                    }
                declared_here.add(fallback_id)
                if fallback_id in active_path:
                    return {
                        "status": "blocked",
                        "route_id": None,
                        "route_chain": [*active_path, fallback_id],
                        "pool_id": candidate.get("pool"),
                        "capacity_status": "blocked",
                        "failure_class": "invalid_fallback_cycle",
                        "reset_at": None,
                        "attempt_id": attempt_id,
                    }
                issue = validate_declared_routes(fallback_id)
                if issue is not None:
                    return issue
            active_path.pop()
            validated.add(candidate_id)
            return None

        policy_issue = validate_declared_routes(route_id)
        if policy_issue is not None:
            return policy_issue

        ledger = self._load_ledger()
        pool_states = ledger["pools"]
        route_states = ledger["routes"]
        now = _as_utc(self.clock())
        evaluated: set[str] = set()

        def evaluate_candidate(candidate_id: str, path: list[str]) -> dict[str, Any]:
            candidate = routes[candidate_id]
            quarantined = (
                str(candidate.get("status") or "active") in {"quarantined", "disabled"}
                or candidate.get("automatic_use") is False
            )
            explicit_candidate_allowed = (
                explicit_canary
                and candidate_id == route_id
                and candidate.get("explicit_canary_allowed") is True
                and str(candidate.get("status") or "active") != "disabled"
            )
            if quarantined and not explicit_candidate_allowed:
                return {
                    "status": "blocked",
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": candidate.get("pool"),
                    "capacity_status": "blocked",
                    "failure_class": "route_quarantined",
                    "reset_at": None,
                    "attempt_id": attempt_id,
                }
            supported = {
                str(item).strip().lower()
                for item in candidate.get("input_modalities", []) or []
                if str(item).strip()
            }
            if required and not required.issubset(supported):
                return {
                    "status": "blocked",
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": candidate.get("pool"),
                    "capacity_status": "blocked",
                    "failure_class": "unsupported_modality",
                    "reset_at": None,
                    "missing_modalities": sorted(required - supported),
                    "attempt_id": attempt_id,
                }
            pool_id = str(candidate.get("pool", ""))
            if pool_id not in self.policy.get("pools", {}):
                raise CapacityPolicyError(
                    f"route {candidate_id!r} names unknown capacity pool {pool_id!r}"
                )
            route_state = route_states.get(candidate_id, {}) if isinstance(route_states, Mapping) else {}
            if isinstance(route_state, Mapping) and route_state.get("status") == "blocked":
                return {
                    "status": "blocked",
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "blocked",
                    "failure_class": route_state.get("failure_class"),
                    "reset_at": route_state.get("reset_at"),
                    "attempt_id": attempt_id,
                }
            pool_state = pool_states.get(pool_id, {}) if isinstance(pool_states, Mapping) else {}
            pool_status = pool_state.get("status") if isinstance(pool_state, Mapping) else None
            reset_at = _parse_timestamp(pool_state.get("reset_at")) if isinstance(pool_state, Mapping) else None
            quota_stale_at = _parse_timestamp(pool_state.get("quota_stale_at")) if isinstance(pool_state, Mapping) else None
            remaining_percent = pool_state.get("remaining_percent") if isinstance(pool_state, Mapping) else None
            admission_floor = max(
                float((self.policy.get("quota_policy") or {}).get("hard_reserve_percent", 5.0)),
                max(0.0, float(predicted_unit_usage_percent)) + max(0.0, float(risk_reserve_percent)),
            )
            if long_batch and (
                pool_status == "telemetry_degraded"
                or (quota_stale_at is not None and now >= quota_stale_at)
            ):
                return {
                    "status": "blocked",
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "telemetry_degraded",
                    "failure_class": "telemetry_degraded",
                    "reset_at": pool_state.get("reset_at"),
                    "attempt_id": attempt_id,
                }
            if remaining_percent is not None and float(remaining_percent) <= admission_floor:
                return {
                    "status": str(pool_state.get("wait_state") or "blocked"),
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "blocked",
                    "failure_class": "quota_exhausted",
                    "reset_at": pool_state.get("reset_at"),
                    "resume_at": pool_state.get("resume_at"),
                    "remaining": remaining_percent,
                    "admission_floor_percent": admission_floor,
                    "attempt_id": attempt_id,
                }
            lease = pool_state.get("canary_lease") if isinstance(pool_state, Mapping) else None
            lease_expires = _parse_timestamp(lease.get("expires_at")) if isinstance(lease, Mapping) else None
            lease_owner = lease.get("attempt_id") if isinstance(lease, Mapping) else None

            if (
                pool_status == "canary"
                and lease_owner == attempt_id
                and lease_expires is not None
                and now < lease_expires
            ):
                return {
                    "status": "selected",
                    "route_id": candidate_id,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "canary",
                    "selection_kind": "primary" if len(path) == 1 else "approved_fallback",
                    "attempt_id": attempt_id,
                }

            grant_canary = False
            if pool_status == "open" and reset_at is not None and now >= reset_at:
                grant_canary = True
            elif pool_status == "canary" and lease_expires is not None and now >= lease_expires:
                grant_canary = True

            if grant_canary:
                lease_seconds = int(
                    self.policy.get("pools", {}).get(pool_id, {}).get(
                        "canary_lease_seconds", self.policy.get("canary_lease_seconds", 300)
                    )
                )
                mutable_pool = pool_states.setdefault(pool_id, {})
                mutable_pool["status"] = "canary"
                mutable_pool["canary_lease"] = {
                    "attempt_id": attempt_id,
                    "leased_at": _timestamp(now),
                    "expires_at": _timestamp(now + timedelta(seconds=lease_seconds)),
                }
                ledger["updated_at"] = _timestamp(now)
                atomic_write_yaml(self.ledger_path, ledger)
                return {
                    "status": "selected",
                    "route_id": candidate_id,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "canary",
                    "selection_kind": "primary" if len(path) == 1 else "approved_fallback",
                    "attempt_id": attempt_id,
                }

            if pool_status in {"open", "canary"}:
                blocked = {
                    "status": str(pool_state.get("wait_state") or "blocked"),
                    "route_id": None,
                    "route_chain": list(path),
                    "pool_id": pool_id,
                    "capacity_status": "blocked",
                    "failure_class": pool_state.get("failure_class"),
                    "reset_at": pool_state.get("reset_at"),
                    "remaining": pool_state.get("remaining"),
                    "resume_at": pool_state.get("resume_at"),
                    "attempt_id": attempt_id,
                }
                return blocked

            capacity_status = "available" if pool_status == "closed" else "unknown"
            selection = {
                "status": "selected",
                "route_id": candidate_id,
                "route_chain": list(path),
                "pool_id": pool_id,
                "capacity_status": capacity_status,
                "selection_kind": "primary" if len(path) == 1 else "approved_fallback",
                "attempt_id": attempt_id,
            }
            if explicit_candidate_allowed:
                selection["selection_mode"] = "explicit_canary"
            return selection

        def traverse(candidate_id: str, path: list[str]) -> dict[str, Any] | None:
            if candidate_id in evaluated:
                return None
            evaluated.add(candidate_id)
            decision = evaluate_candidate(candidate_id, path)
            if decision["status"] == "selected":
                return decision

            candidate = routes[candidate_id]
            fallbacks = candidate.get("approved_fallbacks", []) or []
            fallback_on = candidate.get("fallback_on", []) or []
            if decision.get("failure_class") == "unsupported_modality":
                return decision
            if decision.get("failure_class") not in fallback_on:
                return decision

            incompatible_fallbacks: list[dict[str, Any]] = []
            first_terminal_block: dict[str, Any] | None = None
            for raw_fallback_id in fallbacks:
                fallback_id = str(raw_fallback_id)
                child = traverse(fallback_id, [*path, fallback_id])
                if child is None:
                    continue
                if child["status"] == "selected":
                    return child
                if child.get("failure_class") == "unsupported_modality":
                    incompatible_fallbacks.append(
                        {
                            "route_id": fallback_id,
                            "missing_modalities": child.get("missing_modalities", []),
                        }
                    )
                elif first_terminal_block is None:
                    first_terminal_block = child
                incompatible_fallbacks.extend(child.get("incompatible_fallbacks", []))
            if first_terminal_block is not None:
                return first_terminal_block
            if incompatible_fallbacks:
                decision["incompatible_fallbacks"] = incompatible_fallbacks
            return decision

        return traverse(route_id, [route_id]) or {
            "status": "blocked",
            "route_id": None,
            "route_chain": [route_id],
            "pool_id": None,
            "capacity_status": "unknown",
            "failure_class": "approved_fallbacks_exhausted",
            "reset_at": None,
            "attempt_id": attempt_id,
        }

    def record_success(self, route_id: str, *, attempt_id: str) -> dict[str, Any]:
        """Close a shared breaker after a successful attempt or canary."""

        route = self.policy.get("routes", {}).get(route_id)
        if not isinstance(route, Mapping):
            raise CapacityPolicyError(f"unknown capacity route: {route_id}")
        pool_id = str(route.get("pool", ""))
        if pool_id not in self.policy.get("pools", {}):
            raise CapacityPolicyError(f"unknown capacity pool for route {route_id}: {pool_id}")

        with self._exclusive_ledger_lock():
            return self._record_pool_success(
                pool_id,
                attempt_id=attempt_id,
                source_kind="runtime_success",
                route_id=route_id,
            )

    def _record_pool_success(
        self,
        pool_id: str,
        *,
        attempt_id: str,
        source_kind: str,
        route_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist an available observation and close the pool breaker."""

        ledger = self._load_ledger()
        pool_state = ledger["pools"].setdefault(pool_id, {})
        if route_id is not None:
            route_state = ledger["routes"].setdefault(route_id, {})
            route_state["status"] = "closed"
            route_state["failure_class"] = None
            route_state["reset_at"] = None
        lease = pool_state.get("canary_lease")
        if (
            pool_state.get("status") == "canary"
            and isinstance(lease, Mapping)
            and lease.get("attempt_id") != attempt_id
        ):
            raise CapacityPolicyError(
                f"attempt {attempt_id!r} does not own canary lease for pool {pool_id!r}"
            )

        observed_at = _timestamp(_as_utc(self.clock()))
        observation = {
            "source_kind": source_kind,
            "observed_at": observed_at,
            "expires_at": None,
            "reset_at": None,
            "remaining": None,
            "confidence": "high",
            "attempt_id": attempt_id,
            "failure_class": None,
        }
        quota_remaining = pool_state.get("remaining_percent")
        hard_reserve = float((self.policy.get("quota_policy") or {}).get("hard_reserve_percent", 5.0))
        quota_reserved = quota_remaining is not None and float(quota_remaining) <= hard_reserve
        pool_state["status"] = "open" if quota_reserved else "closed"
        pool_state["failure_class"] = "quota_exhausted" if quota_reserved else None
        if not quota_reserved:
            pool_state["reset_at"] = None
            pool_state["resume_at"] = None
            pool_state["wait_state"] = None
        # Runtime success proves the route works, but it does not invent or
        # erase an independently observed subscription percentage.
        if "remaining_percent" not in pool_state:
            pool_state["remaining"] = None
        pool_state["canary_lease"] = None
        pool_state.setdefault("observations", []).append(observation)
        ledger["updated_at"] = observed_at
        atomic_write_yaml(self.ledger_path, ledger)
        return observation
