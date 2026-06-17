from __future__ import annotations

"""Source quality scoring for AgentLab web intelligence.

Each fetched page is scored on a 0-100 scale using simple, transparent
heuristics: domain trust, content length, and title presence.  The
scoring function is deterministic and has no external dependencies.
"""

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .source_extractor import ExtractedContent


# ---------------------------------------------------------------------------
# Trusted domains
# ---------------------------------------------------------------------------

TRUSTED_DOMAINS: frozenset[str] = frozenset({
    # Language & runtime docs
    "docs.python.org",
    "python.org",
    "nodejs.org",
    "developer.mozilla.org",
    "golang.org",
    "go.dev",
    "ruby-doc.org",
    "rust-lang.org",
    "doc.rust-lang.org",
    # Package registries & code hosting
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "pypi.org",
    "crates.io",
    "npmjs.com",
    # Standards & specifications
    "w3.org",
    "ietf.org",
    "rfc-editor.org",
    "whatwg.org",
    # Well-known references
    "stackoverflow.com",
    "stackexchange.com",
    "en.wikipedia.org",
    "wikipedia.org",
    "arxiv.org",
    # Cloud / infra docs
    "docs.aws.amazon.com",
    "cloud.google.com",
    "learn.microsoft.com",
    "kubernetes.io",
    "docker.com",
    # Security
    "owasp.org",
    "cve.mitre.org",
    "nvd.nist.gov",
})


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceQuality:
    """Quality assessment for a single web source."""

    url: str
    domain: str
    score: int            # 0 – 100
    reasons: list[str]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Return the lower-cased hostname from *url*, or empty string."""
    try:
        hostname = urlparse(url).hostname or ""
        return hostname.lower()
    except Exception:
        return ""


def rank_source(url: str, content: ExtractedContent) -> SourceQuality:
    """Score *content* fetched from *url* and return a ``SourceQuality``.

    Scoring rubric (max 100):
    +-----------+------------------------------------------+
    | Points    | Criterion                                |
    +===========+==========================================+
    | 0 – 40    | Domain trust                             |
    | 0 – 35    | Body word count (scales logarithmically) |
    | 0 – 15    | Title presence and length                |
    | 0 – 10    | Content-type bonus (HTML / Markdown)     |
    +-----------+------------------------------------------+
    """
    domain = _extract_domain(url)
    score = 0
    reasons: list[str] = []

    # --- Domain trust (0-40) ------------------------------------------------
    if domain in TRUSTED_DOMAINS:
        score += 40
        reasons.append(f"Trusted domain: {domain}")
    else:
        # Partial credit for subdomains of trusted roots
        for trusted in TRUSTED_DOMAINS:
            if domain.endswith("." + trusted):
                score += 25
                reasons.append(f"Subdomain of trusted root: {trusted}")
                break
        else:
            reasons.append(f"Unrecognised domain: {domain}")

    # --- Word count (0-35) --------------------------------------------------
    wc = content.word_count
    if wc >= 500:
        score += 35
        reasons.append(f"Substantial content: {wc} words")
    elif wc >= 200:
        score += 25
        reasons.append(f"Moderate content: {wc} words")
    elif wc >= 50:
        score += 15
        reasons.append(f"Short content: {wc} words")
    elif wc > 0:
        score += 5
        reasons.append(f"Very short content: {wc} words")
    else:
        reasons.append("Empty body — no content to evaluate")

    # --- Title presence (0-15) ----------------------------------------------
    if content.title:
        if 3 <= len(content.title) <= 200:
            score += 15
            reasons.append(f"Good title: \"{content.title[:60]}\"")
        else:
            score += 8
            reasons.append("Title present but unusual length")
    else:
        reasons.append("No title found")

    # --- Content type bonus (0-10) ------------------------------------------
    ct = content.content_type.lower()
    if "html" in ct:
        score += 10
        reasons.append("Structured HTML content")
    elif "markdown" in ct:
        score += 8
        reasons.append("Markdown content")
    elif "json" in ct:
        score += 5
        reasons.append("JSON content")
    else:
        score += 3
        reasons.append(f"Content type: {ct or 'unknown'}")

    # Clamp
    score = max(0, min(100, score))

    return SourceQuality(
        url=url,
        domain=domain,
        score=score,
        reasons=reasons,
    )
