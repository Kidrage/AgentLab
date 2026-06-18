# S5 Evidence / Recovery Intelligence Report

## Verdict

PASS.

## Scope

S5 now connects S1-S4 planning to local-first evidence and recovery artifacts.
It does not call the network, execute skills, invoke providers, or bypass S4
trust gates.

## Added

- `agent_runtime/intelligence/s5_planner.py`
- `./agentlab.sh web-research-plan`
- `./agentlab.sh local-search-index`
- `./agentlab.sh local-search-query`
- `docs/S5_EVIDENCE_RECOVERY_INTELLIGENCE.md`
- `tests/test_s5_evidence_recovery_planning.py`

## Acceptance Evidence

- S4 smoke reports were generated from
  `acceptance_runs/s5_evidence_recovery_intelligence/fixtures/safe_skill`.
- S5 generated:
  - `research_plan.yml`
  - `source_plan.yml`
  - `evidence_ledger.yml`
  - `recovery_packet.yml`
  - `phase_acceptance_evidence.yml`
- `phase_acceptance_evidence.yml` records:
  - `research_plan_generated: true`
  - `source_plan_generated: true`
  - `evidence_ledger_generated: true`
  - `private_sources_blocked_by_policy: true`
  - `s4_gate_checked: true`
  - `no_network_used: true`
  - `verdict: pass`

## Improvement Confirmed

Before this repair, the native web and local search modules existed, but the
main AgentLab CLI did not expose S5 commands and there was no artifact chain
from S4 trust reports to S5 evidence/recovery planning.

After this repair:

- AgentLab can build a deterministic local search index from the main CLI.
- AgentLab can query that index and write evidence snippets with content hashes
  and line references.
- AgentLab can generate a research plan, source plan, evidence ledger, recovery
  packet, and phase acceptance evidence from one `web-research-plan` command.
- Missing evidence blocks factual claims through `facts_allowed: false`.
- S4 trust reports are consumed before S5 marks evidence ready for review.

## Verification

```bash
python -m pytest -q tests/test_s5_evidence_recovery_planning.py
# 3 passed

python -m pytest -q tests/test_s5_evidence_recovery_planning.py tests/test_cli_contract.py tests/test_s4_skill_trust_validation.py tests/test_s3_skill_os_bridge.py
# 55 passed

python -m pytest -q tests/test_s5_evidence_recovery_planning.py tests/test_cli_contract.py
# 44 passed

python -m pytest -q
# 1269 passed, 2 skipped

python -m compileall agent_runtime/intelligence agent_runtime/local_search agent_runtime/run_task.py
# pass

./agentlab.sh local-search-index --root acceptance_runs/s5_evidence_recovery_intelligence --output local_search_index.jsonl
# indexed 1 document

./agentlab.sh local-search-query --root acceptance_runs/s5_evidence_recovery_intelligence --index local_search_index.jsonl --query "evidence ledger factual claims" --out local_search_query.yml
# pass

./agentlab.sh skill-trust-validate --package-path acceptance_runs/s5_evidence_recovery_intelligence/fixtures/safe_skill --out acceptance_runs/s5_evidence_recovery_intelligence/s4_reports --approved
# passed: true

./agentlab.sh web-research-plan --topic "S5 evidence recovery intelligence" --s4-report-dir acceptance_runs/s5_evidence_recovery_intelligence/s4_reports --local-index acceptance_runs/s5_evidence_recovery_intelligence/local_search_index.jsonl --out acceptance_runs/s5_evidence_recovery_intelligence
# local_evidence_count: 1; s4_gate_checked: true

./agentlab.sh repo-hygiene-check
# status: pass; existing warnings only

python scripts/audit_text_integrity.py
# suspicious_count: 0; verdict: PASS
```

## Boundary

S5 remains mock-first. Real web fetch, external provider search, and active
skill dispatch are still later-stage work and must stay behind policy and
approval gates.
