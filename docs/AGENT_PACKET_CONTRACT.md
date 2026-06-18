# Agent Packet Contract

`agent_packet.yml` is a lightweight handoff format for AgentLab agents.

```yaml
packet_id: packet_001
project_id: example_project
task_id: task_0001
sender: research_lead
receiver: qa_lead
purpose: review
max_context_budget_tokens: 1200
must_read:
  - artifact_index.yml
summary:
  what_changed: "Research notes were compacted."
  key_findings: []
  open_risks: []
requested_action:
  type: review
  acceptance:
    - verify artifact index exists
forbidden:
  - reread_full_raw_logs
  - modify_unrelated_files
```

Packets should stay small and point to evidence artifacts rather than embedding large raw logs.
