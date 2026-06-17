# Local Search and Project Knowledge Index (R3)

## Overview

R3 adds a deterministic, lightweight, local-first text index so AgentLab can search
its own repository, docs, skills, task histories, recovery histories, acceptance
reports, and project memory without external APIs.

This is NOT semantic vector search. This is a deterministic BM25-like text index
using only the Python standard library.

## Architecture

```
agent_runtime/local_search/
  __init__.py       # Package exports
  document.py       # Document model, content hashing
  indexer.py        # File system indexer with source category mapping
  query.py          # BM25 scoring, phrase boost, snippet extraction
  storage.py        # JSONL index persistence
  evidence.py       # Evidence snippet dataclass
  cli.py            # CLI (argparse-based)
```

## Indexed Sources

| Source Category | Directories | Suffixes |
|----------------|-------------|----------|
| `repo_files` | `agent_runtime/` | `.py`, `.md`, `.sh` |
| `docs` | `docs/` | `.md` |
| `config` | `config/` | `.yml`, `.yaml` |
| `skills` | `agent_runtime/skills/` | `.py` |
| `tests` | `tests/` | `.py` |
| `scripts` | `scripts/` | `.py`, `.sh` |
| `acceptance_runs` | `acceptance_runs/` | `.md`, `.yml`, `.yaml` |
| `recovery_history` | `projects/*/runs/*/recovery*` | `.jsonl`, `.json` |
| `closure_feedback` | `projects/*/runs/*/closure*` | `.json`, `.md` |
| `project_brain` | `projects/*/project_brain/*` | `.md`, `.yml` |

Missing directories are skipped with a warning.

## Scoring

- **BM25** with k1=1.5, b=0.75
- **Exact phrase boost**: 1.5× if the query phrase appears verbatim
- **Snippet extraction**: ~200 chars around best match, with line numbers

## Safety

- Secrets are not indexed (lines with API key/secret/password/token assignments are skipped)
- Local absolute paths are redacted to `<HOME>` in indexed text
- Binary files and files >1MB are skipped
- Generated/ignored directories (`.venv`, `__pycache__`, `.git`, etc.) are excluded

## CLI

```bash
# Build index
python -m agent_runtime.local_search.cli index --root /path/to/project

# Query
python -m agent_runtime.local_search.cli query --root /path/to/project -q "recovery closure feedback"

# Status
python -m agent_runtime.local_search.cli status
```

## Configuration

See `config/local_search.yml` for tunable parameters.

## Evidence Format

Each search result includes:
```json
{
  "path": "agent_runtime/recovery/closure_feedback.py",
  "line_start": 42,
  "line_end": 48,
  "snippet": "...relevant text around the match...",
  "score": 3.14,
  "source_category": "repo_files",
  "content_hash": "abc123..."
}
```
