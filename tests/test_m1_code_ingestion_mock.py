"""M1-6: Code ingestion mock — deterministic unit tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runtime.ingestion.ingestion_contract import IngestionContract
from agent_runtime.ingestion.code_ingestion import ingest_code, assess_code_quality


def test_ingest_code_codebase_memory_mock():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "test.py").write_text("print('hello')")
        (root / "README.md").write_text("# Test Repo")

        contract = IngestionContract(
            artifact_id="code_001",
            source_path=str(root),
            source_type="code",
            provider="codebase_memory_mock",
        )
        result = ingest_code(contract, repo_root=str(root))
        assert result.status == "ingested"
        assert result.provider == "codebase_memory_mock"
        assert len(result.output_assets) == 2
        assert result.content_hash


def test_ingest_code_graphify_mock():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "main.py").write_text("def main(): pass")

        contract = IngestionContract(
            artifact_id="code_002",
            source_path=str(root),
            source_type="code",
            provider="graphify_mock",
        )
        result = ingest_code(contract, repo_root=str(root))
        assert result.status == "ingested"
        assert result.provider == "graphify_mock"
        assert len(result.output_assets) == 2


def test_ingest_code_missing_path():
    contract = IngestionContract(
        artifact_id="code_missing",
        source_path="/tmp/definitely_missing_repo_m1_6",
        source_type="code",
        provider="codebase_memory_mock",
    )
    result = ingest_code(contract)
    assert result.status == "failed"
    assert result.requires_human_review is True


def test_ingest_code_unsupported_provider():
    with tempfile.TemporaryDirectory() as tmpdir:
        contract = IngestionContract(
            artifact_id="code_bad",
            source_path=str(tmpdir),
            source_type="code",
            provider="markitdown_mock",  # not a code provider
        )
        result = ingest_code(contract, repo_root=str(tmpdir))
        assert result.status == "failed"
        assert any("not supported" in w for w in result.warnings)


def test_ingest_code_no_python_files_warns():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "README.md").write_text("# No code here")

        contract = IngestionContract(
            artifact_id="code_nopy",
            source_path=str(root),
            source_type="code",
            provider="codebase_memory_mock",
        )
        result = ingest_code(contract, repo_root=str(root))
        assert any("No Python files" in w for w in result.warnings)


def test_assess_code_quality_pass():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="code_q",
        source_path="/tmp/repo",
        source_type="code",
        provider="codebase_memory_mock",
        status="ingested",
        output_assets=["code_q_graph.yml"],
        content_hash="def456",
    )
    q = assess_code_quality(result, symbol_count=5)
    assert q.confidence == 1.0
    assert q.checks_passed == 3


def test_assess_code_quality_no_symbols():
    from agent_runtime.ingestion.ingestion_contract import IngestionResult

    result = IngestionResult(
        artifact_id="code_empty",
        source_path="/tmp/repo",
        source_type="code",
        provider="codebase_memory_mock",
        status="ingested",
        output_assets=[],
        content_hash="",
    )
    q = assess_code_quality(result, symbol_count=0)
    assert q.confidence < 1.0
    assert q.checks_failed == 3
