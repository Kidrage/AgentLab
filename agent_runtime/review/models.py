from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ReviewTarget:
    task_id: str
    target_dir: Path
    handoff_path: Optional[Path] = None
    report_path: Optional[Path] = None
    changed_files: list[str] = field(default_factory=list)
    claimed_tests: list[str] = field(default_factory=list)


@dataclass
class ReviewEvidence:
    path: str
    exists: bool
    kind: str = "artifact"
    summary: str = ""
    size_bytes: int = 0


@dataclass
class ExploreSummary:
    task_id: str
    target_dir: str
    artifacts: list[ReviewEvidence] = field(default_factory=list)
    required_artifacts_present: list[str] = field(default_factory=list)
    required_artifacts_missing: list[str] = field(default_factory=list)
    optional_artifacts_present: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    claimed_tests: list[str] = field(default_factory=list)
    report_sections_present: list[str] = field(default_factory=list)
    report_sections_missing: list[str] = field(default_factory=list)
    text_evidence: dict[str, str] = field(default_factory=dict)
    output_path: Optional[str] = None


@dataclass
class ReviewFinding:
    finding_id: str
    severity: str
    category: str
    message: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    status: str = "fail"


@dataclass
class ReviewVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)


@dataclass
class RetryHandoff:
    path: Path
    failed_findings: list[ReviewFinding] = field(default_factory=list)
    required_fixes: list[str] = field(default_factory=list)
    reproduction_commands: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class ReviewReport:
    target: ReviewTarget
    summary: ExploreSummary
    findings: list[ReviewFinding]
    verdict: ReviewVerdict
    retry_handoff: Optional[RetryHandoff] = None
    markdown_path: Optional[Path] = None
    yaml_path: Optional[Path] = None


def to_plain_data(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_data(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    return value
