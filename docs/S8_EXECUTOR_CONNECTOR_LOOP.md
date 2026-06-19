# S8 Executor Connector Loop

S8 connects S7 phases to executor task packets and evidence-based acceptance.

It reuses the existing P2 executor foundation and adds:

- phase-aware `task_packet.yml`
- connector contract with approval-first defaults
- executor result evidence collection
- diff/file-scope inspection
- executor result ledger
- phase acceptance bridge

CLI:

```bash
./agentlab.sh executor-task-create --phase-plan phase_plan.yml --executor-type mock_executor --out acceptance_runs/s8_executor_connector
./agentlab.sh executor-result-ingest --result-dir mock_result --task-packet task_packet.yml --out acceptance_runs/s8_executor_connector
./agentlab.sh executor-review --ingested-result ingested_result.yml --phase-plan phase_plan.yml --out acceptance_runs/s8_executor_connector
```

External executors such as Cline, Codex, Claude Code, and human contractors remain approval-gated and are not auto-dispatched.
