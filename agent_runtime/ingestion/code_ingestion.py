from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from .ingestion_contract import IngestionContract, IngestionResult, QualityReport


def ingest_code(contract: IngestionContract, repo_root: Optional[str] = None) -> IngestionResult:
    """Mock codebase structural ingestion via codebase-memory / Graphify contract.

    Does NOT launch MCP servers. Produces deterministic mock output.
    """
    source_path = Path(contract.source_path)
    if repo_root is None:
        repo_root = str(source_path)

    if not source_path.exists():
        return IngestionResult(
            artifact_id=contract.artifact_id,
            source_path=contract.source_path,
            source_type="code",
            provider=contract.provider,
            status="failed",
            warnings=[f"Source path not found: {contract.source_path}"],
            requires_human_review=True,
        )

    content_summary = _scan_repo_structure(repo_root)
    content_hash = hashlib.sha256(content_summary.encode("utf-8")).hexdigest()[:16]

    if contract.provider == "codebase_memory_mock":
        output_assets = [
            f"{contract.artifact_id}_code_graph_asset.yml",
            f"{contract.artifact_id}_symbol_index.jsonl",
        ]
        warnings = _check_code_warnings(repo_root)
    elif contract.provider == "graphify_mock":
        output_assets = [
            f"{contract.artifact_id}_project_graph_asset.yml",
            f"{contract.artifact_id}_relationship_map.yml",
        ]
        warnings = _check_code_warnings(repo_root)
    else:
        return IngestionResult(
            artifact_id=contract.artifact_id,
            source_path=contract.source_path,
            source_type="code",
            provider=contract.provider,
            status="failed",
            warnings=[f"Provider {contract.provider} not supported for code ingestion"],
            requires_human_review=True,
        )

    return IngestionResult(
        artifact_id=contract.artifact_id,
        source_path=contract.source_path,
        source_type="code",
        provider=contract.provider,
        status="ingested",
        output_assets=output_assets,
        warnings=warnings,
        requires_human_review=len(warnings) > 0,
        content_hash=content_hash,
        quality_confidence=1.0 if not warnings else 0.7,
    )


def assess_code_quality(result: IngestionResult, symbol_count: int = 0) -> QualityReport:
    """Deterministic quality check on code ingestion output."""
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

    if symbol_count > 0:
        passed += 1
    else:
        failed += 1
        warnings.append("No symbols found in codebase")

    confidence = 1.0 if passed > 0 and failed == 0 else max(0.0, passed / (passed + failed))
    return QualityReport(
        artifact_id=result.artifact_id,
        confidence=round(confidence, 2),
        warnings=warnings,
        requires_human_review=failed > 0,
        checks_passed=passed,
        checks_failed=failed,
    )


def _scan_repo_structure(repo_root: str) -> str:
    """Minimal repo structure scan — no external tool calls."""
    root = Path(repo_root)
    parts = []
    try:
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in str(p) and ".git/" not in str(p):
                parts.append(str(p.relative_to(root)))
    except PermissionError:
        pass
    return "\n".join(parts[:200])  # cap at 200 files


def _check_code_warnings(repo_root: str) -> list[str]:
    warnings = []
    root = Path(repo_root)
    py_files = list(root.rglob("*.py"))
    if len(py_files) == 0:
        warnings.append("No Python files found in repo")
    if not (root / ".git").exists():
        warnings.append("No .git directory — may not be a git repository")
    return warnings
