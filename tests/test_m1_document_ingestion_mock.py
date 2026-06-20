"""M1-6: Document ingestion mock — deterministic unit tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runtime.ingestion.ingestion_contract import IngestionContract
from agent_runtime.ingestion.document_ingestion import ingest_document, assess_document_quality


def test_ingest_document_markitdown_mock_with_content():
    contract = IngestionContract(
        artifact_id="doc_test",
        source_path="/tmp/does_not_exist_m1_6_test.pdf",
        source_type="document",
        provider="markitdown_mock",
    )
    result = ingest_document(contract, content="# Hello\n\nThis is a test document.")
    assert result.status == "ingested"
    assert result.provider == "markitdown_mock"
    assert len(result.output_assets) == 2
    assert result.content_hash
    assert result.quality_confidence == 1.0
    assert result.requires_human_review is False


def test_ingest_document_mineru_mock():
    contract = IngestionContract(
        artifact_id="doc_mineru",
        source_path="/tmp/does_not_exist_m1_6_test.pdf",
        source_type="document",
        provider="mineru_mock",
    )
    result = ingest_document(contract, content="PDF content with tables and formulas.")
    assert result.status == "ingested"
    assert result.provider == "mineru_mock"
    assert len(result.output_assets) == 3  # includes quality report
    assert result.content_hash


def test_ingest_document_missing_file():
    contract = IngestionContract(
        artifact_id="doc_missing",
        source_path="/tmp/definitely_missing_m1_6.pdf",
        source_type="document",
        provider="markitdown_mock",
    )
    result = ingest_document(contract)  # no content, file doesn't exist
    assert result.status == "failed"
    assert result.requires_human_review is True
    assert any("not found" in w for w in result.warnings)


def test_ingest_document_short_content_warns():
    contract = IngestionContract(
        artifact_id="doc_short",
        source_path="/tmp/x.pdf",
        source_type="document",
        provider="markitdown_mock",
    )
    result = ingest_document(contract, content="hi")
    assert result.requires_human_review is True
    assert any("short" in w.lower() for w in result.warnings)


def test_ingest_document_unsupported_provider():
    contract = IngestionContract(
        artifact_id="doc_bad",
        source_path="/tmp/x.pdf",
        source_type="document",
        provider="codebase_memory_mock",  # not a document provider
    )
    result = ingest_document(contract, content="test")
    assert result.status == "failed"
    assert any("not supported" in w for w in result.warnings)


def test_assess_document_quality_pass():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="doc_q",
        source_path="/tmp/x.pdf",
        source_type="document",
        provider="markitdown_mock",
        status="ingested",
        output_assets=["doc_q_extracted.md"],
        content_hash="abc123",
    )
    q = assess_document_quality(result, extracted_content="Hello world")
    assert q.confidence == 1.0
    assert q.checks_passed == 3
    assert q.checks_failed == 0


def test_assess_document_quality_empty_content():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="doc_empty",
        source_path="/tmp/x.pdf",
        source_type="document",
        provider="markitdown_mock",
        status="ingested",
        output_assets=[],
        content_hash="",
    )
    q = assess_document_quality(result, extracted_content="")
    assert q.confidence < 1.0
    assert q.checks_failed > 0


def test_ingest_document_from_real_tempfile():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("This is a test document with enough content to pass checks.")
        tmp_path = f.name

    try:
        contract = IngestionContract(
            artifact_id="doc_real_file",
            source_path=tmp_path,
            source_type="document",
            provider="markitdown_mock",
        )
        result = ingest_document(contract)
        assert result.status == "ingested"
        assert result.content_hash
    finally:
        Path(tmp_path).unlink(missing_ok=True)
