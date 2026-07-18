from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_runtime.capabilities import (
    CapabilityRegistry,
    CapabilityRecord,
    CapabilityStatus,
    PermissionGate,
    RiskLevel,
    create_builtin_registry,
    write_audio_contract,
    write_capability_gap_card,
    write_document_contract,
    write_vision_contract,
)
from agent_runtime.run_task import app


REQUIRED_CAPABILITY_IDS = {
    "filesystem_read",
    "filesystem_write",
    "shell_command",
    "git_ops",
    "web_search",
    "browser_fetch",
    "pdf_read",
    "docx_read",
    "spreadsheet_read",
    "image_understanding",
    "ocr",
    "video_understanding",
    "audio_transcription",
    "audio_analysis",
    "database_query",
    "github_ops",
    "ide_handoff",
    "openclaw_notify",
}


def test_builtin_registry_loads_deterministically() -> None:
    registry = create_builtin_registry()

    first = registry.to_sorted_dicts()
    second = create_builtin_registry().to_sorted_dicts()

    assert [item["capability_id"] for item in first] == sorted(REQUIRED_CAPABILITY_IDS)
    assert {item["capability_id"] for item in first} == REQUIRED_CAPABILITY_IDS
    assert first == second
    assert all("secret" not in yaml.safe_dump(item).lower() for item in first)


def test_duplicate_capability_id_fails() -> None:
    record = CapabilityRecord(
        capability_id="filesystem_read",
        display_name="Filesystem Read",
        description="Read files inside approved project paths.",
        modality="filesystem",
        backend_type="builtin",
        status=CapabilityStatus.AVAILABLE,
        permissions=("read",),
        risk_level=RiskLevel.LOW,
        evidence_required=("path",),
    )

    with pytest.raises(ValueError, match="duplicate capability_id"):
        CapabilityRegistry([record, record])


def test_missing_backend_creates_gap_card_without_fabricated_result(tmp_path: Path) -> None:
    registry = create_builtin_registry()

    gap_path = write_capability_gap_card(
        registry=registry,
        capability_id="image_understanding",
        out_dir=tmp_path,
        reason="mission requested image perception",
    )

    gap = yaml.safe_load(gap_path.read_text())
    assert gap["required_capability"] == "image_understanding"
    assert gap["missing_backend_reason"]
    assert gap["recommended_next_action"] == "request_approval_or_configure_backend"
    assert not (tmp_path / "vision_result.yml").exists()


def test_disabled_capability_cannot_be_selected() -> None:
    registry = create_builtin_registry()
    gate = PermissionGate(registry, disabled_capabilities={"web_search"})

    decision = gate.evaluate("web_search")

    assert decision.allowed is False
    assert decision.reason == "capability_disabled"


def test_high_risk_capability_requires_approval() -> None:
    registry = create_builtin_registry()
    gate = PermissionGate(registry)

    decision = gate.evaluate("shell_command")

    assert decision.allowed is False
    assert decision.reason == "approval_required"
    assert decision.requires_approval is True


def test_media_contracts_serialize_deterministically_and_validate_evidence(tmp_path: Path) -> None:
    vision_path = write_vision_contract(
        input_artifact="artifact.png",
        out_dir=tmp_path,
        observations=["mock observation"],
        summary="mock summary",
        evidence_artifacts=["artifact.png"],
        confidence="mock_only",
        mock=True,
    )
    audio_path = write_audio_contract(
        input_artifact="artifact.wav",
        out_dir=tmp_path,
        duration=0.0,
        observations=["mock audio observation"],
        transcript="mock transcript",
        features={"mode": "mock"},
        summary="mock audio summary",
        evidence_artifacts=["artifact.wav"],
        confidence="mock_only",
        mock=True,
    )
    document_path = write_document_contract(
        input_artifact="artifact.pdf",
        out_dir=tmp_path,
        pages=0,
        extracted_text="mock extracted text",
        tables=[],
        figures=[],
        citations=[],
        evidence_artifacts=["artifact.pdf"],
        confidence="mock_only",
        mock=True,
    )

    assert yaml.safe_load(vision_path.read_text())["risk"] == "human_review_required"
    assert yaml.safe_load(audio_path.read_text())["risk"] == "human_review_required"
    assert yaml.safe_load(document_path.read_text())["risk"] == "human_review_required"

    with pytest.raises(ValueError, match="confidence"):
        write_vision_contract(
            input_artifact="artifact.png",
            out_dir=tmp_path / "bad",
            observations=["mock observation"],
            summary="mock summary",
            evidence_artifacts=["artifact.png"],
            confidence="",
            mock=True,
        )

    with pytest.raises(ValueError, match="evidence_artifacts"):
        write_audio_contract(
            input_artifact="artifact.wav",
            out_dir=tmp_path / "bad2",
            duration=0.0,
            observations=["mock audio observation"],
            transcript="mock transcript",
            features={},
            summary="mock audio summary",
            evidence_artifacts=[],
            confidence="mock_only",
            mock=True,
        )


def test_capability_cli_lists_and_writes_gap_card(tmp_path: Path) -> None:
    runner = CliRunner()

    list_result = runner.invoke(app, ["capability-list"])
    assert list_result.exit_code == 0
    assert "image_understanding" in list_result.stdout
    assert "secret" not in list_result.stdout.lower()

    gap_result = runner.invoke(
        app,
        ["capability-gap", "--capability", "image_understanding", "--out", str(tmp_path)],
    )
    assert gap_result.exit_code == 0
    assert (tmp_path / "capability_gap_decision_card.yml").exists()


def test_mock_media_cli_requires_explicit_mock(tmp_path: Path) -> None:
    runner = CliRunner()

    blocked = runner.invoke(
        app,
        ["vision-contract", "--input", "artifact.png", "--out", str(tmp_path / "blocked")],
    )
    assert blocked.exit_code != 0
    assert not (tmp_path / "blocked" / "vision_result.yml").exists()

    allowed = runner.invoke(
        app,
        ["vision-contract", "--input", "artifact.png", "--out", str(tmp_path / "allowed"), "--mock"],
    )
    assert allowed.exit_code == 0
    assert (tmp_path / "allowed" / "vision_result.yml").exists()
