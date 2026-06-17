from __future__ import annotations

"""Command-line interface for AgentLab web intelligence.

Subcommands
-----------
plan    Generate a research plan for a topic.
fetch   Fetch a URL (use ``--mock`` for offline testing).
brief   Generate a research brief (use ``--mock`` to use canned evidence).

Usage examples::

    python -m agent_runtime.intelligence.cli plan "Python asyncio patterns"
    python -m agent_runtime.intelligence.cli fetch --mock https://example.com
    python -m agent_runtime.intelligence.cli brief --mock "async patterns"
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .citation_ledger import CitationLedger, write_citation_ledger
from .research_brief import generate_brief
from .research_planner import plan_research
from .source_extractor import extract_content
from .web_fetcher import MockFetcher


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_plan(args: argparse.Namespace) -> None:
    """Handle the ``plan`` subcommand."""
    context = {}
    if args.focus:
        context["focus"] = args.focus
    if args.max_queries:
        context["max_queries"] = args.max_queries

    plan = plan_research(args.topic, context=context)

    output = {
        "topic": plan.topic,
        "queries": plan.queries,
        "planned_sources": [
            {"query": ps.query, "expected_type": ps.expected_type}
            for ps in plan.planned_sources
        ],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def _cmd_fetch(args: argparse.Namespace) -> None:
    """Handle the ``fetch`` subcommand."""
    url = args.url

    if args.mock:
        fetcher = MockFetcher()
        # Pre-register a handful of example responses
        fetcher.register(
            "https://example.com",
            status_code=200,
            content_type="text/html",
            body=(
                "<html><head><title>Example Domain</title></head>"
                "<body><h1>Example</h1><p>This domain is for use in "
                "illustrative examples in documents.</p></body></html>"
            ),
        )
        fetcher.register(
            "https://docs.python.org/3/library/asyncio.html",
            status_code=200,
            content_type="text/html",
            body=(
                "<html><head><title>asyncio — Asynchronous I/O</title></head>"
                "<body><p>asyncio is a library to write concurrent code "
                "using the async/await syntax.</p></body></html>"
            ),
        )
        result = fetcher.fetch(url)
    else:
        # Live fetch is intentionally unimplemented in this scaffold.
        print(
            json.dumps({"error": "Live fetch not implemented. Use --mock."}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Extract content from the fetched body
    extracted = extract_content(result.body, result.content_type)

    output = {
        "url": result.url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "content_hash": result.content_hash,
        "fetched_at": result.fetched_at,
        "error": result.error,
        "extracted": {
            "title": extracted.title,
            "body_text": extracted.body_text[:500],
            "word_count": extracted.word_count,
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

    # Optionally write to a ledger
    if args.ledger:
        ledger_path = Path(args.ledger)
        ledger = CitationLedger()
        ledger.append_from_fetch(
            url=result.url,
            body=result.body,
            extracted_text=extracted.body_text,
            fetch_status="mock" if args.mock else "ok",
            title=extracted.title,
        )
        write_citation_ledger(ledger, ledger_path)
        print(f"Ledger entry written to {ledger_path}", file=sys.stderr)


def _cmd_brief(args: argparse.Namespace) -> None:
    """Handle the ``brief`` subcommand."""
    topic = args.topic

    if args.mock:
        # Canned evidence for offline testing
        evidence = [
            {
                "url": "https://docs.python.org/3/library/asyncio.html",
                "title": "asyncio — Asynchronous I/O",
                "body_text": (
                    "asyncio is a library to write concurrent code using "
                    "the async/await syntax. It is used as a foundation for "
                    "multiple Python asynchronous frameworks."
                ),
                "source_quality_score": 85,
            },
            {
                "url": "https://realpython.com/async-io-python/",
                "title": "Async IO in Python: A Complete Walkthrough",
                "body_text": (
                    "Async IO is a style of concurrent programming that is "
                    "well-suited to IO-bound and high-concurrency workloads. "
                    "Python's asyncio library provides an event loop and "
                    "coroutine support."
                ),
                "source_quality_score": 72,
            },
            {
                "url": "https://github.com/python/cpython",
                "title": "CPython source code",
                "body_text": (
                    "The CPython interpreter reference implementation "
                    "includes the asyncio module as part of the standard "
                    "library since Python 3.4."
                ),
                "source_quality_score": 90,
            },
        ]
    else:
        print(
            json.dumps({"error": "Live brief not implemented. Use --mock."}),
            file=sys.stderr,
        )
        sys.exit(1)

    brief = generate_brief(topic, evidence)

    output = {
        "topic": brief.topic,
        "summary": brief.summary,
        "insufficient_evidence": brief.insufficient_evidence,
        "claims": [asdict(c) for c in brief.claims],
        "citations": [asdict(c) for c in brief.citations],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="agentlab-intelligence",
        description="AgentLab web intelligence CLI (mock-safe, stdlib-only)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- plan ---------------------------------------------------------------
    plan_parser = subparsers.add_parser("plan", help="Generate a research plan")
    plan_parser.add_argument("topic", help="Research topic (free text)")
    plan_parser.add_argument(
        "--focus", default=None, help="Optional sub-area focus"
    )
    plan_parser.add_argument(
        "--max-queries", type=int, default=None, help="Max queries (default 5)"
    )

    # --- fetch --------------------------------------------------------------
    fetch_parser = subparsers.add_parser("fetch", help="Fetch a URL")
    fetch_parser.add_argument("url", help="URL to fetch")
    fetch_parser.add_argument(
        "--mock", action="store_true", help="Use MockFetcher (offline)"
    )
    fetch_parser.add_argument(
        "--ledger", default=None, help="Path to write a citation ledger entry"
    )

    # --- brief --------------------------------------------------------------
    brief_parser = subparsers.add_parser("brief", help="Generate a research brief")
    brief_parser.add_argument("topic", help="Research topic (free text)")
    brief_parser.add_argument(
        "--mock", action="store_true", help="Use canned evidence (offline)"
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "plan": _cmd_plan,
        "fetch": _cmd_fetch,
        "brief": _cmd_brief,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
