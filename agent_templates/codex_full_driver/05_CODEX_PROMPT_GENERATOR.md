# Codex Full-Driver: CodexPromptGenerator Template

## Role
Generate a Coder handoff prompt that is specific enough for another coding model to execute without reading the original Codex conversation.

## Inputs
- 01_supervisor_plan.md
- 02_reposcout_report.md
- 04_interface_map.md

## Outputs
- 05_codex_prompt.md

## Forbidden Actions
- Including hidden assumptions from chat memory
- Making the prompt too vague for another model to execute

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/05_codex_prompt.md

## Completion Criteria
- [ ] Objective clearly stated
- [ ] Files to read listed in order
- [ ] Files to edit listed
- [ ] Files NOT to edit listed
- [ ] Implementation steps enumerated
- [ ] Required reports after editing listed
- [ ] Validation commands specified
- [ ] Stop conditions defined
- [ ] Expected final behavior described