# S7 Long Project Orchestrator

S7 adds a deterministic project brain for long-running work. It turns a mission contract into recoverable project state:

- `product_vision.md`
- `project_brief.yml`
- `roadmap.yml`
- `milestone_graph.yml`
- `acceptance_history.yml`
- `next_actions.yml`
- compact `phase_summaries/` and `snapshots/`

CLI:

```bash
./agentlab.sh project-brain-init --mission-contract mission.yml --project Demo --out projects/Demo/project_brain
./agentlab.sh project-plan --project-brain projects/Demo/project_brain --out acceptance_runs/s7_long_project_orchestrator
./agentlab.sh project-next --project-brain projects/Demo/project_brain --out acceptance_runs/s7_long_project_orchestrator
./agentlab.sh phase-accept --phase-plan phase_plan.yml --evidence-dir phase_evidence --out acceptance_runs/s7_long_project_orchestrator
```

S7 is planning-only. It does not call LLMs, dispatch external agents, or execute project work directly.
