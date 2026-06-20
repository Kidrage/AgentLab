from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .ingestion_contract import IngestionContract, IngestionResult, QualityReport


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def ingest_document(contract: IngestionContract, content: Optional[str] = None) -> IngestionResult:
    """Mock document ingestion via MarkItDown / MinerU contract.

    Reads from file if content is None. Provider must be markitdown_mock or mineru_mock.
    """
    source_path = Path(contract.source_path)
    if content is None:
        if not source_path.exists():
            return IngestionResult(
                artifact_id=contract.artifact_id,
                source_path=contract.source_path,
                source_type="document",
                provider=contract.provider,
                status="failed",
                warnings=[f"Source file not found: {contract.source_path}"],
                requires_human_review=True,
            )
        content = source_path.read_text(encoding="utf-8")

    content_hash = _hash_content(content)

    if contract.provider == "markitdown_mock":
        # Lightweight mock: extracts text, creates asset metadata
        output_assets = [
            f"{contract.artifact_id}_extracted.md",
            f"{contract.artifact_id}_asset.yml",
        ]
        warnings = _check_markitdown_warnings(content)
    elif contract.provider == "mineru_mock":
        # Heavy mock: PDF/OCR/table/formula extraction
        output_assets = [
            f"{contract.artifact_id}_extracted.md",
            f"{contract.artifact_id}_document_asset.yml",
            f"{contract.artifact_id}_quality_report.yml",
        ]
        warnings = _check_mineru_warnings(content)
    else:
        return IngestionResult(
            artifact_id=contract.artifact_id,
            source_path=contract.source_path,
            source_type="document",
            provider=contract.provider,
            status="failed",
            warnings=[f"Provider {contract.provider} not supported for document ingestion"],
            requires_human_review=True,
        )

    return IngestionResult(
        artifact_id=contract.artifact_id,
        source_path=contract.source_path,
        source_type="document",
        provider=contract.provider,
        status="ingested",
        output_assets=output_assets,
        warnings=warnings,
        requires_human_review=len(warnings) > 0,
        content_hash=content_hash,
        quality_confidence=1.0 if not warnings else 0.7,
    )


def assess_document_quality(result: IngestionResult, extracted_content: str = "") -> QualityReport:
    """Deterministic quality check on ingestion output."""
    warnings = list(result.warnings)
    passed, failed = 0, 0

    # Check: output assets exist
    if result.output_assets:
        passed += 1
    else:
        failed += 1
        warnings.append("No output assets produced")

    # Check: content hash present
    if result.content_hash:
        passed += 1
    else:
        failed += 1
        warnings.append("Missing content hash")

    # Check: extracted content not empty
    if extracted_content.strip():
        passed += 1
    else:
        failed += 1
        warnings.append("Extracted content is empty")

    confidence = 1.0 if passed > 0 and failed == 0 else max(0.0, passed / (passed + failed))
    return QualityReport(
        artifact_id=result.artifact_id,
        confidence=round(confidence, 2),
        warnings=warnings,
        requires_human_review=failed > 0 or len(warnings) > 1,
        checks_passed=passed,
        checks_failed=failed,
    )


def _check_markitdown_warnings(content: str) -> list[str]:
    warnings = []
    if len(content) < 10:
        warnings.append("Document content is very short (< 10 chars)")
    if "\x00" in content:
        warnings.append("Document contains null bytes")
    return warnings


def _check_mineru_warnings(content: str) -> list[str]:
    warnings = _check_markitdown_warnings(content)
    if len(content) > 1_000_000:
        warnings.append("Document exceeds 1MB; heavy extraction may be slow")
    return warnings
