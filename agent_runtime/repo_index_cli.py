"""AgentLab optional repo indexer CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

try:
    from ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter
    from ingestion.repo_indexers.ledger import write_repo_index_artifacts
except ImportError:  # pragma: no cover
    from agent_runtime.ingestion.repo_indexers.codegraph_adapter import CodeGraphAdapter
    from agent_runtime.ingestion.repo_indexers.ledger import write_repo_index_artifacts


DEFAULT_CONFIG = {
    "repo_indexing": {
        "enabled": False,
        "default_indexer": "codegraph_cli_optional",
        "policy": {
            "require_local_checkout": True,
            "forbid_remote_clone": True,
            "forbid_repo_profile_indexing": True,
            "require_approval_for_indexing": True,
            "max_workspace_mb": 300,
            "max_index_seconds": 120,
        },
        "codegraph": {
            "command": "codegraph",
            "allow_if_missing": False,
            "index_args": ["init", "-i"],
            "query_args": {
                "explore": ["explore"],
                "search": ["search"],
                "node": ["node"],
                "callers": ["callers"],
                "callees": ["callees"],
                "impact": ["impact"],
            },
        },
        "codegraphcontext": {
            "enabled": False,
            "command": "cgc",
            "mode": "optional_future_provider",
        },
    }
}


def load_repo_index_config(root: Path) -> dict:
    path = root / "config" / "repo_indexing.yml"
    if not path.exists():
        return DEFAULT_CONFIG["repo_indexing"]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = dict(DEFAULT_CONFIG["repo_indexing"])
    merged.update(data.get("repo_indexing") or {})
    return merged


def output_dir(root: Path, project: str, task_id: str | None, override: Path | None) -> Path:
    if override is not None:
        return override
    if task_id:
        return root / "projects" / project / "runs" / task_id / "artifacts" / "repo_index"
    return root / "artifacts" / "repo_index"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentLab repo indexer adapter CLI.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--project", default="AgentLab")
    parser.add_argument("--task-id")
    parser.add_argument("--output-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--repo-path", type=Path, required=True)

    index = sub.add_parser("index")
    index.add_argument("--repo-path", type=Path, required=True)
    index.add_argument("--mode", default="repo_patch")
    index.add_argument("--dry-run", action="store_true", default=True)
    index.add_argument("--execute", dest="dry_run", action="store_false")
    index.add_argument("--approve-indexing", action="store_true")

    query = sub.add_parser("query")
    query.add_argument("--repo-path", type=Path, required=True)
    query.add_argument("--query", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_repo_index_config(args.root)
    adapter = CodeGraphAdapter(cfg)
    out = output_dir(args.root, args.project, args.task_id, args.output_dir)

    if args.command == "status":
        status = adapter.status(args.repo_path)
        write_repo_index_artifacts(out, task_id=args.task_id, repo_path=args.repo_path, status=status)
        print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "index":
        if not args.dry_run and not args.approve_indexing:
            result = adapter.index_repo(
                args.repo_path,
                dry_run=True,
                mode=args.mode,
                approve_indexing=False,
            )
            result.decision.action = "pending_approval"
            result.decision.reasons.append("non-dry-run requires --approve-indexing")
            write_repo_index_artifacts(out, task_id=args.task_id, repo_path=args.repo_path, result=result)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            return 1
        result = adapter.index_repo(
            args.repo_path,
            dry_run=args.dry_run,
            mode=args.mode,
            approve_indexing=args.approve_indexing,
        )
        write_repo_index_artifacts(out, task_id=args.task_id, repo_path=args.repo_path, result=result)
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "query":
        query_result = adapter.query(args.repo_path, args.query)
        status = adapter.status(args.repo_path)
        write_repo_index_artifacts(
            out,
            task_id=args.task_id,
            repo_path=args.repo_path,
            status=status,
            query_result=query_result,
        )
        print(json.dumps(query_result.as_dict(), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
