# S5 Evidence / Recovery Intelligence

S5 connects the existing native web intelligence and local search layers to the
S1-S4 planning chain.

## Boundary

S5 is mock-first and local-first:

- no default live web fetch;
- no provider call;
- no skill dispatch;
- no bypass of S4 trust, permission, sandbox, or approval reports.

## Inputs

- `mission_contract.yml` from S1;
- optional `workflow_plan.yml` from S2;
- optional S4 validation report directory;
- optional local search index JSONL.

## CLI

```bash
./agentlab.sh local-search-index --root . --output .agentlab_runtime/local_search.jsonl

./agentlab.sh local-search-query \
  --root . \
  --index .agentlab_runtime/local_search.jsonl \
  --query "recovery evidence policy" \
  --out acceptance_runs/s5_evidence_recovery_intelligence/local_search_query.yml

./agentlab.sh web-research-plan \
  --mission-contract acceptance_runs/s5_evidence_recovery_intelligence/mission_contract.yml \
  --workflow-plan acceptance_runs/s5_evidence_recovery_intelligence/workflow_plan.yml \
  --s4-report-dir acceptance_runs/s5_evidence_recovery_intelligence/s4_reports \
  --local-index .agentlab_runtime/local_search.jsonl \
  --out acceptance_runs/s5_evidence_recovery_intelligence
```

## Outputs

`web-research-plan` writes:

- `research_plan.yml`;
- `source_plan.yml`;
- `evidence_ledger.yml`;
- `recovery_packet.yml`;
- `phase_acceptance_evidence.yml`.

## Acceptance

S5 is acceptable when:

- research planning is deterministic;
- all factual claims require source evidence;
- private, local, file, login-wall, paywall-bypass, and unbounded crawl sources
  remain blocked by policy;
- local search can provide evidence snippets with hashes and line references;
- recovery packets explain how to replan when evidence or S4 gates are missing;
- AnySearch or external providers remain optional, not required.
