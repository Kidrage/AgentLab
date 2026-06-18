# Lightweight Cost Observability

AgentLab cost tracking is intentionally local and cheap by default. It must not
add model calls, web calls, billing calls, or extra agent reasoning to normal
task execution.

## Default Path

During existing agent execution, AgentLab records provider usage that is already
available in the model response:

```text
provider response usage + config/model_pricing.yml -> cost_ledger.yml
```

No extra API request is made. If usage or pricing is unavailable, the event is
recorded as unknown instead of being converted to zero.

## Accuracy Fields

Each cost event should expose:

```yaml
usage_source: provider_response | unavailable
cost_accuracy: estimated | measured | unknown
pricing_source: config/model_pricing.yml | provider_bill | unknown
pricing_confidence: high | medium | low | none
```

Meanings:

- `estimated`: provider token usage was measured, local price table estimated
  the cost.
- `measured`: a future billing/provider receipt supplied the actual cost.
- `unknown`: tokens, pricing, or external subscription usage was not visible.

## Commands

```bash
./agentlab.sh cost-status --project <ProjectName> --task-id <task_id>
./agentlab.sh cost-status --project <ProjectName> --task-id <task_id> --json
./agentlab.sh cost-doctor --project <ProjectName> --task-id <task_id>
```

`cost-status` summarizes local totals by agent and provider.

`cost-doctor` checks for lightweight observability gaps:

- missing cost ledger;
- no cost events;
- provider usage unavailable;
- usage recorded but local price unknown;
- suspicious zero-cost entries.

## Non-Goals

Default task execution does not:

- call official pricing pages;
- call billing APIs;
- ask an LLM to estimate cost;
- infer hidden Codex Plus / ChatGPT / external IDE token usage;
- block work because a subscription or plugin has unknown cost.

Manual reconciliation can be added later as an explicit command, but it must not
run in the default task path.
