from __future__ import annotations

import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

P1_CD_PYTHON_FILES = [
    "agent_runtime/search/provider.py",
    "agent_runtime/search/anysearch_adapter.py",
    "agent_runtime/search/local_url_reader.py",
    "agent_runtime/search/ledger.py",
    "agent_runtime/search/policy.py",
    "agent_runtime/search_cli.py",
    "agent_runtime/ingestion/repo_indexers/base.py",
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py",
    "agent_runtime/ingestion/repo_indexers/ledger.py",
    "agent_runtime/ingestion/repo_indexers/semantic_library.py",
    "agent_runtime/repo_index_cli.py",
    "agent_runtime/intelligence_plans.py",
]

P1_CD_YAML_FILES = [
    "config/search_providers.yml",
    "config/repo_indexing.yml",
]

MIN_LINE_COUNTS = {
    "agent_runtime/search/provider.py": 20,
    "agent_runtime/search/anysearch_adapter.py": 50,
    "agent_runtime/search/local_url_reader.py": 40,
    "agent_runtime/search/ledger.py": 50,
    "agent_runtime/search/policy.py": 20,
    "agent_runtime/search_cli.py": 40,
    "agent_runtime/ingestion/repo_indexers/base.py": 20,
    "agent_runtime/ingestion/repo_indexers/codegraph_adapter.py": 50,
    "agent_runtime/ingestion/repo_indexers/ledger.py": 50,
    "agent_runtime/ingestion/repo_indexers/semantic_library.py": 15,
    "agent_runtime/repo_index_cli.py": 50,
    "agent_runtime/intelligence_plans.py": 50,
}


def test_p1_cd_python_files_are_parseable() -> None:
    for relative_path in P1_CD_PYTHON_FILES:
        path = ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))


def test_p1_cd_yaml_files_are_loadable() -> None:
    for relative_path in P1_CD_YAML_FILES:
        path = ROOT / relative_path
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), relative_path


def test_no_p1_cd_python_file_is_single_line_compressed() -> None:
    for relative_path, minimum_lines in MIN_LINE_COUNTS.items():
        path = ROOT / relative_path
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count > minimum_lines, f"{relative_path} has only {line_count} lines"

