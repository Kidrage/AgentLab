"""R3 Local Search CLI.

Provides `index`, `query`, and `status` subcommands for building,
searching, and inspecting the local search index from the terminal.
Uses only argparse — no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .indexer import build_index
from .query import query_index
from .storage import index_status, load_index, save_index


def _cmd_index(args: argparse.Namespace) -> None:
    """Build the local search index."""
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output

    print(f"Indexing project root: {root}")
    docs = build_index(root)
    print(f"Indexed {len(docs)} documents.")

    save_index(docs, output)
    print(f"Index written to: {output}")


def _cmd_query(args: argparse.Namespace) -> None:
    """Query the local search index."""
    root = Path(args.root).resolve()
    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = root / index_path

    docs = load_index(index_path)
    if not docs:
        print("No documents in index. Run 'index' first.", file=sys.stderr)
        sys.exit(1)

    source_cats: list[str] | None = None
    if args.source_category:
        source_cats = [args.source_category]

    results = query_index(
        docs,
        args.query,
        max_results=args.max_results,
        source_categories=source_cats,
    )

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"\n--- Result {i} (score: {r.score:.4f}) ---")
        print(f"  Path:     {r.path}")
        print(f"  Category: {r.source_category}")
        print(f"  Lines:    {r.line_start}-{r.line_end}")
        # Truncate snippet for display
        snippet = r.snippet
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        print(f"  Snippet:  {snippet}")


def _cmd_status(args: argparse.Namespace) -> None:
    """Show index status."""
    index_path = Path(args.index)
    if not index_path.is_absolute():
        index_path = Path.cwd() / index_path

    status = index_status(index_path)
    print(json.dumps(status, indent=2))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="local-search",
        description="AgentLab Local Search — stdlib-only text index",
    )
    sub = parser.add_subparsers(dest="command")

    # --- index ---
    idx = sub.add_parser("index", help="Build local search index")
    idx.add_argument(
        "--root", type=str, default=".", help="Project root directory"
    )
    idx.add_argument(
        "--output",
        type=str,
        default=".agentlab_runtime/local_search.jsonl",
        help="Output JSONL path (relative to --root)",
    )

    # --- query ---
    qry = sub.add_parser("query", help="Query local search index")
    qry.add_argument(
        "--root", type=str, default=".", help="Project root directory"
    )
    qry.add_argument(
        "--index",
        type=str,
        default=".agentlab_runtime/local_search.jsonl",
        help="Index JSONL path (relative to --root)",
    )
    qry.add_argument(
        "--query", "-q", type=str, required=True, help="Search query"
    )
    qry.add_argument(
        "--max-results", type=int, default=10, help="Max results to return"
    )
    qry.add_argument(
        "--source-category",
        type=str,
        default=None,
        help="Filter by source category",
    )

    # --- status ---
    sts = sub.add_parser("status", help="Show index status")
    sts.add_argument(
        "--index",
        type=str,
        default=".agentlab_runtime/local_search.jsonl",
        help="Index JSONL path",
    )

    args = parser.parse_args()

    if args.command == "index":
        _cmd_index(args)
    elif args.command == "query":
        _cmd_query(args)
    elif args.command == "status":
        _cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
