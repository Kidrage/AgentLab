# AgentLab P2-B External Executor Router

## AgentLab P2-B Positioning

AgentLab does not directly own Codex/Cline/ECC subscriptions or external harnesses.
The executor router decides where a task should go, creates handoff artifacts,
records cost/risk/ledger events, and requires P2-A review before accepting
results.

P1 covers safe discovery and registration of external capabilities. P2-A is the
3E review gate. P2-B is the dispatch layer between them.

## Supported Modes

- dry-run route planning
- manual handoff
- mock executor for tests
- result ingestion
- P2-A review bridge

## Not Supported

- No real Codex CLI execution yet.
- No real Cline execution yet.
- No real ECC execution yet.
- No real API model execution yet.
- No automatic merge of external results.

## Safety Boundaries

- external providers require approval
- unknown cost requires approval
- no secrets in ledger/handoff/report
- no remote clone by router
- no MCP startup by router
- no external script execution by router
- all external results must pass P2-A review before acceptance

## Artifacts

- `route_report.yml` records the deterministic routing decision and rejected
  providers.
- `execution_plan.yml` records selected provider, execution mode, risk, cost,
  and review requirements.
- `external_execution_handoff.md` is generated for manual or approval-required
  providers.
- `approval_required.yml` is generated when a provider cannot proceed without
  user approval.
- `execution_ledger.yml` records routed, approval, handoff, mock execution,
  result ingestion, and P2-A review events.

## CLI

```bash
python scripts/p2_executor_router_check.py \
  --task-type repo_patch \
  --summary "Patch a small repo bug" \
  --output executor_runs/p2_router_demo \
  --mode dry-run
```

Use `--mode mock` to run the deterministic mock executor and send its result to
P2-A review. Use `--mode manual-handoff` to generate the handoff without running
an external tool.
