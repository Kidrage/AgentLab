from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from .ingestion_contract import IngestionContract, IngestionResult, QualityReport


MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".mp4", ".mov", ".avi", ".webm",
    ".mp3", ".wav", ".ogg", ".flac",
}
MEDIA_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".flac": "audio/flac",
}


def ingest_media(contract: IngestionContract, media_bytes: Optional[bytes] = None) -> IngestionResult:
    """Mock media ingestion via Supervision contract.

    Does NOT run actual ML models. Produces deterministic metadata.
    """
    source_path = Path(contract.source_path)
    ext = source_path.suffix.lower() if source_path.suffix else ""

    if media_bytes is None:
        if not source_path.exists():
            return IngestionResult(
                artifact_id=contract.artifact_id,
                source_path=contract.source_path,
                source_type="media",
                provider=contract.provider,
                status="failed",
                warnings=[f"Media file not found: {contract.source_path}"],
                requires_human_review=True,
            )
        media_bytes = source_path.read_bytes()

    content_hash = hashlib.sha256(media_bytes).hexdigest()[:16]
    mime_type = MEDIA_MIME_MAP.get(ext, "application/octet-stream")
    media_type = _classify_media_type(ext)

    if contract.provider == "supervision_mock":
        output_assets = [
            f"{contract.artifact_id}_vision_evidence.yml",
            f"{contract.artifact_id}_metadata.yml",
        ]
        warnings = _check_media_warnings(ext, len(media_bytes))
    else:
        return IngestionResult(
            artifact_id=contract.artifact_id,
            source_path=contract.source_path,
            source_type="media",
            provider=contract.provider,
            status="failed",
            warnings=[f"Provider {contract.provider} not supported for media ingestion"],
            requires_human_review=True,
        )

    return IngestionResult(
        artifact_id=contract.artifact_id,
        source_path=contract.source_path,
        source_type="media",
        provider=contract.provider,
        status="ingested",
        output_assets=output_assets,
        warnings=warnings,
        requires_human_review=len(warnings) > 0,
        content_hash=content_hash,
        quality_confidence=1.0 if not warnings else 0.7,
        metadata={"mime_type": mime_type, "media_type": media_type, "size_bytes": len(media_bytes)},
    )


def assess_media_quality(result: IngestionResult) -> QualityReport:
    """Deterministic quality check on media ingestion output."""
    warnings = list(result.warnings)
    passed, failed = 0, 0

    if result.output_assets:
        passed += 1
    else:
        failed += 1
        warnings.append("No output assets produced")

    if result.content_hash:
        passed += 1
    else:
        failed += 1
        warnings.append("Missing content hash")

    if result.metadata.get("size_bytes", 0) > 0:
        passed += 1
    else:
        failed += 1
        warnings.append("Media file appears to be empty")

    confidence = 1.0 if passed > 0 and failed == 0 else max(0.0, passed / (passed + failed))
    return QualityReport(
        artifact_id=result.artifact_id,
        confidence=round(confidence, 2),
        warnings=warnings,
        requires_human_review=failed > 0 or len(warnings) > 1,
        checks_passed=passed,
        checks_failed=failed,
    )


def _classify_media_type(ext: str) -> str:
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return "image"
    if ext in {".mp4", ".mov", ".avi", ".webm"}:
        return "video"
    if ext in {".mp3", ".wav", ".ogg", ".flac"}:
        return "audio"
    return "unknown"


def _check_media_warnings(ext: str, size_bytes: int) -> list[str]:
    warnings = []
    if ext not in MEDIA_EXTENSIONS:
        warnings.append(f"Unrecognized media extension: {ext}")
    if size_bytes == 0:
        warnings.append("Media file is empty")
    if size_bytes > 100_000_000:
        warnings.append("Media file exceeds 100MB; heavy processing may be required")
    return warnings
