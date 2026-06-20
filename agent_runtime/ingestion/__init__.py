"""Repository ingestion helpers — document, code, media ingestion contracts."""

# M1-6: always-available ingestion contracts (no external deps)
from .ingestion_contract import IngestionContract, IngestionResult, QualityReport
from .document_ingestion import ingest_document, assess_document_quality
from .code_ingestion import ingest_code, assess_code_quality
from .media_ingestion import ingest_media, assess_media_quality

# Legacy: guarded imports — these have transitive deps that may not be installed
try:
    from .github_reader import GitHubRepoRef, parse_github_url, extract_github_urls, build_repo_manifest
    from .repo_manifest import RepoManifest
    from .clone_guard import evaluate_command, CloneGuardDecision
    from .resource_ledger import ResourceLedger, write_resource_ledger
    _LEGACY_AVAILABLE = True
except ImportError:
    _LEGACY_AVAILABLE = False
    GitHubRepoRef = None  # type: ignore
    parse_github_url = None  # type: ignore
    extract_github_urls = None  # type: ignore
    build_repo_manifest = None  # type: ignore
    RepoManifest = None  # type: ignore
    evaluate_command = None  # type: ignore
    CloneGuardDecision = None  # type: ignore
    ResourceLedger = None  # type: ignore
    write_resource_ledger = None  # type: ignore

__all__ = [
    # Legacy
    "GitHubRepoRef",
    "parse_github_url",
    "extract_github_urls",
    "build_repo_manifest",
    "RepoManifest",
    "evaluate_command",
    "CloneGuardDecision",
    "ResourceLedger",
    "write_resource_ledger",
    # M1-6
    "IngestionContract",
    "IngestionResult",
    "QualityReport",
    "ingest_document",
    "assess_document_quality",
    "ingest_code",
    "assess_code_quality",
    "ingest_media",
    "assess_media_quality",
]
