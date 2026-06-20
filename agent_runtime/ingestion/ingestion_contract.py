from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


SOURCE_TYPES = {"document", "code", "media", "unknown"}
PROVIDER_IDS = {"markitdown_mock", "mineru_mock", "codebase_memory_mock", "graphify_mock", "supervision_mock"}
STATUSES = {"created", "ingested", "quality_checked", "evidence_logged", "failed"}


@dataclass
class IngestionContract:
    """Defines what and how to ingest. Provider-agnostic contract."""
    artifact_id: str
    source_path: str
    source_type: str  # document | code | media
    provider: str     # markitdown_mock | mineru_mock | codebase_memory_mock | ...
    project_id: Optional[str] = None
    phase_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {SOURCE_TYPES}, got {self.source_type}")
        if self.provider not in PROVIDER_IDS:
            raise ValueError(f"provider must be one of {PROVIDER_IDS}, got {self.provider}")


@dataclass
class IngestionResult:
    """Result of an ingestion run."""
    artifact_id: str
    source_path: str
    source_type: str
    provider: str
    status: str  # created | ingested | quality_checked | evidence_logged | failed
    output_assets: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str = ""
    quality_confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "provider": self.provider,
            "status": self.status,
            "output_assets": self.output_assets,
            "evidence_paths": self.evidence_paths,
            "warnings": self.warnings,
            "requires_human_review": self.requires_human_review,
            "created_at": self.created_at,
            "content_hash": self.content_hash,
            "quality": {
                "confidence": self.quality_confidence,
                "warnings": self.warnings,
                "requires_human_review": self.requires_human_review,
            },
            "provenance": {
                "created_at": self.created_at,
                "content_hash": self.content_hash,
            },
        }


@dataclass
class QualityReport:
    """Deterministic quality assessment of ingestion output."""
    artifact_id: str
    confidence: float  # 0.0 - 1.0
    warnings: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    checks_passed: int = 0
    checks_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "requires_human_review": self.requires_human_review,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
        }
