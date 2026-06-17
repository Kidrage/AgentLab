from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from intelligence.web_policy import (  # noqa: E402
    URLValidation,
    is_private_ip,
    load_web_policy,
    validate_url,
)
from intelligence.web_fetcher import FetchResult, MockFetcher  # noqa: E402
from intelligence.web_cache import (  # noqa: E402
    CachedSource,
    cache_key_for_url,
    load_from_cache,
    save_to_cache,
)
from intelligence.source_extractor import (  # noqa: E402
    ExtractedContent,
    extract_content,
    extract_from_html,
    extract_from_markdown,
    extract_from_text,
)
from intelligence.source_ranker import rank_source  # noqa: E402
from intelligence.research_planner import plan_research  # noqa: E402
from intelligence.research_brief import generate_brief  # noqa: E402
from intelligence.citation_ledger import (  # noqa: E402
    CitationEntry,
    CitationLedger,
    load_citation_ledger,
    write_citation_ledger,
)


# ── URL Safety Policy ─────────────────────────────────────────────


def test_validates_public_https_url() -> None:
    result = validate_url("https://docs.python.org/3/library/index.html")
    assert result.allowed is True


def test_blocks_localhost() -> None:
    result = validate_url("http://localhost:8080/api")
    assert result.allowed is False
    reason = result.reason.lower()
    assert "localhost" in reason or "private" in reason or "loopback" in reason


def test_blocks_127_loopback() -> None:
    result = validate_url("http://127.0.0.1:3000/test")
    assert result.allowed is False


def test_blocks_10_private_network() -> None:
    result = validate_url("http://10.0.1.5/internal")
    assert result.allowed is False


def test_blocks_172_private_network() -> None:
    result = validate_url("http://172.16.0.1/admin")
    assert result.allowed is False


def test_blocks_192_168_private_network() -> None:
    result = validate_url("http://192.168.1.100/router")
    assert result.allowed is False


def test_blocks_link_local() -> None:
    result = validate_url("http://169.254.1.1/metadata")
    assert result.allowed is False


def test_blocks_ipv6_loopback() -> None:
    result = validate_url("http://[::1]:8080/api")
    assert result.allowed is False


def test_blocks_file_scheme() -> None:
    result = validate_url("file:///etc/passwd")
    assert result.allowed is False


def test_blocks_ftp_scheme() -> None:
    result = validate_url("ftp://example.com/secret")
    assert result.allowed is False


def test_blocks_ssh_scheme() -> None:
    result = validate_url("ssh://user@host/path")
    assert result.allowed is False


def test_blocks_data_scheme() -> None:
    result = validate_url("data:text/html,<script>alert(1)</script>")
    assert result.allowed is False


def test_blocks_javascript_scheme() -> None:
    result = validate_url("javascript:alert(1)")
    assert result.allowed is False


def test_blocks_empty_url() -> None:
    result = validate_url("")
    assert result.allowed is False


def test_is_private_ip_detection() -> None:
    assert is_private_ip("127.0.0.1") is True
    assert is_private_ip("10.0.0.1") is True
    assert is_private_ip("172.16.0.1") is True
    assert is_private_ip("192.168.1.1") is True
    assert is_private_ip("169.254.1.1") is True
    assert is_private_ip("::1") is True


def test_load_web_policy_defaults() -> None:
    policy = load_web_policy(None)
    assert policy["enabled"] is False
    assert policy["mode"] == "mock_first"


# ── Mock Fetcher ───────────────────────────────────────────────────


def test_mock_fetcher_returns_registered_url() -> None:
    fetcher = MockFetcher()
    fetcher.register(
        "https://example.com/test",
        body="<html><body>Hello World</body></html>",
        content_type="text/html",
        status_code=200,
    )
    result = fetcher.fetch("https://example.com/test")
    assert result.status_code == 200
    assert "Hello World" in result.body
    assert result.content_hash is not None


def test_mock_fetcher_returns_404_for_unknown() -> None:
    fetcher = MockFetcher()
    result = fetcher.fetch("https://unknown.example.com/missing")
    assert result.status_code == 404


def test_fetch_result_has_required_fields() -> None:
    result = FetchResult(
        url="https://example.com",
        status_code=200,
        content_type="text/html",
        body="test",
        content_hash="abc123",
        fetched_at="2026-01-01T00:00:00Z",
        error=None,
    )
    assert result.url == "https://example.com"
    assert result.error is None


# ── Web Cache ──────────────────────────────────────────────────────


def test_cache_save_and_load(tmp_path: Path) -> None:
    source = CachedSource(
        url="https://example.com/page",
        content_hash="hash123",
        content_type="text/html",
        body="<p>cached content</p>",
        cached_at="2026-01-01T00:00:00Z",
        fetch_status=200,
    )
    cache_dir = tmp_path / "cache"
    save_to_cache(source, cache_dir)
    loaded = load_from_cache("https://example.com/page", cache_dir)
    assert loaded is not None
    assert loaded.content_hash == "hash123"
    assert loaded.body == "<p>cached content</p>"


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    result = load_from_cache("https://nonexistent.example.com", cache_dir)
    assert result is None


def test_cache_key_is_deterministic() -> None:
    key1 = cache_key_for_url("https://example.com/page")
    key2 = cache_key_for_url("https://example.com/page")
    assert key1 == key2
    assert len(key1) == 64  # SHA-256 hex


# ── Content Extraction ─────────────────────────────────────────────


def test_extract_from_html() -> None:
    html = "<html><head><title>Test Page</title></head><body><p>Hello <b>world</b></p></body></html>"
    result = extract_from_html(html)
    assert "Hello" in result.body_text
    assert "world" in result.body_text
    assert result.content_type == "text/html"


def test_extract_from_html_strips_scripts() -> None:
    html = "<html><body><script>var x = 1;</script><p>Content</p></body></html>"
    result = extract_from_html(html)
    assert "var x" not in result.body_text
    assert "Content" in result.body_text


def test_extract_from_markdown() -> None:
    md = "# Title\n\nSome **bold** text and [a link](https://example.com).\n"
    result = extract_from_markdown(md)
    assert "Title" in result.body_text
    assert "bold" in result.body_text
    assert result.content_type == "text/markdown"


def test_extract_from_text() -> None:
    text = "Plain text content with multiple words."
    result = extract_from_text(text)
    assert result.body_text == text
    assert result.word_count > 0


def test_extract_content_dispatches() -> None:
    html_result = extract_content("<p>test</p>", "text/html")
    assert html_result.content_type == "text/html"
    md_result = extract_content("# test", "text/markdown")
    assert md_result.content_type == "text/markdown"
    txt_result = extract_content("plain", "text/plain")
    assert txt_result.content_type == "text/plain"


# ── Source Quality Ranking ─────────────────────────────────────────


def test_rank_trusted_domain_scores_high() -> None:
    content = ExtractedContent(
        title="Python Documentation",
        body_text="word " * 500,
        content_type="text/html",
        word_count=500,
        content_hash="abc",
    )
    quality = rank_source("https://docs.python.org/3/library/os.html", content)
    assert quality.score >= 50


def test_rank_unknown_domain_scores_lower() -> None:
    content = ExtractedContent(
        title="",
        body_text="short",
        content_type="text/plain",
        word_count=1,
        content_hash="abc",
    )
    quality = rank_source("https://unknown-site-12345.com/page", content)
    assert quality.score < 50


# ── Research Planning ──────────────────────────────────────────────


def test_plan_research_generates_queries() -> None:
    plan = plan_research("AgentLab local search index")
    assert len(plan.queries) >= 2
    assert plan.topic == "AgentLab local search index"


def test_plan_research_with_context() -> None:
    plan = plan_research("recovery closure feedback", context={"project": "AgentLab"})
    assert len(plan.queries) >= 2


# ── Research Brief ─────────────────────────────────────────────────


def test_generate_brief_with_sufficient_evidence() -> None:
    evidence = [
        {"url": "https://example.com/a", "title": "Source A", "snippet": "First finding"},
        {"url": "https://example.com/b", "title": "Source B", "snippet": "Second finding"},
        {"url": "https://example.com/c", "title": "Source C", "snippet": "Third finding"},
    ]
    brief = generate_brief("test topic", evidence)
    assert brief.topic == "test topic"
    assert brief.insufficient_evidence is False
    assert len(brief.citations) == 3


def test_generate_brief_insufficient_evidence() -> None:
    evidence = [
        {"url": "https://example.com/a", "title": "Only source", "snippet": "One finding"},
    ]
    brief = generate_brief("test topic", evidence)
    assert brief.insufficient_evidence is True


def test_generate_brief_empty_evidence() -> None:
    brief = generate_brief("test topic", [])
    assert brief.insufficient_evidence is True


# ── Citation Ledger ────────────────────────────────────────────────


def test_citation_ledger_append_and_serialize() -> None:
    ledger = CitationLedger()
    entry = CitationEntry(
        url="https://example.com/page",
        fetched_at="2026-01-01T00:00:00Z",
        fetch_status=200,
        content_hash="hash1",
        extracted_text_hash="hash2",
        title="Test Page",
    )
    ledger.append(entry)
    assert len(ledger.entries) == 1

    jsonl = ledger.to_jsonl()
    restored = CitationLedger.from_jsonl(jsonl)
    assert len(restored.entries) == 1
    assert restored.entries[0].url == "https://example.com/page"


def test_citation_ledger_write_and_load(tmp_path: Path) -> None:
    ledger = CitationLedger()
    ledger.append(CitationEntry(
        url="https://example.com/a",
        fetched_at="2026-01-01T00:00:00Z",
        fetch_status=200,
        content_hash="h1",
        extracted_text_hash="h2",
        title="Page A",
    ))
    path = tmp_path / "citations.jsonl"
    write_citation_ledger(ledger, path)
    loaded = load_citation_ledger(path)
    assert len(loaded.entries) == 1


# ── Offline Operation ──────────────────────────────────────────────


def test_no_real_internet_required() -> None:
    """All R4 operations work without any network access."""
    fetcher = MockFetcher()
    fetcher.register(
        "https://example.com/doc",
        body="# AgentLab Docs\n\nRecovery closure feedback system.",
        content_type="text/markdown",
        status_code=200,
    )
    result = fetcher.fetch("https://example.com/doc")
    assert result.status_code == 200
    extracted = extract_content(result.body, result.content_type)
    assert "Recovery" in extracted.body_text
    quality = rank_source(result.url, extracted)
    assert quality.score >= 0
