"""Agent authority evaluation with fail-closed scope matching."""

from __future__ import annotations

import hashlib
import json

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


def effective_contract_hash(manifest: AgentManifest) -> str:
    """Hash the fields that constrain one concrete Agent execution."""
    document = manifest.to_dict()
    contract = {
        "identity": document["identity"],
        "role": document["role"],
        "authority": document["authority"],
        "knowledge": document["knowledge"],
        "runtime": document["runtime"],
        "lifecycle": document["lifecycle"],
        "validation": document["validation"],
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
