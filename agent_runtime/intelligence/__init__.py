from __future__ import annotations

"""AgentLab web intelligence — safe, limited, deterministic web research.

This package provides a stdlib-only scaffold for web research that can
be tested entirely offline via mock mode.  Every public symbol from the
sibling modules is re-exported here for convenient star-imports.
"""

# -- web_policy --------------------------------------------------------------
from .web_policy import (
    URLValidation,
    is_private_ip,
    load_web_policy,
    validate_url,
)

# -- web_fetcher -------------------------------------------------------------
from .web_fetcher import (
    FetchResult,
    MockFetcher,
    WebFetcher,
)

# -- web_cache ---------------------------------------------------------------
from .web_cache import (
    CachedSource,
    cache_key_for_url,
    clear_cache,
    list_cached_urls,
    load_from_cache,
    save_to_cache,
)

# -- source_extractor --------------------------------------------------------
from .source_extractor import (
    ExtractedContent,
    extract_content,
    extract_from_html,
    extract_from_markdown,
    extract_from_text,
)

# -- source_ranker -----------------------------------------------------------
from .source_ranker import (
    TRUSTED_DOMAINS,
    SourceQuality,
    rank_source,
)

# -- research_planner --------------------------------------------------------
from .research_planner import (
    PlannedSource,
    ResearchPlan,
    plan_research,
)

# -- research_brief ----------------------------------------------------------
from .research_brief import (
    Citation,
    Claim,
    ResearchBrief,
    generate_brief,
)

# -- citation_ledger ---------------------------------------------------------
from .citation_ledger import (
    CitationEntry,
    CitationLedger,
    load_citation_ledger,
    write_citation_ledger,
)

__all__ = [
    # web_policy
    "URLValidation",
    "is_private_ip",
    "load_web_policy",
    "validate_url",
    # web_fetcher
    "FetchResult",
    "MockFetcher",
    "WebFetcher",
    # web_cache
    "CachedSource",
    "cache_key_for_url",
    "clear_cache",
    "list_cached_urls",
    "load_from_cache",
    "save_to_cache",
    # source_extractor
    "ExtractedContent",
    "extract_content",
    "extract_from_html",
    "extract_from_markdown",
    "extract_from_text",
    # source_ranker
    "TRUSTED_DOMAINS",
    "SourceQuality",
    "rank_source",
    # research_planner
    "PlannedSource",
    "ResearchPlan",
    "plan_research",
    # research_brief
    "Citation",
    "Claim",
    "ResearchBrief",
    "generate_brief",
    # citation_ledger
    "CitationEntry",
    "CitationLedger",
    "load_citation_ledger",
    "write_citation_ledger",
]
