"""M1-6: Ingestion contract schemas — deterministic unit tests."""
from __future__ import annotations

from pathlib import Path

from agent_runtime.ingestion.ingestion_contract import (
    IngestionContract,
    IngestionResult,
    QualityReport,
    SOURCE_TYPES,
    PROVIDER_IDS,
)


def test_ingestion_contract_valid():
    c = IngestionContract(
        artifact_id="doc_001",
        source_path="/tmp/test.pdf",
        source_type="document",
        provider="markitdown_mock",
        project_id="TestProject",
    )
    assert c.artifact_id == "doc_001"
    assert c.source_type == "document"
    assert c.provider == "markitdown_mock"
    assert c.project_id == "TestProject"


def test_ingestion_contract_invalid_source_type_raises():
    try:
        IngestionContract(artifact_id="x", source_path="/x", source_type="bogus", provider="markitdown_mock")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_ingestion_contract_invalid_provider_raises():
    try:
        IngestionContract(artifact_id="x", source_path="/x", source_type="document", provider="evil_provider")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_ingestion_result_to_dict():
    r = IngestionResult(
        artifact_id="doc_001",
        source_path="/tmp/test.pdf",
        source_type="document",
        provider="markitdown_mock",
        status="ingested",
        output_assets=["doc_001_extracted.md"],
        content_hash="abc123",
        quality_confidence=1.0,
    )
    d = r.to_dict()
    assert d["artifact_id"] == "doc_001"
    assert d["status"] == "ingested"
    assert "quality" in d
    assert "provenance" in d
    assert d["quality"]["confidence"] == 1.0


def test_quality_report_to_dict():
    q = QualityReport(artifact_id="doc_001", confidence=0.9, warnings=["short content"], checks_passed=2, checks_failed=1)
    d = q.to_dict()
    assert d["artifact_id"] == "doc_001"
    assert d["confidence"] == 0.9
    assert d["checks_passed"] == 2


def test_all_source_types_valid():
    for st in SOURCE_TYPES:
        if st != "unknown":
            c = IngestionContract(artifact_id="x", source_path="/x", source_type=st, provider="markitdown_mock")
            assert c.source_type == st


def test_all_providers_valid():
    for pid in PROVIDER_IDS:
        c = IngestionContract(artifact_id="x", source_path="/x", source_type="document", provider=pid)
        assert c.provider == pid
