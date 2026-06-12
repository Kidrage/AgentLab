# CostLedger v2

CostLedger v2 records model usage calls, token totals, pricing confidence, and
cost estimates without converting unknown prices to `$0`.

## P0.1 Pipeline Integration

- Every `append_cost_ledgers()` update refreshes `cost_ledger.yml` v2 fields.
- `cost_summary.md` is regenerated with `Pricing status`.
- `budget_gate_decision.yml` is written after each run-level cost update.

## Pricing Status

`CostLedger.total()` includes:

```yaml
pricing_status: complete | partial | unknown
unknown_priced_calls:
  - stage:
    model_alias:
    provider_model_id:
```

Definitions:

- `complete`: all calls have known estimated costs.
- `partial`: at least one call is known and at least one is unknown.
- `unknown`: all calls are unknown or there are no priced calls.

`cost_summary.md` displays:

```markdown
Pricing status: partial

Unknown priced calls:
- qwen3.6-flash
```

## BudgetGate Decision

`budget_gate_decision.yml` includes status, known cost, unknown priced calls,
total tokens, approval requirement, warnings, and active budget policy.

Unknown pricing remains `null` and may produce warnings for high-token usage; it
is never treated as zero-dollar cost unless explicitly priced as free.

## Not Supported

- LiteLLM Proxy deployment.
- AnySearch.
- CodeGraph.
- MAVIS / 3E workflow.
- Multimodal accounting.
- Treating ChatGPT/Codex subscriptions as API usage.