from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess

import yaml

from agent_runtime.narrative.candidates.promotion import evidence_bundle_sha256
from agent_runtime.narrative.user_acceptance import (
    candidate_acceptance_payload,
    record_candidate_acceptance,
)


def record_signed_candidate_acceptance(
    project_root: Path,
    *,
    manifest_path: Path,
    actor_id: str,
    idempotency_key: str,
    approved_at: str,
) -> dict:
    manifest = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    authority_root = (
        project_root.parent.parent.parent / "test-approval-authority"
    )
    authority_root.mkdir(parents=True, exist_ok=True)
    private_key = authority_root / "private.pem"
    public_key = authority_root / "public.pem"
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
    config_path = project_root.parent.parent / "config" / "local_private_topology.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "user_approval_authority": {
                    "public_key_path": str(public_key),
                    "public_key_sha256": hashlib.sha256(
                        public_key.read_bytes()
                    ).hexdigest(),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    payload = candidate_acceptance_payload(
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        approved_at=approved_at,
        candidate_set_id=str(manifest["candidate_set_id"]),
        candidate_set_sha256=str(manifest["candidate_set_sha256"]),
        evidence_bundle_sha256=evidence_bundle_sha256(
            project_root,
            manifest,
        ),
    )
    payload_path = authority_root / f"{idempotency_key}.json"
    payload_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    signature_path = authority_root / f"{idempotency_key}.sig"
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
    return record_candidate_acceptance(
        project_root,
        manifest_path=manifest_path,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        approved_at=approved_at,
        signature_path=signature_path,
    )
