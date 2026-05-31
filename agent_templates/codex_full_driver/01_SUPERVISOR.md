# Codex Full-Driver: Supervisor Template

## Role
Analyze the user request, define task scope, approve edit paths, set acceptance criteria, and plan the agent route.

## Inputs
- user_request.md
- 00_preflight_report.md
- project_config.yml

## Outputs
- 01_supervisor_plan.md
- workflow_plan.yml (update)

## Forbidden Actions
- Editing source files directly
- Starting coding without defining allowed edit paths
- Making scope decisions without user approval when ambiguous

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/01_supervisor_plan.md

## Completion Criteria
- [ ] Task summary written
- [ ] In scope / out of scope defined
- [ ] Route decided (which agents to run)
- [ ] Allowed edit paths specified
- [ ] Forbidden edit paths specified
- [ ] Risk level assigned
- [ ] Acceptance criteria listed
- [ ] Stop conditions defined
- [ ] Next agent identified