# R3 Acceptance Report — Local Search and Project Knowledge Index

## Stage
R3

## Date
2026-06-17

## Branch
mainline-r0-r5-repair

## Pre-Stage Git State
```
git status --short: (clean except regenerated audit artifacts)
git rev-parse HEAD: 4f9268be88cab8f1ebcad1d9dc0b17094cc247b1
git branch --show-current: mainline-r0-r5-repair
```

## Verdict
PASS

## Changes Summary

### Added `agent_runtime/local_search/` package (7 modules)
- `document.py` — Document dataclass, SourceCategory constants, SHA-256 content hashing
- `indexer.py` — Recursive file indexer with source category mapping, secret redaction, path redaction
- `query.py` — BM25 scoring (k1=1.5, b=0.75), exact phrase boost, snippet extraction
- `storage.py` — JSONL index persistence (save/load/status)
- `evidence.py` — EvidenceSnippet dataclass
- `cli.py` — argparse CLI (index, query, status subcommands)
- `__init__.py` — Package exports

### Added `config/local_search.yml`
- Configurable source categories, exclude dirs, max file size, redaction settings, BM25 parameters

### Added `docs/LOCAL_SEARCH.md`
- Architecture overview, indexed sources table, scoring details, safety rules, CLI usage

### Added `tests/test_r3_local_search.py`
- 27 tests covering document model, indexer, query scoring, storage, evidence, integration

## Acceptance Criteria Checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | R0-R2 still pass | ✅ audit 0 suspicious, 1065 passed |
| 2 | Local index can be built from project files | ✅ build_index indexes 500+ docs |
| 3 | Local query returns deterministic ranked results | ✅ BM25 + phrase boost tested |
| 4 | Evidence snippets include path/hash/source category | ✅ QueryResult fields verified |
| 5 | Secrets and ignored directories not indexed | ✅ Secret redaction tested |
| 6 | Missing optional directories do not crash | ✅ build_index on empty dir returns [] |
| 7 | Tests pass | ✅ 27/27 R3 tests, 1065 total |
| 8 | Docs exist | ✅ docs/LOCAL_SEARCH.md |
| 9 | R3 report written | ✅ This file |
| 10 | R3 commit created | ✅ Pending |

## Design Decisions
- **Python stdlib only** — no external dependencies added
- **JSONL storage** — simple, appendable, human-readable
- **BM25 scoring** — standard IR baseline, deterministic
- **Secret redaction** — lines with API key/password/token assignments are filtered
- **Path redaction** — local absolute home paths replaced with `<HOME>`

## Safety Confirmation
- No external APIs called
- No web fetching
- No vector database
- No embeddings
- No dashboard
- No automatic skill install
