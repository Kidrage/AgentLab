# Known Limits — P2-G Autonomous Task Smoke

## Not Supported in Current Version

### Real External Execution

AgentLab does **not** execute external agents (Codex, Cline, ECC, or any model API) by default.
All task execution is handled by `mock_executor`, which produces deterministic local-only results.

To enable real execution, you must explicitly pass `--execute` flags to the pipeline, and
configure valid API credentials. This smoke test uses `--dry-run` only.

### Real Web Search

The AnySearch provider is configured but disabled by default in `config/search_providers.yml`.
No real web searches are performed during this smoke test. All "search" results are local
file scans and fixture data.

### Real Model API Runs

No model API (OpenAI, DeepSeek, etc.) is called during this smoke test.
The `mock_executor` simulates execution without any network calls.

### Deployment Automation

AgentLab does not automate deployment to production, staging, or any remote environment.
All artifacts are written to local directories under `acceptance_runs/` or `projects/`.

### Full Autonomous Repo Modification

AgentLab does not directly modify repository code, create branches, open PRs, or push commits.
Task execution produces recommendations and revision packets that a human or external executor
would act upon.

### Production Router Auto-Mutation

Router update recommendations are **dry-run only**. Applying a router change requires:
1. An explicit `--allow-router-apply` flag
2. A valid approval artifact
3. A rollback plan

The default is to never modify production config.

## What IS Supported

- Local-first task execution with mock/dry-run providers
- 3E (Explore/Examine/Enhance) review workflow
- Unified review verdict with quality scores
- Revision packet generation for failed deliveries
- Provider governance feedback (cost, resource, evidence compliance)
- Router feedback with routing recommendations
- Dry-run router update with approval/rollback safety
- Structured artifact generation and manifest tracking
- User-readable delivery reports
- Text integrity audit guard
- Forbidden file tracking guard
- CLI integration (`./agentlab.sh p2-closure`, `./agentlab.sh p2-capability-map`)

## GitHub Actions Node.js Compatibility

The CI workflow uses `actions/checkout@v4` and `actions/setup-python@v5`, which are
the latest stable versions supporting Node.js 24. No deprecation warnings are expected
for these action versions. If GitHub deprecates older action versions in the future,
these tags will continue to resolve to compatible releases.
