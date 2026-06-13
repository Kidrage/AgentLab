"""AgentLab search provider CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

try:
    from search.anysearch_adapter import AnySearchAdapter
    from search.ledger import write_search_artifacts
    from search.policy import load_search_config, search_artifact_dir
except ImportError:  # pragma: no cover
    from agent_runtime.search.anysearch_adapter import AnySearchAdapter
    from agent_runtime.search.ledger import write_search_artifacts
    from agent_runtime.search.policy import load_search_config, search_artifact_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentLab search provider adapter CLI.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", default="AgentLab")
    parser.add_argument("--task-id")
    parser.add_argument("--output-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    web = sub.add_parser("search-web", help="Run or plan a web search.")
    web.add_argument("query")
    web.add_argument("--max-results", type=int, default=None)
    web.add_argument("--vertical")
    web.add_argument("--mock", action="store_true")

    extract = sub.add_parser("extract-url", help="Extract URL text with AnySearch or local fallback.")
    extract.add_argument("url")
    extract.add_argument("--max-chars", type=int, default=None)
    extract.add_argument("--mock", action="store_true")

    batch = sub.add_parser("batch-search", help="Run or plan batch search from a query file.")
    batch.add_argument("queries_file", type=Path)
    batch.add_argument("--max-results", type=int, default=None)
    batch.add_argument("--mock", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_search_config(args.root)
    any_cfg = (config.get("search_providers") or {}).get("anysearch") or {}
    provider = AnySearchAdapter(any_cfg, mock=getattr(args, "mock", False))
    output_dir = search_artifact_dir(args.root, args.project, args.task_id, args.output_dir)

    if args.command == "search-web":
        max_results = args.max_results or int(any_cfg.get("max_results_default", 5) or 5)
        response = provider.search_web(args.query, max_results=max_results, vertical=args.vertical)
        write_search_artifacts(output_dir, task_id=args.task_id, action="web_search", response=response)
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "extract-url":
        max_chars = args.max_chars or int(any_cfg.get("max_url_extract_chars", 12000) or 12000)
        response = provider.extract_url(args.url, max_chars=max_chars)
        write_search_artifacts(output_dir, task_id=args.task_id, action="url_extract", response=response)
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "batch-search":
        queries = [line.strip() for line in args.queries_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        max_results = args.max_results or int(any_cfg.get("max_results_default", 5) or 5)
        response = provider.batch_search(queries, max_results=max_results)
        write_search_artifacts(output_dir, task_id=args.task_id, action="batch_search", response=response)
        print(json.dumps(response.as_dict(), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
