# Native Web Intelligence Layer (R4)

## Overview

R4 adds a native web intelligence scaffold so AgentLab is not fully dependent on
external providers like AnySearch. The layer is safe, limited, deterministic, and
testable entirely offline.

## Architecture

```
agent_runtime/intelligence/
  __init__.py           # Package exports
  web_policy.py         # URL safety validation (blocks private/local/dangerous)
  web_fetcher.py        # Fetcher interface + MockFetcher
  web_cache.py          # Local source snapshot cache
  source_extractor.py   # HTML/Markdown/text content extraction
  source_ranker.py      # Source quality scoring
  research_planner.py   # Query planning from task context
  research_brief.py     # Brief generation with citations
  citation_ledger.py    # Citation/provenance tracking
  cli.py                # CLI (argparse-based)
```

## Safety Policy

Blocked by default:
- `localhost`, `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- `169.254.0.0/16`, `::1`
- `file://`, `ftp://`, `ssh://`, `data:`, `javascript:`
- Private IPs, link-local IPs

Additional rules:
- Do not bypass paywalls
- Do not use credentials
- Do not execute remote scripts
- Rate limit: 10 requests/minute
- Max response: 512 KB
- Only `http` and `https` schemes allowed

## Mock Mode

All tests use `MockFetcher` which returns predefined responses for known URLs
and 404 for unknown URLs. No real internet access required.

## Source Quality Scoring

- Domain trust: 40 points (trusted domains get full score)
- Content length: 35 points (longer is better, capped at 1000 words)
- Title presence: 15 points
- Content type: 10 points (HTML/Markdown preferred)

## Citation Ledger

Every fetch records:
- URL, timestamp, fetch status
- Content hash, extracted text hash
- Title

## Research Briefs

- Generated from evidence list
- Each claim cites evidence entries
- If evidence < 3 sources, flagged as `insufficient_evidence`

## Configuration

See `config/web_intelligence.yml` and `config/source_quality_policy.yml`.

## CLI

```bash
python -m agent_runtime.intelligence.cli plan --topic "AgentLab local search"
python -m agent_runtime.intelligence.cli fetch --url "https://example.com" --mock
python -m agent_runtime.intelligence.cli brief --topic "AgentLab" --mock
```
