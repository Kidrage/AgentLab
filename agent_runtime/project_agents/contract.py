"""Agent authority evaluation with fail-closed scope matching."""

from __future__ import annotations

from .models import AgentManifest


class AgentContractViolation(RuntimeError):
    """An agent operation is absent from or forbidden by its manifest."""


def scope_matches(grant: str, requested: str) -> bool:
    if grant == "*":
        return True
    if grant.endswith(".*"):
        prefix = grant[:-2]
        return requested == prefix or requested.startswith(f"{prefix}.")
    return grant == requested


class AgentContract:
    def __init__(self, manifest: AgentManifest):
        self.manifest = manifest

    def assert_active(self) -> None:
        if self.manifest.status != "active":
            raise AgentContractViolation(
                f"agent {self.manifest.id!r} is not active"
            )

    def assert_read(self, scope: str) -> None:
        self._assert_scope(scope, self.manifest.read_scope, "read")

    def assert_write(self, scope: str) -> None:
        self._assert_scope(scope, self.manifest.write_scope, "write")

    def assert_approve(self, scope: str) -> None:
        self._assert_scope(scope, self.manifest.approval_scope, "approval")

    def _assert_scope(
        self, requested: str, grants: tuple[str, ...], authority: str
    ) -> None:
        self.assert_active()
        if not any(scope_matches(grant, requested) for grant in grants):
            raise AgentContractViolation(
                f"{requested!r} is outside {authority} scope for "
                f"agent {self.manifest.id!r}"
            )
