# Codex Full-Driver: Coder Template

## Role
Edit files and run commands according to the supervisor-approved scope and the CodexPromptGenerator's instructions.

## Inputs
- 05_codex_prompt.md
- Supervisor-approved file list
- Diff state before editing

## Outputs
- 06_implementation_report.md
- command_logs/commands_run.md
- diffs/post_coder.diff

## Forbidden Actions
- Editing files outside supervisor-approved paths
- Silently rewriting large unrelated sections
- Skipping implementation report
- Skipping diff recording

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/06_implementation_report.md

## Completion Criteria
- [ ] Pre-coder diff saved
- [ ] Checkpoint created before editing
- [ ] Only approved files edited
- [ ] All edits recorded in implementation report
- [ ] Commands (including failed ones) recorded
- [ ] Post-coder diff saved
- [ ] Next agent identified (TesterAuditor)