# Codex Full-Driver: Preflight Template

## Role
Perform preflight guard inspection before any code changes — check Git status, safety, and scope boundaries.

## Inputs
- user_request.md
- Git status output
- file system state

## Outputs
- 00_preflight_report.md

## Forbidden Actions
- Editing files during preflight
- Starting coding without completing preflight
- Ignoring dirty Git state

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/00_preflight_report.md

## Completion Criteria
- [ ] Git branch and commit recorded
- [ ] Dirty files recorded
- [ ] Safety checks passed (no staged secrets)
- [ ] Allowed edit scope defined
- [ ] Blockers documented (or "none")