# Codex Full-Driver: Handoff Template

## Role
Build the machine-readable handoff packet that tells AgentLab or another model exactly where the task stopped and what to do next.

## Inputs
- All prior reports (00 through 09)
- state.yml
- progress.yml
- Git status

## Outputs
- handoff_packet.yml
- provider_incidents.yml (if quota exhaustion or errors occurred)

## Forbidden Actions
- Skipping handoff packet creation
- Setting incorrect next_agent
- Omitting resume_instructions
- Omitting required artifact paths

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/handoff_packet.yml

## Completion Criteria
- [ ] task_id and project set
- [ ] execution_mode recorded
- [ ] status correct (completed / running / paused / blocked)
- [ ] last_completed_agent set
- [ ] next_agent set (null if completed)
- [ ] All artifact paths listed
- [ ] code_state documented (branch, commit, dirty status)
- [ ] validation status recorded
- [ ] Resume instructions written for codex, api_agents, and human
- [ ] backup status recorded