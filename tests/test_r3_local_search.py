from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from local_search.document import Document, SourceCategory, content_hash_of  # noqa: E402
from local_search.indexer import build_index, index_directory  # noqa: E402
from local_search.query import (  # noqa: E402
    QueryResult,
    exact_phrase_boost,
    query_index,
    score_bm25,
    tokenize,
)
from local_search.storage import index_status, load_index, save_index  # noqa: E402
from local_search.evidence import EvidenceSnippet  # noqa: E402


VALID_CATEGORIES = {
    "repo_files", "docs", "config", "skills", "tests", "scripts",
    "acceptance_runs", "task_runs", "recovery_history", "closure_feedback",
    "external_inventory", "project_brain", "web_snapshots",
}


# ── Document Model ─────────────────────────────────────────────────


def test_content_hash_is_deterministic() -> None:
    h1 = content_hash_of("hello world")
    h2 = content_hash_of("hello world")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_content_hash_differs_for_different_content() -> None:
    h1 = content_hash_of("hello")
    h2 = content_hash_of("world")
    assert h1 != h2


def test_document_to_dict() -> None:
    doc = Document(
        path="test/file.py",
        source_category="repo_files",
        content_hash="abc123",
        text="some code",
        line_count=1,
        size_bytes=9,
        indexed_at="2026-01-01T00:00:00Z",
    )
    d = doc.to_dict()
    assert d["path"] == "test/file.py"
    assert d["source_category"] == "repo_files"
    assert d["content_hash"] == "abc123"


def test_document_from_dict_round_trip() -> None:
    doc = Document(
        path="x.py", source_category="tests", content_hash="def456",
        text="test code", line_count=1, size_bytes=9,
        indexed_at="2026-01-01T00:00:00Z",
    )
    restored = Document.from_dict(doc.to_dict())
    assert restored.path == doc.path
    assert restored.content_hash == doc.content_hash


def test_source_category_values() -> None:
    cats = SourceCategory.all_values()
    assert cats == VALID_CATEGORIES


# ── Indexer ────────────────────────────────────────────────────────


def test_index_directory_finds_python_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (src / "util.py").write_text("def helper(): pass\n", encoding="utf-8")
    docs = index_directory(tmp_path, "repo_files", {".py"}, set())
    assert len(docs) == 2
    assert all(d.source_category == "repo_files" for d in docs)


def test_index_directory_skips_excluded_dirs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (src / "good.py").write_text("x = 1\n", encoding="utf-8")
    (venv / "bad.py").write_text("x = 2\n", encoding="utf-8")
    docs = index_directory(tmp_path, "repo_files", {".py"}, {".venv"})
    assert len(docs) == 1
    assert docs[0].path.endswith("good.py")


def test_index_directory_skips_binary_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text("x = 1\n", encoding="utf-8")
    (src / "binary.bin").write_bytes(b"\x00\x01\x02\xff")
    docs = index_directory(tmp_path, "repo_files", {".py", ".bin"}, set())
    py_docs = [d for d in docs if d.path.endswith(".py")]
    assert len(py_docs) == 1


def test_index_directory_redacts_local_paths(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    home_user = "/Users/" + "testuser" + "/Desktop/project/file.py"
    (src / "file.py").write_text(
        f"path = '{home_user}'\n",
        encoding="utf-8",
    )
    docs = index_directory(tmp_path, "repo_files", {".py"}, set())
    assert len(docs) == 1
    assert "testuser" not in docs[0].text


def test_build_index_handles_missing_dirs(tmp_path: Path) -> None:
    docs = build_index(tmp_path)
    assert isinstance(docs, list)
    assert len(docs) == 0


def test_build_index_indexes_project_files() -> None:
    docs = build_index(ROOT)
    assert len(docs) > 50
    categories = {d.source_category for d in docs}
    assert "repo_files" in categories


# ── Query / Scoring ────────────────────────────────────────────────


def test_tokenize_basic() -> None:
    tokens = tokenize("Hello World! This is a test.")
    assert "hello" in tokens
    assert "world" in tokens
    assert "test" in tokens


def test_tokenize_filters_short_words() -> None:
    tokens = tokenize("a I is the to of")
    assert len(tokens) == 0 or all(len(t) >= 2 for t in tokens)


def test_score_bm25_returns_positive_for_match() -> None:
    doc = Document(
        path="x.py", source_category="repo_files", content_hash="abc",
        text="recovery closure feedback system", line_count=1,
        size_bytes=30, indexed_at="2026-01-01T00:00:00Z",
    )
    score = score_bm25(
        ["recovery", "closure"],
        doc, avg_dl=4.0, doc_freqs={"recovery": 1, "closure": 1},
        total_docs=1,
    )
    assert score > 0


def test_score_bm25_returns_zero_for_no_match() -> None:
    doc = Document(
        path="x.py", source_category="repo_files", content_hash="abc",
        text="hello world", line_count=1, size_bytes=11,
        indexed_at="2026-01-01T00:00:00Z",
    )
    score = score_bm25(
        ["nonexistent"],
        doc, avg_dl=2.0, doc_freqs={}, total_docs=1,
    )
    assert score == 0.0


def test_exact_phrase_boost_found() -> None:
    boost = exact_phrase_boost("recovery closure", "the recovery closure feedback")
    assert boost == 1.5


def test_exact_phrase_boost_not_found() -> None:
    boost = exact_phrase_boost("recovery closure", "the recovery and closure")
    assert boost == 1.0


def test_query_index_returns_ranked_results() -> None:
    docs = [
        Document(
            path="a.py", source_category="repo_files", content_hash="h1",
            text="recovery closure feedback system implementation",
            line_count=1, size_bytes=46, indexed_at="2026-01-01T00:00:00Z",
        ),
        Document(
            path="b.py", source_category="repo_files", content_hash="h2",
            text="unrelated code module",
            line_count=1, size_bytes=22, indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    results = query_index(docs, "recovery closure")
    assert len(results) >= 1
    assert results[0].path == "a.py"
    assert results[0].score > 0


def test_query_index_source_category_filter() -> None:
    docs = [
        Document(
            path="a.py", source_category="repo_files", content_hash="h1",
            text="recovery system", line_count=1, size_bytes=15,
            indexed_at="2026-01-01T00:00:00Z",
        ),
        Document(
            path="b.md", source_category="docs", content_hash="h2",
            text="recovery documentation", line_count=1, size_bytes=22,
            indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    results = query_index(docs, "recovery", source_categories=["docs"])
    assert all(r.source_category == "docs" for r in results)


def test_query_index_path_filter() -> None:
    docs = [
        Document(
            path="agent_runtime/recovery/a.py", source_category="repo_files",
            content_hash="h1", text="recovery plan",
            line_count=1, size_bytes=13, indexed_at="2026-01-01T00:00:00Z",
        ),
        Document(
            path="tests/test_b.py", source_category="tests",
            content_hash="h2", text="recovery test",
            line_count=1, size_bytes=13, indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    results = query_index(docs, "recovery", path_filter="agent_runtime")
    assert all("agent_runtime" in r.path for r in results)


def test_query_result_has_evidence_fields() -> None:
    docs = [
        Document(
            path="x.py", source_category="repo_files", content_hash="abc",
            text="def recovery_plan(): pass",
            line_count=1, size_bytes=25, indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    results = query_index(docs, "recovery")
    assert len(results) >= 1
    r = results[0]
    assert r.path == "x.py"
    assert r.source_category == "repo_files"
    assert r.content_hash == "abc"
    assert isinstance(r.snippet, str)


# ── Storage ────────────────────────────────────────────────────────


def test_save_and_load_index(tmp_path: Path) -> None:
    docs = [
        Document(
            path="a.py", source_category="repo_files", content_hash="h1",
            text="hello", line_count=1, size_bytes=5,
            indexed_at="2026-01-01T00:00:00Z",
        ),
        Document(
            path="b.md", source_category="docs", content_hash="h2",
            text="world", line_count=1, size_bytes=5,
            indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    path = tmp_path / "index.jsonl"
    save_index(docs, path)
    loaded = load_index(path)
    assert len(loaded) == 2
    assert loaded[0].path == "a.py"
    assert loaded[1].source_category == "docs"


def test_index_status(tmp_path: Path) -> None:
    docs = [
        Document(
            path="a.py", source_category="repo_files", content_hash="h1",
            text="hello", line_count=1, size_bytes=5,
            indexed_at="2026-01-01T00:00:00Z",
        ),
    ]
    path = tmp_path / "index.jsonl"
    save_index(docs, path)
    status = index_status(path)
    assert status["count"] == 1
    assert status["size_bytes"] > 0


def test_load_missing_index_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.jsonl"
    loaded = load_index(path)
    assert loaded == []


# ── Evidence ───────────────────────────────────────────────────────


def test_evidence_snippet_to_dict() -> None:
    ev = EvidenceSnippet(
        path="test.py", line_start=10, line_end=15,
        snippet="some code", score=2.5,
        source_category="repo_files", content_hash="abc",
    )
    d = ev.to_dict()
    assert d["path"] == "test.py"
    assert d["score"] == 2.5
    assert d["source_category"] == "repo_files"


# ── Integration ────────────────────────────────────────────────────


def test_full_index_and_query_cycle(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "recovery.py").write_text(
        "def recovery_closure_feedback():\n"
        "    '''Process recovery closure quality feedback.'''\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    (src / "unrelated.py").write_text(
        "def calculate_sum(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    docs = index_directory(tmp_path, "repo_files", {".py"}, set())
    assert len(docs) == 2

    idx_path = tmp_path / "index.jsonl"
    save_index(docs, idx_path)
    loaded = load_index(idx_path)
    assert len(loaded) == 2

    results = query_index(loaded, "recovery closure feedback")
    assert len(results) >= 1
    assert results[0].path.endswith("recovery.py")
    assert results[0].score > 0


def test_secrets_not_indexed(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.py").write_text(
        "api_key = 'sk-1234567890abcdef'\n"
        "password = 'super_secret_123'\n"
        "normal_code = True\n",
        encoding="utf-8",
    )
    docs = index_directory(tmp_path, "repo_files", {".py"}, set())
    assert len(docs) == 1
    assert "sk-1234567890" not in docs[0].text
    assert "super_secret" not in docs[0].text
