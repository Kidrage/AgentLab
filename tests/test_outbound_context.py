from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.outbound_context import (
    PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
    build_outbound_context_manifest,
)


def test_outbound_manifest_hashes_payload_without_rendering_private_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "projects" / "Crown_of_Ash" / "project_fact_snapshot.yml"
    source.parent.mkdir(parents=True)
    source.write_text("canon_marker: ash-crown-private\n", encoding="utf-8")

    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_writer",
        role="Writer",
        provider_surface="cli_agent:agy",
        payload_kind="sealed_cli_role_session_packet",
        payload_text="Use canon marker ash-crown-private.",
        source_paths=[source],
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=False,
    )

    assert report["status"] == "pass"
    assert report["execution_allowed"] is True
    assert len(report["payload"]["sha256"]) == 64
    assert report["source_inventory"]["files"][0]["path"].endswith(
        "project_fact_snapshot.yml"
    )
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "ash-crown-private" not in rendered


def test_outbound_manifest_blocks_secret_without_echoing_value(tmp_path: Path) -> None:
    secret = "sk-" + ("a" * 40)

    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_writer",
        role="Writer",
        provider_surface="cli_agent:agy",
        payload_kind="sealed_cli_role_session_packet",
        payload_text=f"credential: {secret}",
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=False,
    )

    assert report["status"] == "blocked"
    assert report["execution_allowed"] is False
    assert report["payload"]["secret_pattern_hit_count"] >= 1
    assert "secret_pattern_detected" in report["issues"]
    assert secret not in yaml.safe_dump(report, sort_keys=False)


def test_outbound_manifest_distinguishes_pending_approval_from_unsafe_payload(
    tmp_path: Path,
) -> None:
    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_narrative_eval_ch01_test",
        role="Writer",
        provider_surface="cli_agent:agy",
        payload_kind="sealed_cli_role_session_packet",
        payload_text="safe private chapter context",
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=True,
        approval_granted=False,
    )

    assert report["status"] == "pending_approval"
    assert report["issues"] == ["explicit_private_context_approval_missing"]
    assert report["authorization"]["approval_observed"] is False


def test_outbound_manifest_rejects_env_source_even_when_payload_is_clean(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".env.local"
    source.write_text("SAFE_PLACEHOLDER=true\n", encoding="utf-8")

    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_writer",
        role="Writer",
        provider_surface="cli_agent:agy",
        payload_kind="sealed_cli_role_session_packet",
        payload_text="clean payload",
        source_paths=[source],
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=False,
    )

    assert report["status"] == "blocked"
    assert "forbidden_source_path:.env.local" in report["issues"]


def test_outbound_manifest_does_not_treat_fictional_secret_field_as_credential(
    tmp_path: Path,
) -> None:
    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_writer",
        role="Writer",
        provider_surface="cli_agent:agy",
        payload_kind="sealed_cli_role_session_packet",
        payload_text="character_state:\n  secret: bloodline\n",
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=False,
    )

    assert report["status"] == "pass"
    assert report["payload"]["secret_pattern_hit_count"] == 0


def test_outbound_manifest_uses_scoped_approval_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME, "1")

    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_pack",
        role="ArtifactProducer",
        provider_surface="cli_agent:agy",
        payload_kind="production_pack_cli_role_session_packet",
        payload_text="safe production-pack context",
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=True,
        approval_env_name=PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
    )

    assert report["status"] == "pass"
    assert report["authorization"]["approval_env_name"] == (
        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
    )
    assert report["authorization"]["approval_observed"] is True


def test_outbound_manifest_blocks_when_required_source_inventory_is_empty(
    tmp_path: Path,
) -> None:
    report = build_outbound_context_manifest(
        tmp_path,
        item_id="task_pack",
        role="Verifier",
        provider_surface="direct_api:deepseek",
        payload_kind="production_pack_direct_api_messages",
        payload_text="safe production-pack context",
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=True,
        approval_granted=True,
        approval_env_name=PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
        source_inventory_required=True,
    )

    assert report["status"] == "blocked"
    assert report["source_inventory"]["required"] is True
    assert "source_inventory_empty" in report["issues"]
