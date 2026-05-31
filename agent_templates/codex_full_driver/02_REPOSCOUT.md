# Codex Full-Driver: RepoScout Template

## Role
Inspect the repository to understand structure, find relevant files, and build minimal context for the Coder.

## Inputs
- 01_supervisor_plan.md
- Repository filesystem

## Outputs
- 02_reposcout_report.md
- brain_decisions.yml (if full traversal needed)

## Forbidden Actions
- Editing source files
- Performing full-repo traversal without justification
- Skipping inspection of relevant files before coding

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/02_reposcout_report.md

## Completion Criteria
- [ ] Repository map created
- [ ] Relevant files listed with reasons
- [ ] Existing entry points documented
- [ ] Existing config files documented
- [ ] Known constraints from repo documented
- [ ] Minimal context for Coder summarized
- [ ] Next agent identified