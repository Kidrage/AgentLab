# Archive Update

## Project Memory Updates

Created AgentLab self-project memory files under `projects/AgentLab/agent_docs/`
and recorded task `task_0001` in the task ledger.

## Durable Decisions

- UI lives under `web_ui/`.
- Initial UI is static and dependency-free.
- The future data contract is `agent_status.sample.json`.
- Runtime integration should generate a snapshot instead of making the browser
  read scattered task files directly.

## Next Task Candidates

- Generate live status snapshots from `run_task.py`.
- Add Codex quota and checkpoint ledgers to the dashboard data model.
- Add visual QA when browser automation is available.
