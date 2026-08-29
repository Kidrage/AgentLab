from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess

import yaml

from agent_runtime.approval_signature import (
    approval_payload_bytes,
    narrative_outbound_approval_payload,
)
from agent_runtime.cli_executor import _task_packet_payload
from agent_runtime.schemas import WorkflowPlan


def authorize_external_packet(
    plan: WorkflowPlan,
    *,
    agent_name: str,
    cli_agent_name: str,
    sealed_messages: list[dict[str, str]] | None = None,
    task_messages: list[dict[str, str]] | None = None,
) -> None:
    root = Path(plan.agentlab_root)
    authority = root.parent / f".{root.name}-external-approval"
    authority.mkdir(parents=True, exist_ok=True)
    private_key = authority / "private.pem"
    public_key = authority / "public.pem"
    if not private_key.is_file():
        subprocess.run(
            [
                "/usr/bin/openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
        )
    topology_path = root / "config" / "local_private_topology.yml"
    topology = (
        yaml.safe_load(topology_path.read_text(encoding="utf-8")) or {}
        if topology_path.is_file()
        else {}
    )
    topology["external_context_approval_authority"] = {
        "public_key_path": str(public_key),
        "public_key_sha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
    }
    topology_path.write_text(
        yaml.safe_dump(topology, sort_keys=False),
        encoding="utf-8",
    )
    packet_text = json.dumps(
        _task_packet_payload(
            agent_name,
            plan,
            sealed_messages,
            task_messages,
        ),
        indent=2,
        ensure_ascii=False,
    )
    packet_sha256 = hashlib.sha256(packet_text.encode("utf-8")).hexdigest()
    scope_sha256 = hashlib.sha256(
        f"{plan.task_id}:{agent_name}:{cli_agent_name}".encode("utf-8")
    ).hexdigest()
    recipient = f"cli_agent:{cli_agent_name}"
    purpose = "bounded test role session"
    expires_at = "2999-01-01T00:00:00Z"
    payload = narrative_outbound_approval_payload(
        project=str(plan.project),
        task_id=str(plan.task_id),
        recipient=recipient,
        purpose=purpose,
        packet_payload_sha256=packet_sha256,
        scope_sha256=scope_sha256,
        expires_at=expires_at,
    )
    payload_path = authority / f"{plan.task_id}-{agent_name}.json"
    payload_path.write_bytes(approval_payload_bytes(payload))
    signature_path = authority / f"{plan.task_id}-{agent_name}.sig"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature_path),
            str(payload_path),
        ],
        check=True,
        capture_output=True,
    )
    plan.execution_policy = {
        "external_context_approval_required": True,
        "external_context_payload_sha256_required": True,
        "external_context_scope_sha256_required": True,
        "external_context_scope_contract_valid": True,
        "external_context_scope_sha256": scope_sha256,
        "external_context_approval_signature_path": str(signature_path),
        "external_context_transfer": {
            "recipient": recipient,
            "purpose": purpose,
            "expires_at": expires_at,
        },
    }
