"""Deterministic S9 capability registry."""

from __future__ import annotations

from collections.abc import Iterable

from .capability_contract import CapabilityRecord, CapabilityStatus, RiskLevel


def _record(
    capability_id: str,
    display_name: str,
    description: str,
    modality: str,
    backend_type: str,
    status: CapabilityStatus,
    permissions: tuple[str, ...],
    risk_level: RiskLevel,
    evidence_required: tuple[str, ...],
    missing_backend_reason: str = "",
) -> CapabilityRecord:
    return CapabilityRecord(
        capability_id=capability_id,
        display_name=display_name,
        description=description,
        modality=modality,
        backend_type=backend_type,
        status=status,
        permissions=permissions,
        risk_level=risk_level,
        evidence_required=evidence_required,
        missing_backend_reason=missing_backend_reason,
    )


BUILTIN_CAPABILITIES: tuple[CapabilityRecord, ...] = (
    _record("audio_analysis", "Audio Analysis", "Describe audio features from an explicit artifact contract.", "audio", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "evidence_artifacts"), "no local audio analysis backend configured"),
    _record("audio_transcription", "Audio Transcription", "Transcribe audio from an explicit artifact contract.", "audio", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "transcript", "evidence_artifacts"), "no local transcription backend configured"),
    _record("browser_fetch", "Browser Fetch", "Fetch browser-readable web content only when network policy allows it.", "web", "adapter", CapabilityStatus.REQUIRES_APPROVAL, ("network",), RiskLevel.HIGH, ("url", "fetched_at")),
    _record("database_query", "Database Query", "Query an explicitly configured database in read-only mode.", "database", "adapter", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.HIGH, ("query", "result_artifact"), "no database connection configured"),
    _record("docx_read", "DOCX Read", "Extract text from DOCX artifacts.", "document", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "extracted_text"), "no document parser backend configured"),
    _record("filesystem_read", "Filesystem Read", "Read files inside approved project paths.", "filesystem", "builtin", CapabilityStatus.AVAILABLE, ("read",), RiskLevel.LOW, ("path",)),
    _record("filesystem_write", "Filesystem Write", "Write deterministic artifacts to explicit output paths.", "filesystem", "builtin", CapabilityStatus.REQUIRES_APPROVAL, ("write",), RiskLevel.HIGH, ("path", "content_hash")),
    _record("git_ops", "Git Operations", "Inspect or modify git state when explicitly approved.", "git", "builtin", CapabilityStatus.REQUIRES_APPROVAL, ("shell", "write"), RiskLevel.HIGH, ("command", "stdout")),
    _record("github_ops", "GitHub Operations", "Use GitHub APIs only with explicit user approval and configured auth.", "github", "adapter", CapabilityStatus.MISSING_BACKEND, ("network", "write"), RiskLevel.HIGH, ("request", "response_artifact"), "no GitHub backend configured in capability fabric"),
    _record("ide_handoff", "IDE Handoff", "Prepare handoff artifacts for a local IDE without taking control.", "ide", "artifact", CapabilityStatus.AVAILABLE, ("write",), RiskLevel.MEDIUM, ("handoff_artifact",)),
    _record("image_understanding", "Image Understanding", "Describe visual artifacts using a configured vision backend or mock contract.", "vision", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "observations", "evidence_artifacts"), "no local vision backend configured"),
    _record("ocr", "OCR", "Extract text from image or document artifacts.", "vision", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "extracted_text"), "no OCR backend configured"),
    _record("openclaw_notify", "OpenClaw Notify", "Write or send OpenClaw notification artifacts only when configured.", "notification", "adapter", CapabilityStatus.MISSING_BACKEND, ("network", "write"), RiskLevel.HIGH, ("message", "delivery_status"), "no OpenClaw notification backend configured"),
    _record("pdf_read", "PDF Read", "Extract text and structural metadata from PDF artifacts.", "document", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "pages", "extracted_text"), "no PDF parser backend configured"),
    _record("shell_command", "Shell Command", "Run a shell command only after explicit approval.", "shell", "builtin", CapabilityStatus.REQUIRES_APPROVAL, ("shell",), RiskLevel.HIGH, ("command", "exit_code", "stdout")),
    _record("spreadsheet_read", "Spreadsheet Read", "Extract rows and sheets from spreadsheet artifacts.", "document", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "tables"), "no spreadsheet parser backend configured"),
    _record("video_understanding", "Video Understanding", "Describe video artifacts using a configured backend or mock contract.", "video", "mock_contract", CapabilityStatus.MISSING_BACKEND, ("read",), RiskLevel.MEDIUM, ("input_artifact", "observations", "evidence_artifacts"), "no video backend configured"),
    _record("web_search", "Web Search", "Search the web only when network policy allows it.", "web", "adapter", CapabilityStatus.REQUIRES_APPROVAL, ("network",), RiskLevel.HIGH, ("query", "result_artifact")),
)


class CapabilityRegistry:
    def __init__(self, capabilities: Iterable[CapabilityRecord]) -> None:
        self._capabilities: dict[str, CapabilityRecord] = {}
        for capability in capabilities:
            if capability.capability_id in self._capabilities:
                raise ValueError(f"duplicate capability_id: {capability.capability_id}")
            self._capabilities[capability.capability_id] = capability

    def get(self, capability_id: str) -> CapabilityRecord:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability_id: {capability_id}") from exc

    def to_sorted_records(self) -> list[CapabilityRecord]:
        return [self._capabilities[key] for key in sorted(self._capabilities)]

    def to_sorted_dicts(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self.to_sorted_records()]


def create_builtin_registry() -> CapabilityRegistry:
    return CapabilityRegistry(BUILTIN_CAPABILITIES)
