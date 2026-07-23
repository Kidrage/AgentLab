# AnySearch Integration

AnySearch is an optional external search provider adapter. It is disabled by
default in `config/search_providers.yml` and tests use mocks, not real network
calls.

Capabilities:

- `web_search`
- `batch_search`
- `url_extract`

The adapter does not require `ANYSEARCH_API_KEY` to exist. If anonymous mode is
allowed, artifacts record `auth_mode: anonymous`; if the provider is disabled,
the CLI writes planned/skipped evidence instead of calling the network. API keys
are never written to artifacts or logs.

Evidence artifacts are written under a task run's `artifacts/search/` directory
or local-only `.agentlab/artifacts/search/` for standalone CLI use:

- `search_ledger.yml`
- `search_results.json`
- `search_summary.md`
- `skill_usage_ledger.yml`

Unknown external provider cost is represented as `estimated_cost_usd: null` and
`token_visibility: unknown`, never as zero.
