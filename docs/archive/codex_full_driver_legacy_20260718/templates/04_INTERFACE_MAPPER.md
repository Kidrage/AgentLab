# Codex Full-Driver: InterfaceMapper Template

## Role
Map interfaces affected by the task — CLI commands, APIs, config schemas, file schemas, providers, backup interfaces.

## Inputs
- 01_supervisor_plan.md
- 02_reposcout_report.md (for repo context)

## Outputs
- 04_interface_map.md

## Forbidden Actions
- Implementing code changes
- Changing schema without documenting old and new schema

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/04_interface_map.md

## Completion Criteria
- [ ] All affected interfaces listed
- [ ] Existing contracts documented
- [ ] Proposed changes documented with compatibility risk
- [ ] CLI command changes (if any) documented with exact arguments
- [ ] Backward compatibility assessed
- [ ] Migration notes (if applicable)
- [ ] Next agent identified